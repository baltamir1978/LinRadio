"""Shazam sobre el propio stream, con songrec (cliente no oficial, en Rust).

El reproductor deja una copia del audio que suena (16 kHz, mono, 16 bits) en `PcmRing`; para
identificar se escriben los últimos 12 s en un WAV y se le pasan a
`songrec audio-file-to-recognized-song`. Puede romperse si Shazam cambia algo: entonces
sólo se pierde la identificación, nunca la radio.

La copia sale de *después* del búfer del reproductor, así que llega al ritmo al que suena:
la ráfaga de audio atrasado que mandan algunas emisoras al conectar (Cadena 100: 5,2 s en
medio segundo) ya está absorbida y no corre la posición.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RATE = 16000
SAMPLE_BYTES = 2
SAMPLE_SECONDS = 12.0
MIN_SECONDS = 8.0
TIMEOUT = 40


@dataclass(frozen=True)
class Match:
    track: str
    artist: str | None
    song_offset: float          # segundos de canción que han sonado al final de la muestra
    heard_at: float             # reloj de pared del final de la muestra
    artwork_url: str | None
    page_url: str | None


class PcmRing:
    """Los últimos segundos de audio, con la hora a la que llegó el último trozo."""

    def __init__(self, seconds: float = 20.0) -> None:
        self._capacity = int(seconds * RATE) * SAMPLE_BYTES
        self._data = bytearray()
        self._lock = threading.Lock()
        self.last_at = 0.0

    def push(self, chunk: bytes, at: float | None = None) -> None:
        with self._lock:
            self._data += chunk
            if len(self._data) > self._capacity:
                del self._data[:len(self._data) - self._capacity]
            self.last_at = at if at is not None else time.time()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.last_at = 0.0

    def seconds(self) -> float:
        with self._lock:
            return len(self._data) / (RATE * SAMPLE_BYTES)

    def snapshot(self, seconds: float = SAMPLE_SECONDS) -> tuple[bytes, float]:
        """(PCM de los últimos `seconds`, hora del final)."""
        wanted = int(seconds * RATE) * SAMPLE_BYTES
        with self._lock:
            return bytes(self._data[-wanted:]), self.last_at


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(SAMPLE_BYTES)
        out.setframerate(RATE)
        out.writeframes(pcm)


def songrec_path() -> Path | None:
    """songrec del sistema, el compilado con cargo o el que lleve el paquete."""
    here = Path(__file__).resolve().parent.parent / "build" / "songrec"   # al desarrollar
    for candidate in (os.environ.get("LINRADIO_SONGREC"), shutil.which("songrec"),
                      "/usr/lib/linradio/songrec", str(Path.home() / ".cargo/bin/songrec"),
                      str(here)):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate)
    return None


def available() -> bool:
    return songrec_path() is not None


def parse(data: Any, heard_at: float, sample_seconds: float) -> Match | None:
    """La respuesta de Shazam (lo que imprime songrec) como `Match`, o None si no reconoce."""
    if not isinstance(data, dict):
        return None
    track = data.get("track")
    matches = data.get("matches")
    if not isinstance(track, dict) or not isinstance(matches, list) or not matches:
        return None
    title = track.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    first = matches[0] if isinstance(matches[0], dict) else {}
    offset = first.get("offset")
    # `offset` es por dónde iba la canción al *empezar* la muestra.
    song_offset = (float(offset) if isinstance(offset, (int, float)) else 0.0) + sample_seconds
    artist = track.get("subtitle")
    raw_images = track.get("images")
    images: dict[str, Any] = raw_images if isinstance(raw_images, dict) else {}
    art = images.get("coverarthq") or images.get("coverart")
    page = track.get("url")
    return Match(track=title.strip(),
                 artist=artist.strip() if isinstance(artist, str) and artist.strip() else None,
                 song_offset=song_offset, heard_at=heard_at,
                 artwork_url=art if isinstance(art, str) else None,
                 page_url=page if isinstance(page, str) else None)


class RecognizerError(Exception):
    pass


def identify(ring: PcmRing) -> Match | None:
    """Bloquea unos segundos. None: Shazam no reconoce nada (anuncios, locutor)."""
    binary = songrec_path()
    if binary is None:
        raise RecognizerError("songrec no está instalado")
    if ring.seconds() < MIN_SECONDS:
        raise RecognizerError("todavía no hay audio suficiente")
    pcm, heard_at = ring.snapshot()
    sample_seconds = len(pcm) / (RATE * SAMPLE_BYTES)
    with tempfile.TemporaryDirectory(prefix="linradio-") as folder:
        wav = Path(folder) / "muestra.wav"
        write_wav(wav, pcm)
        try:
            done = subprocess.run([str(binary), "audio-file-to-recognized-song", str(wav)],
                                  capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RecognizerError(str(error)) from error
    if done.returncode != 0:
        raise RecognizerError(done.stderr.strip().splitlines()[-1] if done.stderr.strip()
                              else f"songrec terminó con código {done.returncode}")
    try:
        data = json.loads(done.stdout)
    except ValueError as error:
        raise RecognizerError("songrec no devolvió JSON") from error
    return parse(data, heard_at, sample_seconds)
