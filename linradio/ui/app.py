"""La aplicación: una sola instancia que lleva el reproductor, la sesión, MPRIS y las órdenes
de la línea de órdenes (`linradio --play <emisora>`, `--toggle`, `--next`…)."""

import os
import sys
from collections.abc import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_ID, __version__, paths, recognizer
from ..catalog import Station, StationList
from ..history import History
from ..memory import StationMemory
from ..mpris import Controls, Mpris
from ..player import Player, PlayState
from ..session import NowPlaying, Session
from ..titles import compact
from .window import MainWindow

COMMANDS = ("--play", "--toggle", "--stop", "--next", "--previous", "--identify",
            "--favorite", "--gui")


def _soon(callback: Callable[[], None]) -> None:
    def once() -> bool:
        callback()
        return False
    GLib.idle_add(once)


class LinRadioApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name("LinRadio")
        self.window: MainWindow | None = None
        self.settings: dict[str, object] = {}
        self._held = False
        self._started = False

    # --- Arranque ----------------------------------------------------------------------

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        loaded = paths.read_json(paths.config_dir() / "ajustes.json", {})
        self.settings = loaded if isinstance(loaded, dict) else {}
        self.stations = StationList.load()
        self.history = History.load()
        self.memory = StationMemory.load()
        self.player = Player(self._on_title, self._on_state, self._intro_mismatch)
        self.player.set_volume(float(self.settings.get("volume", 1.0)))     # type: ignore[arg-type]
        self.session = Session(self.history, self.memory, self._on_now,
                               post=_soon,
                               identify=lambda: recognizer.identify(self.player.ring),
                               can_identify=lambda: recognizer.available()
                               and self.player.state is PlayState.PLAYING)
        self.mpris = Mpris(Controls(play=self.resume, pause=self.stop, toggle=self.toggle,
                                    next=lambda: self.step(1), previous=lambda: self.step(-1),
                                    raise_window=self.show_window, quit=self.quit_all,
                                    set_volume=self.set_volume),
                           APP_ID)
        GLib.timeout_add(250, self._tick)
        self._watch_sleep()

        for name, handler, accels in (
                ("toggle", self.toggle, ["<Control>p"]),
                ("next", lambda: self.step(1), ["<Control>Right"]),
                ("previous", lambda: self.step(-1), ["<Control>Left"]),
                ("identify", self.session.identify_now, ["<Control>i"]),
                ("favorite", self.session.toggle_favorite, ["<Control>d"]),
                ("lyrics-earlier", lambda: self.session.nudge_lyrics(-0.5),
                 ["<Control><Alt>Left"]),
                ("lyrics-later", lambda: self.session.nudge_lyrics(0.5),
                 ["<Control><Alt>Right"]),
                ("add-search", self._add_search, None),
                ("add-manual", self._add_manual, None),
                ("import", self._import, None),
                ("about", self._about, None),
                ("quit", self.quit_all, ["<Control>q"])):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, h=handler: h())
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        background = Gio.SimpleAction.new_stateful(
            "background", None, GLib.Variant("b", bool(self.settings.get("background", True))))
        background.connect("change-state", self._background_changed)
        self.add_action(background)
        self.set_accels_for_action("win.show-help-overlay", ["<Control>question"])

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        command = args[0] if args else "--gui"
        rest = " ".join(args[1:]).strip()
        first_time = not self._started
        self._started = True
        if command == "--play":
            station = self._find(rest) if rest else self._last_station()
            if station is None:
                command_line.printerr(f"No hay ninguna emisora que se llame «{rest}»\n")
                if first_time:
                    self.show_window()
                return 1
            self.play(station)
            if first_time:
                self.show_window()
        elif command == "--toggle":
            self.toggle()
        elif command == "--stop":
            self.stop()
        elif command == "--next":
            self.step(1)
        elif command == "--previous":
            self.step(-1)
        elif command == "--identify":
            self.session.identify_now()
        elif command == "--favorite":
            self.session.toggle_favorite()
        else:
            self.show_window()
        if first_time and self.window is None:
            self.show_window()
        return 0

    def do_activate(self) -> None:
        self.show_window()

    def show_window(self) -> None:
        if self.window is None:
            self.window = MainWindow(self)
            self.window.set_help_overlay(_shortcuts())
            self.window.connect("close-request", self._on_close)
            self._on_now(self.session.now)
            self._on_state(self.player.state, "")
            if not self.stations.stations:
                self.window.sidebar.add_from_search()
        self.window.present()

    # --- Órdenes ------------------------------------------------------------------------

    def play(self, station: Station) -> None:
        self.session.tune(station)
        intro = self.memory.intro(station.streamURL)
        self.player.play(station.streamURL, intro)
        self.settings["last_station"] = station.id
        self._save_settings()
        if self.memory.needs_learning_intro(station.streamURL):
            self._learn_intro(station.streamURL)

    def resume(self) -> None:
        if self.player.state is PlayState.STOPPED:
            station = self.session.now.station or self._last_station()
            if station is not None:
                self.play(station)

    def stop(self) -> None:
        self.player.stop()
        self.session.stop()

    def toggle(self) -> None:
        if self.player.state is PlayState.STOPPED:
            self.resume()
        else:
            self.stop()

    def step(self, delta: int) -> None:
        items = self.stations.stations
        if not items:
            return
        current = self.session.now.station or self._last_station()
        index = next((i for i, s in enumerate(items) if current and s.id == current.id), -1)
        self.play(items[(index + delta) % len(items)])

    def set_volume(self, value: float) -> None:
        self.player.set_volume(value)
        self.settings["volume"] = round(value, 2)
        self._save_settings()
        self.mpris.set_volume(value)
        if self.window is not None and abs(self.window.now_view.volume.get_value() - value) > 0.01:
            self.window.now_view.volume.set_value(value)

    def stations_changed(self) -> None:
        pass

    def quit_all(self) -> None:
        self.player.stop(notify=False)
        self.mpris.close()
        if self.window is not None:
            self.window.destroy()
        self.quit()

    # --- Avisos -------------------------------------------------------------------------

    def _on_title(self, raw: str, heard_at: float) -> None:
        self.session.on_title(raw, heard_at)

    def _on_state(self, state: PlayState, detail: str) -> None:
        if self.window is not None:
            self.window.show_state(state, detail)
        self._publish(self.session.now)

    def _on_now(self, now: NowPlaying) -> None:
        if self.window is not None:
            self.window.show_now(now)
        self._publish(now)

    def _publish(self, now: NowPlaying) -> None:
        station = now.station
        title = now.title
        stopped = self.player.state is PlayState.STOPPED
        self.mpris.update(
            playing=not stopped, stopped=stopped,
            title=title.track if title else (station.name if station else None),
            artist=title.artist if title else None,
            album=station.name if station else None,
            art_url=(now.artwork_url if title and now.artwork_url else
                     (station.logoURL if station else None)),
            track_id=(now.history_id or "ninguna").replace("-", "_"))

    def _intro_mismatch(self, url: str) -> None:
        # La conexión empezó con otros bytes y no se ha quitado nada. Lo recordado sigue sirviendo
        # si la siguiente trae la cuña de siempre: no se borra, sólo se vuelve a medir.
        self.memory.mark_intro_stale(url)
        self.memory.save()
        self._learn_intro(url)

    def _learn_intro(self, url: str) -> None:
        from .. import intro
        from .util import background

        def learned(found: intro.StreamIntro | None) -> None:
            if found is not None:
                self.memory.record_intro(url, found)
                self.memory.save()
        background(lambda: intro.learn(url), learned)

    def _tick(self) -> bool:
        if self.player.state is PlayState.PLAYING:
            self.session.tick()
        if self.window is not None:
            self.window.now_view.tick()
        return True

    # --- Ventana y segundo plano ---------------------------------------------------------

    def _on_close(self, *_args: object) -> bool:
        keep = bool(self.settings.get("background", True))
        if keep and self.player.state is not PlayState.STOPPED:
            # Sigue sonando: los controles quedan en el menú del sistema (MPRIS).
            if not self._held:
                self.hold()
                self._held = True
            self.window = None
            return False
        self.quit_all()
        return False

    def _background_changed(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        action.set_state(value)
        self.settings["background"] = value.get_boolean()
        self._save_settings()

    def _save_settings(self) -> None:
        paths.write_json(paths.config_dir() / "ajustes.json", self.settings)

    def _last_station(self) -> Station | None:
        wanted = self.settings.get("last_station")
        found = next((s for s in self.stations.stations if s.id == wanted), None)
        return found or (self.stations.stations[0] if self.stations.stations else None)

    def _find(self, name: str) -> Station | None:
        key = compact(name)
        items = self.stations.stations
        return (next((s for s in items if compact(s.name) == key), None)
                or next((s for s in items if key and key in compact(s.name)), None))

    def _watch_sleep(self) -> None:
        """Al despertar, conexión nueva: la vieja está muerta aunque nadie lo haya dicho."""
        def on_signal(_conn: Gio.DBusConnection, _sender: str, _path: str, _iface: str,
                      _signal: str, params: GLib.Variant) -> None:
            going_to_sleep = params.unpack()[0]
            if not going_to_sleep and self.player.state is not PlayState.STOPPED:
                GLib.timeout_add_seconds(2, self._reconnect_once)
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return
        bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                             "PrepareForSleep", "/org/freedesktop/login1", None,
                             Gio.DBusSignalFlags.NONE, on_signal)

    def _reconnect_once(self) -> bool:
        self.player.reconnect()
        return False

    def _add_search(self) -> None:
        if self.window is not None:
            self.window.sidebar.add_from_search()

    def _add_manual(self) -> None:
        if self.window is not None:
            self.window.sidebar.add_manually()

    def _import(self) -> None:
        if self.window is not None:
            self.window.sidebar.import_file()

    def _about(self) -> None:
        about = Adw.AboutDialog(
            application_name="LinRadio", application_icon=APP_ID, version=__version__,
            developer_name="Bruno Altamirano",
            website="https://github.com/baltamir1978/LinRadio",
            comments="Radio por internet con carátula, letra sincronizada, historial con "
                     "favoritas y reconocimiento de canciones.",
            license_type=Gtk.License.CUSTOM,
            license="Letras: LRCLIB (lrclib.net). Carátulas: iTunes Search. Emisoras: "
                    "Radio Browser. Reconocimiento: songrec, cliente no oficial de Shazam.")
        about.present(self.window)


