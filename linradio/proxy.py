"""Proxy local que quita la cuña de entrada antes de que el audio llegue a GStreamer.

Sólo se usa con las emisoras que tienen cuña medida (`memory.intro`). El resto va directo a
`playbin3`. El reproductor pide `http://127.0.0.1:<puerto>/`; el proxy abre la emisora con
metadatos ICY, pasa el audio por `IcyReframer` y lo devuelve con su entramado ICY intacto,
así que los títulos siguen llegando.
"""

import http.server
import socket
import threading
import urllib.request
from collections.abc import Callable

from . import USER_AGENT
from .intro import IcyReframer, StreamIntro

_PASSED_HEADERS = ("content-type", "icy-name", "icy-genre", "icy-br", "icy-description",
                   "icy-url", "icy-pub")


class IntroProxy:
    def __init__(self, url: str, intro: StreamIntro,
                 on_mismatch: Callable[[], None] | None = None,
                 on_skipped: Callable[[], None] | None = None) -> None:
        self.url = url
        self.intro = intro
        self._on_mismatch = on_mismatch
        self._on_skipped = on_skipped
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_args: object) -> None:
                pass

            def do_GET(self) -> None:       # noqa: N802 — nombre que exige http.server
                proxy._serve(self)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def local_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}/"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _serve(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        wants_meta = handler.headers.get("Icy-MetaData") == "1"
        request = urllib.request.Request(self.url, headers={
            "User-Agent": USER_AGENT, "Icy-MetaData": "1" if wants_meta else "0"})
        try:
            upstream = urllib.request.urlopen(request, timeout=15)
        except OSError as error:
            handler.send_error(502, str(error))
            return
        with upstream:
            raw_metaint = upstream.headers.get("icy-metaint") if wants_meta else None
            try:
                metaint = int(raw_metaint) if raw_metaint else 0
            except ValueError:
                metaint = 0
            reframer = IcyReframer(metaint, self.intro)
            handler.send_response(200)
            for name in _PASSED_HEADERS:
                value = upstream.headers.get(name)
                if value:
                    handler.send_header(name, value)
            if metaint:
                handler.send_header("icy-metaint", str(metaint))
            handler.end_headers()
            reported = False
            try:
                while True:
                    chunk = upstream.read(16384)
                    if not chunk:
                        break
                    out = reframer.feed(chunk)
                    if not reported and (reframer.mismatch or reframer.skipped):
                        reported = True
                        callback = self._on_mismatch if reframer.mismatch else self._on_skipped
                        if callback:
                            callback()
                    if out:
                        handler.wfile.write(out)
            except (OSError, socket.timeout):
                pass    # el reproductor ha colgado (cambio de emisora) o se cortó la emisora
