"""El reproductor: GStreamer `playbin3`, con reconexión y una copia del audio para Shazam.

Los títulos ICY no se leen del bus (llegan cuando el demuxer los ve, segundos antes de
sonar) sino del `audio-filter`, que está después del búfer: un evento TAG pasa por ahí
cuando su audio está a punto de sonar. Es la «marca de tiempo del bloque de metadatos
dentro del audio» de MacRadio.

En el mismo `audio-filter` un `tee` saca el audio a 16 kHz mono para `recognizer.PcmRing`,
sin abrir otra conexión.

Todo lo que avisa (`on_title`, `on_state`…) se llama en el hilo principal de GLib.
"""

import os
import time
from collections.abc import Callable
from enum import Enum

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import GLib, Gst, GstApp  # noqa: E402

from . import USER_AGENT  # noqa: E402
from .intro import StreamIntro  # noqa: E402
from .proxy import IntroProxy  # noqa: E402
from .recognizer import RATE, PcmRing  # noqa: E402

Gst.init(None)

RETRY_DELAYS = (1, 2, 4, 8, 15, 30)
# El audio que sale del filtro tarda esto en oírse (el búfer de la tarjeta).
SINK_LATENCY = 0.2


class PlayState(Enum):
    STOPPED = "Detenida"
    CONNECTING = "Conectando"
    BUFFERING = "Cargando"
    PLAYING = "Sonando"
    RETRYING = "Reconectando"


