"""El título que manda la emisora (ICY), y lo que se aprende de cada emisora con él.

Traducción de la parte de `RadioPlayer.swift` de MacRadio que no depende del reproductor:
partir «Artista - Título», reconocer los eslóganes, arreglar la codificación, y el reloj de
la letra (el retraso del título por emisora y el ajuste a mano).
"""

import time
import unicodedata
from dataclasses import dataclass

from .lyrics import artist_names


@dataclass(frozen=True)
class StreamTitle:
    track: str
    artist: str | None

    @property
    def key(self) -> str:
        return f"{self.artist or ''}|{self.track}".lower()


def repair_latin1(title: str) -> str:
    """Una emisora que manda Latin-1 («El Último» con un 0xDA suelto) puede leerse como
    Windows-1256, que convierte «Ú» en «ع». Árabe en un título se toma por ese error: se
    vuelve a los bytes originales y se leen como Windows-1252. (Pasaba con AVFoundation;
    con GStreamer está por ver, pero el arreglo no hace daño.)"""
    if not any(0x0600 <= ord(ch) <= 0x06FF for ch in title):
        return title
    try:
        return title.encode("cp1256").decode("cp1252")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return title


def is_meaningful(s: str) -> bool:
    """Los 40 Classic manda a veces un código numérico de rotación en vez de una canción."""
    return any(ch.isalpha() for ch in s)


def compact(s: str) -> str:
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return "".join(ch for ch in plain.casefold() if ch.isalnum())


def artist_key(s: str) -> str:
    """Como `compact`, pero ciego a cómo se escribe el «y» de un grupo: iTunes tiene «Fito y
    Fitipaldis» y la emisora manda «Fito & Fitipaldis»."""
    return "".join(compact(n) for n in artist_names(s))


def announces_station(title: StreamTitle, station: str) -> bool:
    """Cadena 100 manda siempre «La Mejor Variedad Musical - CADENA 100» entre canciones."""
    key = compact(station)
    return bool(key) and any(compact(p) == key for p in (title.track, title.artist) if p)


def parse(raw: str, station: str = "") -> StreamTitle | None:
    """El título ICY como canción, o None si no lo es (un código, el nombre de la emisora)."""
    cleaned = repair_latin1(raw).strip()
    if not is_meaningful(cleaned):
        return None
    # Primero « - »: un «-» a secas partiría en dos nombres como «M-Clan».
    separator = " - " if " - " in cleaned else "-"
    parts = cleaned.split(separator)
    if len(parts) >= 2:
        artist, track = parts[0].strip(), separator.join(parts[1:]).strip()
        title = StreamTitle(track, artist) if artist and track else StreamTitle(cleaned, None)
    else:
        title = StreamTitle(cleaned, None)
    if announces_station(title, station):
        return None
    return title


def same_song(a: str, b: str) -> bool:
    """Comparación laxa: «Miedo (Directo)» de la emisora es el «Miedo» de Shazam."""
    x, y = compact(a), compact(b)
    return bool(x) and bool(y) and (x in y or y in x)


def is_swapped(title: StreamTitle, found_artist: str | None) -> bool:
    """¿La emisora manda «Título - Artista»? (Cassette FM lo hace.) Nada en el título lo dice,
    pero la carátula de iTunes sí: si su artista es lo que tomamos por la canción, iba al
    revés."""
    if not title.artist or not found_artist:
        return False
    itunes = artist_key(found_artist)
    if not itunes:
        return False
    as_track, as_artist = artist_key(title.track), artist_key(title.artist)
    return as_track == itunes or (itunes in as_track and itunes not in as_artist)


# --- El reloj de la letra --------------------------------------------------------------------

LYRICS_LEAD = 1.0          # las líneas se encienden un poco antes de cantarse
MAX_OFFSET = 15.0
STALE_GRACE = 20.0         # pasada la duración + esto, se pregunta a Shazam
ASSUMED_SONG_LENGTH = 300.0
PLAUSIBLE_LAG = (-5.0, 30.0)


def learn_title_lag(known: float | None, measured: float) -> float | None:
    """Cuánto tarda la emisora en cambiar el título, promediado con lo que se sabía para que
    una medida rara no tire la letra. Fuera de lo verosímil (un acierto de Shazam en la cola
    de la canción anterior) no se aprende nada: devuelve None."""
    if not PLAUSIBLE_LAG[0] <= measured <= PLAUSIBLE_LAG[1]:
        return None
    return measured if known is None else (known + measured) / 2


def clamp_offset(offset: float) -> float:
    return min(MAX_OFFSET, max(-MAX_OFFSET, offset))


@dataclass
class SongClock:
    """Cuándo empezó la canción, y si se puede confiar en ello para seguir la letra: se vio
    cambiar el título mientras se escuchaba, o Shazam dijo por dónde va.

    `offset` es el ajuste a mano de la emisora (− / + / clic en una línea); `title_lag`, lo
    que tarda en cambiar el título, aprendido con Shazam. No se guarda entre sesiones un
    «retraso de conexión»: cambia con la cuña y el búfer y desfasaba la letra.
    """

    started_at: float | None = None
    exact: bool = False
    offset: float = 0.0

    def title_changed(self, heard_at: float, title_lag: float, seen_title_before: bool) -> None:
        """El primer título tras sintonizar es de una canción ya empezada; sólo uno que
        *cambia* mientras se escucha marca el principio de verdad."""
        self.started_at = heard_at - title_lag
        self.exact = seen_title_before

    def shazam_matched(self, matched_at: float, song_offset: float) -> None:
        self.started_at = matched_at - song_offset
        self.exact = True

    def lyrics_start(self) -> float | None:
        if self.started_at is None:
            return None
        return self.started_at - (LYRICS_LEAD + self.offset)

    def elapsed(self, now: float | None = None) -> float | None:
        start = self.lyrics_start()
        return None if start is None else (now if now is not None else time.time()) - start

    def nudge(self, seconds: float) -> None:
        self.offset = clamp_offset(self.offset + seconds)

    def sync_to_line(self, line_time: float, clicked_at: float, reaction: float = 0.3) -> None:
        """Se ha pulsado la línea que suena: la letra sigue desde ahí. Con el principio ya
        conocido, la corrección es de la emisora y va al ajuste; si se sintonizó a mitad,
        es el principio que faltaba."""
        wanted = clicked_at - line_time - reaction
        if self.exact and self.started_at is not None:
            self.offset = clamp_offset(self.started_at - wanted - LYRICS_LEAD)
        else:
            self.started_at = wanted + LYRICS_LEAD + self.offset
            self.exact = True

    def stale_deadline(self, duration: float | None) -> float | None:
        """Cuándo preguntar a Shazam si la canción sigue: la emisora puede haberse quedado con
        el título viejo (Cadena 100 pasó una canción entera sin cambiarlo)."""
        if self.started_at is None:
            return None
        return self.started_at + (duration or ASSUMED_SONG_LENGTH) + STALE_GRACE