def _shortcuts() -> Gtk.ShortcutsWindow:
    rows = [("Escuchar / parar", "space"), ("Escuchar / parar", "&lt;Control&gt;p"),
            ("Emisora siguiente", "&lt;Control&gt;Right"),
            ("Emisora anterior", "&lt;Control&gt;Left"),
            ("Identificar con Shazam", "&lt;Control&gt;i"), ("Favorita", "&lt;Control&gt;d"),
            ("Letra antes", "&lt;Control&gt;&lt;Alt&gt;Left"),
            ("Letra después", "&lt;Control&gt;&lt;Alt&gt;Right"),
            ("Salir", "&lt;Control&gt;q")]
    shortcuts = "".join(
        f'<child><object class="GtkShortcutsShortcut"><property name="title">{t}</property>'
        f'<property name="accelerator">{a}</property></object></child>' for t, a in rows)
    ui = f"""<interface><object class="GtkShortcutsWindow" id="w">
      <property name="modal">1</property>
      <child><object class="GtkShortcutsSection"><property name="section-name">main</property>
        <child><object class="GtkShortcutsGroup"><property name="title">Radio</property>
          {shortcuts}</object></child></object></child></object></interface>"""
    window: Gtk.ShortcutsWindow = Gtk.Builder.new_from_string(ui, -1).get_object("w")
    return window


def run(args: list[str]) -> int:
    code = int(LinRadioApp().run([sys.argv[0], *args]))
    # Sin esperar a los hilos que miden una cuña (hasta 35 s): lo aprendido ya está guardado
    # y una medición a medias no sirve.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