class Player:
    def __init__(self, on_title: Callable[[str, float], None],
                 on_state: Callable[[PlayState, str], None],
                 on_intro_mismatch: Callable[[str], None] | None = None) -> None:
        self._on_title = on_title
        self._on_state = on_state
        self._on_intro_mismatch = on_intro_mismatch
        self.ring = PcmRing()
        self.state = PlayState.STOPPED
        self.url: str | None = None
        self.intro: StreamIntro | None = None
        self.volume = 1.0
        self.playing_since: float | None = None
        self._playbin: Gst.Element | None = None
        self._proxy: IntroProxy | None = None
        self._retry_source = 0
        self._attempt = 0
        self._last_title = ""

    # --- Órdenes ------------------------------------------------------------------------

    def play(self, url: str, intro: StreamIntro | None = None) -> None:
        self.stop(notify=False)
        self.url = url
        self.intro = intro if intro and intro.length > 0 else None
        self._attempt = 0
        self._start()

    def stop(self, notify: bool = True) -> None:
        if self._retry_source:
            GLib.source_remove(self._retry_source)
            self._retry_source = 0
        self._teardown()
        self.url = None
        self.playing_since = None
        if notify:
            self._set_state(PlayState.STOPPED)
        else:
            self.state = PlayState.STOPPED

    def reconnect(self) -> None:
        """Tras despertar el equipo o un corte: misma emisora, conexión nueva."""
        if self.url:
            self._teardown()
            self._attempt = 0
            self._start()

    def set_volume(self, value: float) -> None:
        self.volume = max(0.0, min(1.0, value))
        if self._playbin is not None:
            self._playbin.set_property("volume", self.volume)

    # --- Por dentro ---------------------------------------------------------------------

    def _start(self) -> None:
        assert self.url is not None
        self._last_title = ""
        self.ring.clear()
        self.playing_since = None
        uri = self.url
        if self.intro is not None:
            original = self.url
            self._proxy = IntroProxy(
                original, self.intro,
                on_mismatch=lambda: GLib.idle_add(self._intro_mismatch, original))
            uri = self._proxy.local_url

        playbin = (Gst.ElementFactory.make("playbin3", None)
                   or Gst.ElementFactory.make("playbin", None))
        if playbin is None:
            self._set_state(PlayState.STOPPED, "GStreamer no tiene playbin")
            return
        # Sólo audio: aunque el stream traiga carátula como vídeo, no se pinta.
        flags = playbin.get_property("flags")
        playbin.set_property("flags", (int(flags) & ~0x1 & ~0x4) | 0x2)
        playbin.set_property("uri", uri)
        playbin.set_property("volume", self.volume)
        playbin.set_property("audio-filter", self._make_filter())
        sink_name = os.environ.get("LINRADIO_AUDIO_SINK")
        if sink_name:        # pruebas sin altavoces: LINRADIO_AUDIO_SINK=fakesink
            sink = Gst.ElementFactory.make(sink_name, None)
            if sink is not None:
                if sink.find_property("sync"):
                    sink.set_property("sync", True)
                playbin.set_property("audio-sink", sink)
        playbin.connect("source-setup", self._source_setup)
        bus = playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        self._playbin = playbin
        self._set_state(PlayState.CONNECTING)
        playbin.set_state(Gst.State.PLAYING)

    @staticmethod
    def _source_setup(_playbin: Gst.Element, source: Gst.Element) -> None:
        if source.find_property("user-agent"):
            source.set_property("user-agent", USER_AGENT)
        if source.find_property("iradio-mode"):
            source.set_property("iradio-mode", True)
        if source.find_property("timeout"):
            source.set_property("timeout", 20)

    def _make_filter(self) -> Gst.Element:
        """identity (títulos) → tee → salida, y tee → 16 kHz mono → appsink (Shazam)."""
        bin_ = Gst.Bin.new("linradio-filtro")
        identity = Gst.ElementFactory.make("identity", None)
        tee = Gst.ElementFactory.make("tee", None)
        out_queue = Gst.ElementFactory.make("queue", None)
        tap_queue = Gst.ElementFactory.make("queue", None)
        tap_queue.set_property("leaky", 2)          # downstream: nunca frena a la radio
        tap_queue.set_property("max-size-time", Gst.SECOND)
        convert = Gst.ElementFactory.make("audioconvert", None)
        resample = Gst.ElementFactory.make("audioresample", None)
        caps = Gst.ElementFactory.make("capsfilter", None)
        caps.set_property("caps", Gst.Caps.from_string(
            f"audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved"))
        sink = Gst.ElementFactory.make("appsink", None)
        sink.set_property("emit-signals", True)
        sink.set_property("sync", False)
        sink.set_property("drop", True)
        sink.set_property("max-buffers", 64)
        sink.connect("new-sample", self._on_sample)
        for element in (identity, tee, out_queue, tap_queue, convert, resample, caps, sink):
            bin_.add(element)
        identity.link(tee)
        tee.link(out_queue)
        tee.link(tap_queue)
        tap_queue.link(convert)
        convert.link(resample)
        resample.link(caps)
        caps.link(sink)
        bin_.add_pad(Gst.GhostPad.new("sink", identity.get_static_pad("sink")))
        bin_.add_pad(Gst.GhostPad.new("src", out_queue.get_static_pad("src")))
        identity.get_static_pad("src").add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM,
                                                 self._on_event)
        return bin_

    def _on_sample(self, sink: GstApp.AppSink) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        if sample is not None:
            buffer = sample.get_buffer()
            ok, info = buffer.map(Gst.MapFlags.READ)
            if ok:
                try:
                    self.ring.push(bytes(info.data))
                finally:
                    buffer.unmap(info)
        return Gst.FlowReturn.OK

    def _on_event(self, _pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        event = info.get_event()
        if event is not None and event.type == Gst.EventType.TAG:
            tags = event.parse_tag()
            ok, title = tags.get_string(Gst.TAG_TITLE)
            if ok and title and title != self._last_title:
                self._last_title = title
                heard_at = time.time() + SINK_LATENCY
                GLib.idle_add(self._emit_title, title, heard_at)
        return Gst.PadProbeReturn.OK

    def _emit_title(self, title: str, heard_at: float) -> bool:
        if self._playbin is not None:
            self._on_title(title, heard_at)
        return False

    def _intro_mismatch(self, url: str) -> bool:
        if self._on_intro_mismatch:
            self._on_intro_mismatch(url)
        return False

    def _on_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if self._playbin is None or message.src is None:
            return
        kind = message.type
        if kind == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self._schedule_retry(error.message)
        elif kind == Gst.MessageType.EOS:
            self._schedule_retry("la emisora cortó la conexión")
        elif kind == Gst.MessageType.BUFFERING:
            # La radio es en directo: una vez sonando, el búfer se rellena sin pararla, así que
            # el porcentaje sólo se enseña mientras conecta.
            if self.state in (PlayState.CONNECTING, PlayState.BUFFERING):
                percent = message.parse_buffering()
                if percent < 100:
                    if percent % 10 == 0:
                        self._set_state(PlayState.BUFFERING, f"{percent} %")
                else:
                    self._playing()
        elif kind == Gst.MessageType.STATE_CHANGED and message.src == self._playbin:
            _old, new, _pending = message.parse_state_changed()
            if new == Gst.State.PLAYING:
                self._playing()

    def _playing(self) -> None:
        if self.state is not PlayState.PLAYING:
            self._attempt = 0
            self.playing_since = time.time()
            self._set_state(PlayState.PLAYING)

    def _schedule_retry(self, why: str) -> None:
        if self.url is None or self._retry_source:
            return
        self._teardown()
        delay = RETRY_DELAYS[min(self._attempt, len(RETRY_DELAYS) - 1)]
        self._attempt += 1
        self._set_state(PlayState.RETRYING, f"{why}; otra vez en {delay} s")

        def again() -> bool:
            self._retry_source = 0
            if self.url is not None:
                self._start()
            return False
        self._retry_source = GLib.timeout_add_seconds(delay, again)

    def _teardown(self) -> None:
        playbin, self._playbin = self._playbin, None
        if playbin is not None:
            playbin.set_state(Gst.State.NULL)
            playbin.get_bus().remove_signal_watch()
        proxy, self._proxy = self._proxy, None
        if proxy is not None:
            proxy.close()

    def _set_state(self, state: PlayState, detail: str = "") -> None:
        self.state = state
        self._on_state(state, detail)
