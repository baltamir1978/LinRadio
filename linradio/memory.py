"""Lo que se aprende de cada emisora y se guarda entre sesiones, por URL del stream.

- `title_lag`: cuánto tarda en cambiar el título tras empezar la canción (lo mide Shazam).
- `lyrics_offset`: el ajuste a mano de la letra (− / + / clic en una línea).
- `intro`: la cuña de entrada, si tiene (ver `intro.py`).

En ~/.local/state/linradio/emisoras.json: perderlo no es grave, se vuelve a aprender.
"""

import base64
import time
from pathlib import Path
from typing import Any

from . import paths
from .intro import StreamIntro
from .titles import clamp_offset, learn_title_lag


class StationMemory:
    def __init__(self, data: dict[str, dict[str, Any]] | None = None) -> None:
        self.data: dict[str, dict[str, Any]] = data or {}

    @staticmethod
    def file() -> Path:
        return paths.state_dir() / "emisoras.json"

    @classmethod
    def load(cls) -> "StationMemory":
        data = paths.read_json(cls.file(), {})
        return cls({k: v for k, v in data.items() if isinstance(v, dict)}
                   if isinstance(data, dict) else {})

    def save(self) -> None:
        paths.write_json(self.file(), self.data)

    def _entry(self, url: str) -> dict[str, Any]:
        return self.data.setdefault(url, {})

    # --- Retraso del título ----------------------------------------------------------------

    def title_lag(self, url: str) -> float:
        value = self.data.get(url, {}).get("title_lag")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def learn_title_lag(self, url: str, measured: float) -> bool:
        known = self.data.get(url, {}).get("title_lag")
        lag = learn_title_lag(float(known) if isinstance(known, (int, float)) else None, measured)
        if lag is None:
            return False
        self._entry(url)["title_lag"] = lag
        return True

    # --- Ajuste de la letra ---------------------------------------------------------------

    def lyrics_offset(self, url: str) -> float:
        value = self.data.get(url, {}).get("lyrics_offset")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def set_lyrics_offset(self, url: str, offset: float) -> None:
        offset = clamp_offset(offset)
        if offset == 0:
            self.data.get(url, {}).pop("lyrics_offset", None)
        else:
            self._entry(url)["lyrics_offset"] = offset

    # --- Cuña de entrada ------------------------------------------------------------------

    def intro(self, url: str) -> StreamIntro | None:
        raw = self.data.get(url, {}).get("intro")
        if not isinstance(raw, dict):
            return None
        try:
            return StreamIntro(length=int(raw["length"]),
                               prefix=base64.b64decode(raw.get("prefix", "")),
                               checked_at=float(raw["checked_at"]))
        except (KeyError, ValueError, TypeError):
            return None

    def record_intro(self, url: str, intro: StreamIntro) -> None:
        self._entry(url)["intro"] = {"length": intro.length,
                                     "prefix": base64.b64encode(intro.prefix).decode(),
                                     "checked_at": intro.checked_at}

    def forget_intro(self, url: str) -> None:
        self.data.get(url, {}).pop("intro", None)

    def needs_learning_intro(self, url: str, now: float | None = None) -> bool:
        """Las cuñas son anuncios y rotan: empiezan con la misma sintonía, pero cambia lo que
        duran. Con cuña se mide cada hora; sin ella, cada tres días (las emisoras las añaden)."""
        known = self.intro(url)
        if known is None:
            return True
        age = (now if now is not None else time.time()) - known.checked_at
        return age > 3600 if known.length > 0 else age > 3 * 24 * 3600
