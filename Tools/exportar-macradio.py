#!/usr/bin/env python3
"""Saca las emisoras de MacRadio a un JSON que LinRadio importa (`linradio --importar`).

Se ejecuta en el Mac. MacRadio las guarda dentro de sus preferencias (la clave
`saved_stations`, con el mismo JSON que usa LinRadio). Sólo lee: no toca MacRadio.

Uso:  Tools/exportar-macradio.py > emisoras.json
"""

import json
import plistlib
import sys
from pathlib import Path

PREFS = Path.home() / ("Library/Containers/Altamirano.MacRadio/Data/Library/Preferences/"
                       "Altamirano.MacRadio.plist")


def main() -> int:
    try:
        prefs = plistlib.loads(PREFS.read_bytes())
    except OSError:
        print(f"✗ No encuentro las preferencias de MacRadio en {PREFS}", file=sys.stderr)
        return 1
    raw = prefs.get("saved_stations")
    if raw is None:
        print("✗ MacRadio no tiene emisoras guardadas (usa la lista de partida, que LinRadio "
              "ya trae).", file=sys.stderr)
        return 1
    stations = json.loads(raw)
    json.dump(stations, sys.stdout, ensure_ascii=False, indent=2)
    print()
    print(f"✓ {len(stations)} emisoras", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
