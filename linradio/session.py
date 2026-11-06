"""Lo que suena ahora: une el reproductor con los servicios.

Del título ICY saca la canción, la apunta en el historial, busca carátula y letra, lleva el
reloj de la letra y decide cuándo preguntar a Shazam:

- **Emisoras que no dicen qué suena** (Kiss FM): si en 20 s no llega ningún título, Shazam
  nombra las canciones cada minuto.
- **Sintonizar a mitad de una canción con letra sincronizada**: se identifica una vez sólo
  para situar la letra, sin tocar título ni historial.
- **Aprender el retraso del título**: en cada canción con letra sincronizada, a los ~20 s,
  Shazam da la posición exacta; corrige la letra y actualiza `title_lag` de la emisora.
- **Títulos que se quedan**: pasada la duración (LRCLIB; 300 s si no se sabe) + 20 s sin
  cambiar, se pregunta. Si es otra canción, el título viejo se ignora y Shazam nombra las
  canciones hasta que la emisora mande uno nuevo.

No sabe nada de GTK ni de GStreamer: el reproductor le pasa títulos con `on_title`, la
interfaz llama a `tick()` cada medio segundo y escucha `on_change`. Las búsquedas de red y
Shazam van en hilos; sus respuestas vuelven al hilo principal con `post`, que en la app es
`GLib.idle_add` y en las pruebas una llamada directa.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from . import catalog, lyrics, titles
from .catalog import Lookup, Station
from .history import History
from .lyrics import Outcome, SongLyrics, Status
from .memory import StationMemory
from .recognizer import Match
from .titles import SongClock, StreamTitle

NO_TITLE_GRACE = 20.0          # sin título ICY en este tiempo: emisora muda, manda Shazam
NAME_INTERVAL = 60.0           # Shazam nombrando canciones
LAG_PROBE_AFTER = 20.0         # cuándo medir el retraso del título en una canción nueva
POSITION_PROBE_AFTER = 13.0    # hace falta audio suficiente para la muestra


class Source(Enum):
    STATION = "emisora"
    SHAZAM = "Shazam"


class Probe(Enum):
    POSITION = "situar la letra"
    LAG = "medir el retraso del título"
    STALE = "comprobar si el título se ha quedado"
    NAME = "nombrar la canción"
    MANUAL = "identificar a petición"


@dataclass
class NowPlaying:
    station: Station | None = None
    title: StreamTitle | None = None
    source: Source = Source.STATION
    artwork_url: str | None = None
    page_url: str | None = None
    lyrics: SongLyrics | None = None
    lyrics_status: Status | None = None       # None: buscando o no aplica
    history_id: str | None = None
    favorite: bool = False
    identifying: bool = False
    message: str = ""                         # aviso breve: «Shazam no reconoce nada»…
    clock: SongClock = field(default_factory=SongClock)

    @property
    def has_song(self) -> bool:
        return self.title is not None


Post = Callable[[Callable[[], None]], None]


def _in_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class Session:
    def __init__(self, history: History, memory: StationMemory,
                 on_change: Callable[[NowPlaying], None],
                 post: Post,
                 identify: Callable[[], Match | None] | None = None,
                 lyrics_lookup: Callable[[str, str | None], Outcome] = lyrics.lookup,
                 artwork_lookup: Callable[[str, str | None],
                                          tuple[Lookup, catalog.Artwork | None]]
                 = catalog.find_artwork,
                 spawn: Callable[[Callable[[], None]], None] = _in_thread,
                 can_identify: Callable[[], bool] = lambda: True) -> None:
        self.history = history
        self.memory = memory
        self.now = NowPlaying()
        self._on_change = on_change
        self._post = post
        self._identify = identify
        self._lyrics_lookup = lyrics_lookup
        self._artwork_lookup = artwork_lookup
        self._spawn = spawn
        self._can_identify = can_identify
        self._generation = 0          # cambia con cada canción: descarta respuestas viejas
        self._tuned_at = 0.0
        self._seen_title = False
        self._any_title = False       # llegó algún título ICY, aunque fuera un eslogan
        self._title_heard_at: float | None = None
        self._stale_key: str | None = None
        self._naming = False          # Shazam nombra las canciones (emisora muda o título quedado)
        self._probes: dict[Probe, float] = {}
        self._busy = False

    # --- Lo que pide la interfaz ---------------------------------------------------------

    def tune(self, station: Station, now: float | None = None) -> None:
        self._generation += 1
        self.now = NowPlaying(station=station)
        self._tuned_at = now if now is not None else time.time()
        self._seen_title = False
        self._any_title = False
        self._title_heard_at = None
        self._stale_key = None
        self._naming = False
        self._probes = {}
        self._changed()

    def stop(self) -> None:
        self._generation += 1
        self._probes = {}
        self._naming = False
        station = self.now.station
        self.now = NowPlaying(station=station)
        self._changed()

    def identify_now(self) -> None:
        """Botón «Identificar»: si Shazam reconoce otra canción, pasa a mandar él."""
        self._run_probe(Probe.MANUAL)

    def toggle_favorite(self) -> None:
        if self.now.history_id:
            self.history.toggle_favorite(self.now.history_id)
            song = self.history.get(self.now.history_id)
            self.now.favorite = bool(song and song.favorite)
            self.history.save()
            self._changed()

    def nudge_lyrics(self, seconds: float) -> None:
        self.now.clock.nudge(seconds)
        self._remember_offset()

    def reset_lyrics_offset(self) -> None:
        self.now.clock.offset = 0.0
        self._remember_offset()

    def sync_to_line(self, index: int, now: float | None = None) -> None:
        lyr = self.now.lyrics
        if lyr is None or not 0 <= index < len(lyr.synced):
            return
        was_exact = self.now.clock.exact
        self.now.clock.sync_to_line(lyr.synced[index].time, now if now is not None else time.time())
        if was_exact:
            self._remember_offset()
        else:
            self._changed()

    def _remember_offset(self) -> None:
        station = self.now.station
        if station is not None:
            self.memory.set_lyrics_offset(station.streamURL, self.now.clock.offset)
            self.memory.save()
        self._changed()

    # --- Lo que llega del reproductor ------------------------------------------------------

    def on_title(self, raw: str, heard_at: float) -> None:
        station = self.now.station
        if station is None:
            return
        self._any_title = True
        parsed = titles.parse(raw, station.name)
        if parsed is None:
            # Un eslogan o un código: no es una canción. Si manda Shazam, sigue mandando.
            if not self._naming and self.now.title is not None \
                    and self.now.source is Source.STATION:
                self._clear_song()
            return
        if self._stale_key is not None and parsed.key == self._stale_key:
            return              # el título que se quedó, otra vez: se ignora
        current = self.now.title
        if current is not None and current.key == parsed.key and \
                self.now.source is Source.STATION:
            return              # una reconexión que repite el título
        if self._naming:
            self._naming = False
            self._stale_key = None
            self._probes.pop(Probe.NAME, None)
            if current is not None and titles.same_song(current.track, parsed.track):
                # La emisora ha vuelto con la canción que ya había puesto Shazam.
                self.now.source = Source.STATION
                self._changed()
                return
        self._new_song(parsed, Source.STATION, heard_at)

    # --- El reloj ---------------------------------------------------------------------

    def tick(self, now: float | None = None) -> None:
        t = now if now is not None else time.time()
        if self.now.station is None:
            return
        # Emisora muda: pasan 20 s sin ningún título.
        if not self._any_title and not self._naming and \
                t - self._tuned_at >= NO_TITLE_GRACE:
            self._naming = True
            self._probes[Probe.NAME] = t
        # Título que se queda.
        if self.now.title is not None and self.now.source is Source.STATION and \
                not self._naming and Probe.STALE not in self._probes:
            duration = self.now.lyrics.duration if self.now.lyrics else None
            deadline = self.now.clock.stale_deadline(duration)
            if deadline is not None and t >= deadline:
                self._probes[Probe.STALE] = t
        if self._busy:
            return
        due = [p for p, at in self._probes.items() if at <= t]
        if due:
            order = [Probe.MANUAL, Probe.NAME, Probe.STALE, Probe.POSITION, Probe.LAG]
            self._run_probe(min(due, key=order.index))

    # --- Canciones ----------------------------------------------------------------------

    def _new_song(self, title: StreamTitle, source: Source, heard_at: float,
                  match: Match | None = None) -> None:
        station = self.now.station
        assert station is not None
        self._generation += 1
        generation = self._generation
        clock = SongClock(offset=self.memory.lyrics_offset(station.streamURL))
        if match is not None:
            clock.shazam_matched(match.heard_at, match.song_offset)
            clock.offset = 0.0
        else:
            clock.title_changed(heard_at, self.memory.title_lag(station.streamURL),
                                self._seen_title)
            self._seen_title = True
            self._title_heard_at = heard_at
        song_id = self.history.record(title.track, title.artist, station.name)
        self.history.save()
        self.now = NowPlaying(station=station, title=title, source=source, clock=clock,
                              history_id=song_id,
                              artwork_url=match.artwork_url if match else None,
                              page_url=match.page_url if match else None)
        for probe in (Probe.POSITION, Probe.LAG, Probe.STALE):
            self._probes.pop(probe, None)
        if song_id and match and match.artwork_url:
            self._update_history(song_id, artwork_url=match.artwork_url,
                                 page_url=match.page_url)
        self._changed()
        if not (match and match.artwork_url):
            self._spawn(lambda: self._fetch_artwork(generation, title))
        self._spawn(lambda: self._fetch_lyrics(generation, title))

    def _clear_song(self) -> None:
        self._generation += 1
        station = self.now.station
        self.now = NowPlaying(station=station)
        for probe in (Probe.POSITION, Probe.LAG, Probe.STALE):
            self._probes.pop(probe, None)
        self._changed()

    def _fetch_artwork(self, generation: int, title: StreamTitle) -> None:
        status, art = self._artwork_lookup(title.track, title.artist)
        self._post(lambda: self._artwork_arrived(generation, title, status, art))

    def _artwork_arrived(self, generation: int, title: StreamTitle, status: Lookup,
                         art: catalog.Artwork | None) -> None:
        if generation != self._generation or status is not Lookup.FOUND or art is None:
            return
        self.now.artwork_url = art.image_url
        self.now.page_url = art.page_url
        fixed = title
        if titles.is_swapped(title, art.artist):
            # La emisora manda «Título - Artista» (Cassette FM): manda iTunes.
            fixed = StreamTitle(track=title.artist or title.track, artist=title.track)
            self.now.title = fixed
        if self.now.history_id:
            self._update_history(self.now.history_id, title=fixed.track, artist=fixed.artist,
                                 artwork_url=art.image_url, page_url=art.page_url)
        self._changed()

    def _update_history(self, song_id: str, **values: str | None) -> None:
        song = self.history.get(song_id)
        if song is None:
            return
        for key, value in values.items():
            if value is not None:
                setattr(song, key, value)
        self.history.save()

    def _fetch_lyrics(self, generation: int, title: StreamTitle) -> None:
        outcome = self._lyrics_lookup(title.track, title.artist)
        self._post(lambda: self._lyrics_arrived(generation, outcome))

    def _lyrics_arrived(self, generation: int, outcome: Outcome) -> None:
        if generation != self._generation:
            return
        self.now.lyrics = outcome.lyrics
        self.now.lyrics_status = outcome.status
        synced = bool(outcome.lyrics and outcome.lyrics.synced)
        if synced and self._can_identify():
            clock = self.now.clock
            if clock.exact and self.now.source is Source.STATION and clock.started_at:
                # Se vio cambiar el título: Shazam mide cuánto tarda la emisora.
                self._probes[Probe.LAG] = max(time.time(), clock.started_at + LAG_PROBE_AFTER)
            elif not clock.exact:
                # Se sintonizó a mitad: Shazam sitúa la letra.
                self._probes[Probe.POSITION] = max(time.time(),
                                                   self._tuned_at + POSITION_PROBE_AFTER)
        self._changed()

    # --- Shazam ---------------------------------------------------------------------------

    def _run_probe(self, probe: Probe) -> None:
        self._probes.pop(probe, None)
        if self._identify is None or self._busy or not self._can_identify():
            if probe is Probe.MANUAL:
                self.now.message = "Shazam no está disponible (falta songrec)"
                self._changed()
            return
        self._busy = True
        generation = self._generation
        visible = probe in (Probe.MANUAL, Probe.NAME, Probe.STALE)
        if visible:
            self.now.identifying = True
            self.now.message = ""
            self._changed()
        identify = self._identify

        def work() -> None:
            try:
                match = identify()
                error = ""
            except Exception as failure:        # noqa: BLE001 — Shazam no debe tumbar nada
                match, error = None, str(failure)
            self._post(lambda: self._probe_done(probe, generation, match, error))

        self._spawn(work)

    def _probe_done(self, probe: Probe, generation: int, match: Match | None,
                    error: str) -> None:
        self._busy = False
        self.now.identifying = False
        if self.now.station is None:
            return
        now = time.time()
        current = self.now.title

        if probe in (Probe.POSITION, Probe.LAG):
            if generation != self._generation or match is None or current is None:
                return
            if not titles.same_song(current.track, match.track):
                return
            clock = self.now.clock
            if probe is Probe.LAG and self._title_heard_at is not None:
                started = match.heard_at - match.song_offset
                station = self.now.station
                if self.memory.learn_title_lag(station.streamURL, self._title_heard_at - started):
                    self.memory.save()
            clock.shazam_matched(match.heard_at, match.song_offset)
            clock.offset = 0.0
            self._changed()
            return

        if error:
            self.now.message = f"Shazam: {error}"
        if probe is Probe.STALE:
            if match is None:
                if not error:
                    self._clear_song()              # anuncios o locutor: el logo
                self._probes[Probe.STALE] = now + NAME_INTERVAL
            elif current is not None and titles.same_song(current.track, match.track):
                self._probes[Probe.STALE] = now + NAME_INTERVAL     # una versión más larga
            else:
                self._stale_key = current.key if current else None
                self._naming = True
                self._probes[Probe.NAME] = now + NAME_INTERVAL
                self._song_from_match(match)
            self._changed()
            return

        # NAME y MANUAL
        if self._naming:
            self._probes[Probe.NAME] = now + NAME_INTERVAL
        if match is None:
            if probe is Probe.MANUAL and not error:
                self.now.message = "Shazam no reconoce lo que suena"
            elif self._naming and self.now.source is Source.SHAZAM and not error:
                self._clear_song()
            self._changed()
            return
        if current is not None and titles.same_song(current.track, match.track):
            self.now.clock.shazam_matched(match.heard_at, match.song_offset)
            self.now.clock.offset = 0.0
            if probe is Probe.MANUAL:
                self.now.message = "Es la canción que dice la emisora"
            self._changed()
            return
        if probe is Probe.MANUAL and not self._naming and current is not None:
            # La emisora dice una cosa y suena otra: el título se ha quedado.
            self._stale_key = current.key
            self._naming = True
            self._probes[Probe.NAME] = now + NAME_INTERVAL
        self._song_from_match(match)

    def _song_from_match(self, match: Match) -> None:
        self._new_song(StreamTitle(match.track, match.artist), Source.SHAZAM, match.heard_at,
                       match=match)

    def _changed(self) -> None:
        if self.now.history_id:
            song = self.history.get(self.now.history_id)
            self.now.favorite = bool(song and song.favorite)
        self._on_change(self.now)
