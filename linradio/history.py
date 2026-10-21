"""Las canciones oídas, con favoritas y la lista de títulos ignorados.

El mismo modelo que MacRadio y RadioApp. Lo alimenta el reproductor y no una ventana, para
que siga apuntando con la ventana cerrada.
"""

import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths

MAX_ENTRIES = 1000       # las favoritas no cuentan: no caducan nunca


@dataclass
class ListenedSong:
    title: str
    station_name: str
    artist: str | None = None
    listened_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    artwork_url: str | None = None
    page_url: str | None = None
    # La guarda el usuario (corazón): sobrevive a «borrar para siempre» y a vaciar el resto.
    favorite: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()).upper())

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ListenedSong | None":
        if not isinstance(data.get("title"), str) or not isinstance(data.get("station_name"), str):
            return None
        song = cls(title=data["title"], station_name=data["station_name"])
        for key in ("artist", "listened_at", "artwork_url", "page_url", "id"):
            if isinstance(data.get(key), str):
                setattr(song, key, data[key])
        song.favorite = data.get("favorite") is True
        return song


def _norm(s: str) -> str:
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", s.strip())
                    if not unicodedata.combining(ch))
    return plain.casefold()


def ignore_key(station: str, title: str) -> str:
    return f"{_norm(station)}\n{_norm(title)}"


@dataclass(frozen=True)
class IgnoredTitle:
    """Un título de una emisora que el usuario no quiere en el historial: los eslóganes y
    cuñas que algunas mandan como si fueran canciones."""
    station_name: str
    title: str

    @property
    def key(self) -> str:
        return ignore_key(self.station_name, self.title)


class History:
    def __init__(self, songs: list[ListenedSong] | None = None,
                 ignored: list[IgnoredTitle] | None = None) -> None:
        self.songs = songs or []
        self.ignored = ignored or []

    # --- Archivos ----------------------------------------------------------------------

    @staticmethod
    def songs_file() -> Path:
        return paths.data_dir() / "historial.json"

    @staticmethod
    def ignored_file() -> Path:
        return paths.data_dir() / "titulos-ignorados.json"

    @classmethod
    def load(cls) -> "History":
        songs = paths.read_json(cls.songs_file(), [])
        ignored = paths.read_json(cls.ignored_file(), [])
        return cls(
            [s for s in (ListenedSong.from_json(d) for d in songs if isinstance(d, dict)) if s]
            if isinstance(songs, list) else [],
            [IgnoredTitle(d["station_name"], d["title"]) for d in ignored
             if isinstance(d, dict) and isinstance(d.get("station_name"), str)
             and isinstance(d.get("title"), str)] if isinstance(ignored, list) else [])

    def save(self) -> None:
        paths.write_json(self.songs_file(), [asdict(s) for s in self.songs])
        paths.write_json(self.ignored_file(), [asdict(i) for i in self.ignored])

    # --- Apuntar -----------------------------------------------------------------------

    def record(self, title: str, artist: str | None, station_name: str) -> str | None:
        """Apunta una canción al empezar y devuelve su id, para que el reproductor rellene
        luego la carátula y arregle el orden de título y artista. None si el título está
        ignorado; el id de la última si es la misma (una reconexión la vuelve a mandar)."""
        title = title.strip()
        if not title or self.is_ignored(title, station_name):
            return None
        if self.songs and self.songs[0].station_name == station_name \
                and self.songs[0].title == title:
            return self.songs[0].id
        song = ListenedSong(title=title, artist=artist, station_name=station_name)
        self.songs.insert(0, song)
        self._trim()
        return song.id

    def get(self, song_id: str) -> ListenedSong | None:
        return next((s for s in self.songs if s.id == song_id), None)

    def toggle_favorite(self, song_id: str) -> None:
        song = self.get(song_id)
        if song:
            song.favorite = not song.favorite

    def delete(self, ids: set[str]) -> None:
        self.songs = [s for s in self.songs if s.id not in ids]

    def clear_non_favorites(self) -> None:
        """Vacía el historial pero deja las favoritas: perderlas sin querer dolería."""
        self.songs = [s for s in self.songs if s.favorite]

    # --- Ignorados ---------------------------------------------------------------------

    def is_ignored(self, title: str, station_name: str) -> bool:
        key = ignore_key(station_name, title)
        return any(i.key == key for i in self.ignored)

    def ignore_and_purge(self, song: ListenedSong) -> None:
        """«Borrar para siempre»: ese título de esa emisora no se vuelve a apuntar, y se van
        las copias que ya hay, salvo las favoritas."""
        entry = IgnoredTitle(song.station_name, song.title)
        if not any(i.key == entry.key for i in self.ignored):
            self.ignored.insert(0, entry)
        self.songs = [s for s in self.songs
                      if s.favorite or ignore_key(s.station_name, s.title) != entry.key]

    def unignore(self, entry: IgnoredTitle) -> None:
        self.ignored = [i for i in self.ignored if i.key != entry.key]

    def _trim(self) -> None:
        """Fuera las más viejas que no son favoritas, pasado el tope."""
        excess = len(self.songs) - MAX_ENTRIES
        if excess <= 0:
            return
        keep: list[ListenedSong] = []
        for song in reversed(self.songs):
            if excess > 0 and not song.favorite:
                excess -= 1
                continue
            keep.append(song)
        self.songs = list(reversed(keep))
