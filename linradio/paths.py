"""Carpetas XDG y escritura atómica."""

import json
import os
from pathlib import Path
from typing import Any

APP = "linradio"


def _xdg(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    return Path(value) if value and os.path.isabs(value) else Path.home() / fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def data_dir() -> Path:
    """Emisoras e historial: lo que se echaría de menos."""
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def state_dir() -> Path:
    """Lo aprendido de cada emisora (retraso del título, ajuste de la letra, cuñas)."""
    return _xdg("XDG_STATE_HOME", ".local/state") / APP


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".nuevo")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
