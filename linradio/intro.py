"""La cuña de entrada: un clip fijo —casi siempre anuncios— que algunos servidores ponen a
cada oyente que se conecta, antes del directo. La Indie manda unos 20 s, y en cada reconexión.

Una cuña es un archivo: los mismos bytes en cada conexión, mientras que el directo nunca se
repite. Dos conexiones abiertas con unos segundos de diferencia coinciden exactamente lo que
dura la cuña y ni un byte más: así se mide (`learn`). Ya conocida, se reconoce por sus
primeros bytes y se quita (`IcyReframer`). El servidor la manda a doble velocidad, así que
saltarla cuesta unos segundos de conexión en vez de veinte de anuncios.

Traducción de `StreamIntro.swift` de MacRadio. Lo de los bytes es independiente del
reproductor; con GStreamer, `IcyReframer` irá en el elemento que lee el stream.
"""

import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import USER_AGENT

MINIMUM_INTRO = 32 * 1024     # por debajo, coincidir es sólo la cabecera de trama común
PREFIX_LENGTH = 8 * 1024
CAPTURE_BYTES = 1_500_000
CAPTURE_SECONDS = 30


@dataclass(frozen=True)
class StreamIntro:
    length: int          # bytes de audio que quitar; 0 apunta «esta emisora no tiene cuña»
    prefix: bytes        # sus primeros bytes, para reconocerla antes de quitar nada
    checked_at: float


def intro_length(a: bytes, b: bytes) -> int:
    """Dónde dejan de coincidir dos capturas del mismo stream.

    El directo justo tras la cuña empieza con los mismos bytes de cabecera de trama que las
    tramas de la cuña, así que la coincidencia en bruto se mete unos bytes en la primera trama
    del directo: el corte vuelve a su palabra de sincronía (0xFF Ex de MP3).
    """
    limit = min(len(a), len(b))
    n = 0
    while n < limit and a[n] == b[n]:
        n += 1
    # Coincidir hasta el final quiere decir que una captura se cortó, no que haya cuña.
    if n < MINIMUM_INTRO or n >= limit:
        return 0
    for i in range(n, max(0, n - 8) - 1, -1):
        if i + 1 < len(a) and a[i] == 0xFF and (a[i + 1] & 0xE0) == 0xE0:
            return i
    return n


def _capture(url: str, delay: float) -> bytes | None:
    """Hasta 1,5 MB o 30 s de audio en bruto, sin metadatos ICY para que los bytes casen."""
    if delay:
        time.sleep(delay)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    data = bytearray()
    deadline = time.monotonic() + CAPTURE_SECONDS
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                return None
            while len(data) < CAPTURE_BYTES and time.monotonic() < deadline:
                chunk = response.read(16384)
                if not chunk:
                    break
                data += chunk
    except OSError:
        return bytes(data) or None
    return bytes(data)


_running: set[str] = set()
_running_lock = threading.Lock()


def learn(url: str) -> StreamIntro | None:
    """Mide la cuña con dos conexiones abiertas a 4 s una de otra. Bloquea unos 35 s."""
    if url.lower().endswith(".m3u8"):
        return None
    with _running_lock:
        if url in _running:
            return None
        _running.add(url)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_capture, url, 0)
            second = pool.submit(_capture, url, 4)
            a, b = first.result(), second.result()
        if a is None or b is None:
            return None
        length = intro_length(a, b)
        return StreamIntro(length=length, prefix=a[:PREFIX_LENGTH] if length else b"",
                           checked_at=time.time())
    finally:
        with _running_lock:
            _running.discard(url)


class IcyReframer:
    """Quita una cuña conocida de un stream camino del reproductor.

    Los streams ICY intercalan un bloque de metadatos cada `metaint` bytes de audio, y el
    reproductor cuenta esos bytes desde el principio de la conexión. Recortar audio del
    principio dejaría todos los bloques fuera de sitio y se perderían los títulos, así que el
    stream se desmonta y se vuelve a montar: se separan audio y metadatos al entrar, se tira
    el audio de la cuña y el resto sale con su propio entramado al mismo intervalo, con el
    último título.

    No se tira nada hasta que los primeros bytes coinciden con la cuña recordada; si no
    coinciden, todo pasa tal cual y `mismatch` avisa de que hay que volver a medirla.
    """

    def __init__(self, metaint: int, intro: StreamIntro) -> None:
        self.metaint = metaint
        self.intro = intro
        self._in_audio_left = metaint
        self._in_meta_left = -1
        self._in_meta = bytearray()
        self._out_audio_since_meta = 0
        self._pending_meta: bytes | None = None
        self._checking = True
        self._held = bytearray()
        self._to_skip = intro.length
        self.mismatch = False
        self.skipped = False

    def feed(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        n_total = len(data)
        while i < n_total:
            if self.metaint > 0 and self._in_meta_left >= 0:
                n = min(self._in_meta_left, n_total - i)
                self._in_meta += data[i:i + n]
                self._in_meta_left -= n
                i += n
                if self._in_meta_left == 0:
                    self._pending_meta = bytes(self._in_meta)
                    self._in_meta_left = -1
                    self._in_audio_left = self.metaint
            elif self.metaint > 0 and self._in_audio_left == 0:
                length = data[i] * 16
                i += 1
                if length == 0:
                    self._in_audio_left = self.metaint
                else:
                    self._in_meta = bytearray([data[i - 1]])
                    self._in_meta_left = length
            else:
                n = min(self._in_audio_left, n_total - i) if self.metaint > 0 else n_total - i
                self._audio(data[i:i + n], out)
                i += n
                if self.metaint > 0:
                    self._in_audio_left -= n
        return bytes(out)

    def _audio(self, chunk: bytes, out: bytearray) -> None:
        if self._checking:
            self._held += chunk
            if len(self._held) < len(self.intro.prefix):
                return
            self._checking = False
            waiting = bytes(self._held)
            self._held = bytearray()
            if waiting[:len(self.intro.prefix)] == self.intro.prefix:
                self.skipped = True
                self._drop(waiting, out)
            else:
                self.mismatch = True
                self._to_skip = 0
                self._emit(waiting, out)
            return
        self._drop(chunk, out)

    def _drop(self, chunk: bytes, out: bytearray) -> None:
        if self._to_skip <= 0:
            self._emit(chunk, out)
            return
        n = min(self._to_skip, len(chunk))
        self._to_skip -= n
        if n < len(chunk):
            self._emit(chunk[n:], out)

    def _emit(self, audio: bytes, out: bytearray) -> None:
        if self.metaint <= 0:
            out += audio
            return
        rest = audio
        while rest:
            n = min(self.metaint - self._out_audio_since_meta, len(rest))
            out += rest[:n]
            rest = rest[n:]
            self._out_audio_since_meta += n
            if self._out_audio_since_meta == self.metaint:
                out += self._pending_meta if self._pending_meta is not None else b"\x00"
                self._pending_meta = None
                self._out_audio_since_meta = 0
