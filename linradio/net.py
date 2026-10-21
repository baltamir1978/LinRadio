"""Peticiones HTTP con la biblioteca estándar, distinguiendo «no hay» de «ha fallado la red».

La diferencia importa: una carátula que no existe no se vuelve a pedir; una que no llegó
porque iTunes cortó con un 403 (lo hace con las ráfagas), sí.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import USER_AGENT


class NetworkError(Exception):
    """La red o el servidor fallaron: merece la pena volver a intentarlo."""


def get_json(url: str, params: dict[str, str] | None = None, timeout: float = 20,
             retries: int = 2) -> Any:
    """`timeout` de 20 s y no 12 como en MacRadio: LRCLIB llega a tardar 14 s en contestar
    una búsqueda (medido el 21-oct-2026). Y si contesta «ocupado» (503, o 429 por exceso de
    peticiones) se reintenta a los 2 y a los 4 s: le pasa a ratos y al azar (la misma
    búsqueda da 503 y al momento 200), y se le pasa enseguida."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw: bytes = response.read()
    except urllib.error.HTTPError as error:
        if retries > 0 and error.code in (429, 503):
            time.sleep(2 * (3 - retries))
            return get_json(url, None, timeout, retries - 1)
        raise NetworkError(f"el servidor respondió {error.code}") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise NetworkError(str(getattr(error, "reason", error))) from error
    try:
        return json.loads(raw)
    except ValueError as error:
        raise NetworkError("la respuesta no es JSON") from error
