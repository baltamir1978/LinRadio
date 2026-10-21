"""Letras de LRCLIB (lrclib.net): gratis, sin clave y casi siempre sincronizadas línea a línea.

Traducción de `LyricsService.swift` de MacRadio, con sus mismas búsquedas de repuesto.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .net import NetworkError, get_json

API = "https://lrclib.net/api/search"


@dataclass(frozen=True)
class LyricLine:
    time: float          # segundos desde el principio de la canción
    text: str


@dataclass(frozen=True)
class SongLyrics:
    synced: list[LyricLine] = field(default_factory=list)   # vacía si sólo hay texto
    plain: list[str] = field(default_factory=list)
    instrumental: bool = False
    duration: float | None = None      # la duración de la canción, si se sabe

    @property
    def empty(self) -> bool:
        return not self.synced and not self.plain

    @property
    def lines(self) -> list[str]:
        return [l.text for l in self.synced] if self.synced else self.plain

    def line_index(self, elapsed: float) -> int | None:
        """La línea que se canta a `elapsed` segundos, o None antes de la primera."""
        found = None
        for i, line in enumerate(self.synced):
            if line.time <= elapsed:
                found = i
            else:
                break
        return found


class Status(Enum):
    FOUND = "encontrada"
    NOT_FOUND = "no hay"
    FAILED = "falló la red"      # vale la pena preguntar otra vez más tarde


@dataclass(frozen=True)
class Outcome:
    status: Status
    lyrics: SongLyrics | None = None


def lookup(track: str, artist: str | None) -> Outcome:
    """La canción tal cual y, si no aparece, con título y artista cambiados: algunas emisoras
    mandan «Título - Artista» y, hasta que la carátula ponga el orden bueno, no se distinguen.

    Luego las colaboraciones: LRCLIB guarda «El Canto del Loco y Amaia Montero» bajo el
    primer nombre o escrito de otra forma, así que se prueba con el primero y, al final, con
    el título solo, aceptándolo sólo si es de alguno de los artistas.
    """
    outcome = search(track, artist)
    if outcome.status is not Status.NOT_FOUND or not artist:
        return outcome
    swapped = search(artist, track)
    if swapped.status is not Status.NOT_FOUND:
        return swapped
    names = artist_names(artist)
    if len(names) > 1:
        main = search(track, names[0], by_any_of=names)
        if main.status is not Status.NOT_FOUND:
            return main
    return search(track, None, by_any_of=names)


_SEPARATOR = re.compile(
    r"\s*(?:,|&|\+|/|\b(?:y|and|con|with|x|vs|feat|ft|featuring)\b\.?)\s*", re.IGNORECASE)


def artist_names(artist: str) -> list[str]:
    """«A y B», «A & B», «A feat. B», «A, B», «A x B» → ["A", "B"]."""
    return [p.strip() for p in _SEPARATOR.split(artist) if p.strip()]


def search(track: str, artist: str | None, by_any_of: list[str] | None = None) -> Outcome:
    title = strip_decorations(track).strip()
    params = {"track_name": title or track}
    if artist:
        params["artist_name"] = artist
    try:
        hits = get_json(API, params)
    except NetworkError:
        return Outcome(Status.FAILED)
    if not isinstance(hits, list):
        return Outcome(Status.FAILED)
    return from_hits(hits, track, by_any_of or [])


def from_hits(hits: list[Any], track: str, by_any_of: list[str]) -> Outcome:
    best = pick([h for h in hits if isinstance(h, dict)], track, by_any_of)
    if best is None:
        return Outcome(Status.NOT_FOUND)
    duration = best.get("duration")
    duration = float(duration) if isinstance(duration, (int, float)) else None
    if best.get("instrumental") is True:
        return Outcome(Status.FOUND, SongLyrics(instrumental=True, duration=duration))
    synced = parse_lrc(best.get("syncedLyrics") or "")
    plain = _trim_blank_edges([l.strip() for l in (best.get("plainLyrics") or "").splitlines()])
    lyrics = SongLyrics(synced=synced, plain=plain, duration=duration)
    return Outcome(Status.NOT_FOUND) if lyrics.empty else Outcome(Status.FOUND, lyrics)


def pick(hits: list[dict[str, Any]], track: str, by_any_of: list[str]) -> dict[str, Any] | None:
    """Prefiere una con letra sincronizada cuyo título case de verdad. Los títulos de la radio
    son descuidados («Artista - Título (Radio Edit)»), así que la búsqueda es laxa y es este
    filtro lo que evita la letra de otra canción. Las muy cortas son subidas basura."""
    wanted = normalize(strip_decorations(track))
    artists = [a for a in (normalize(n) for n in by_any_of) if a]

    def plausible(hit: dict[str, Any]) -> bool:
        duration = hit.get("duration")
        if (duration if isinstance(duration, (int, float)) else 120) <= 45:
            return False
        if artists:
            by = normalize(hit.get("artistName") or "")
            if not by or not any(a in by or by in a for a in artists):
                return False
        title = normalize(strip_decorations(hit.get("trackName") or ""))
        return bool(title) and (wanted in title or title in wanted)

    candidates = [h for h in hits if plausible(h)]
    return (next((h for h in candidates if h.get("syncedLyrics")), None)
            or next((h for h in candidates if h.get("plainLyrics") or h.get("instrumental") is True),
                    None))


_STAMP = re.compile(r"^\[([^\]]*)\]")


def parse_lrc(text: str) -> list[LyricLine]:
    """Líneas `[mm:ss.xx] texto`. Una línea con varias marcas (un estribillo escrito una vez)
    da una entrada por marca. Las etiquetas que no son tiempos (`[ar:…]`, `[offset:…]`) no."""
    lines: list[LyricLine] = []
    for raw in text.splitlines():
        rest = raw
        stamps: list[float] = []
        while (m := _STAMP.match(rest)) is not None:
            seconds = _parse_stamp(m.group(1))
            if seconds is not None:
                stamps.append(seconds)
            rest = rest[m.end():]
        body = rest.strip()
        lines += [LyricLine(t, body) for t in stamps]
    return sorted(lines, key=lambda l: l.time)


def _parse_stamp(tag: str) -> float | None:
    parts = tag.split(":")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return None


def _trim_blank_edges(lines: list[str]) -> list[str]:
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def strip_decorations(s: str) -> str:
    """Fuera «(Radio Edit)», «[Remastered]» y las coletillas «feat.» que la base no tiene."""
    out = s
    for opener in "([":
        i = out.find(opener)
        if i > 0:
            out = out[:i]
    lower = out.lower()
    for marker in (" feat.", " ft.", " featuring "):
        i = lower.find(marker)
        if i >= 0:
            out, lower = out[:i], lower[:i]
    return out


def normalize(s: str) -> str:
    """Sin tildes ni mayúsculas, y sólo letras y números: para comparar títulos."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return "".join(ch for ch in plain.casefold() if ch.isalnum())
