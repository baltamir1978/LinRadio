"""Modo consola: probar los servicios de LinRadio sin reproductor.

La reproducción (GStreamer), Shazam (songrec), MPRIS y la bandeja necesitan Debian; esto
recorre todo lo demás con los servicios de verdad.
"""

import json
import sys
from pathlib import Path

from . import __version__, catalog, intro, lyrics, titles
from .catalog import Station, StationList
from .history import History
from .memory import StationMemory
from .net import NetworkError

USAGE = """\
LinRadio — radio por internet con letra sincronizada

Uso:
  linradio --emisoras                     tus emisoras
  linradio --buscar <nombre> [--pais ES]  buscar en Radio Browser
  linradio --anadir <nombre> <url>        añadir una emisora a mano
  linradio --importar <archivo.json>      añadir las exportadas de MacRadio
  linradio --titulo "<ICY>" [--emisora <nombre>]   cómo se entiende un título de la emisora
  linradio --letra "<artista> - <título>"          buscar la letra en LRCLIB
  linradio --caratula "<artista> - <título>"       buscar la carátula en iTunes
  linradio --cuna <nombre o url>          medir la cuña de entrada de una emisora (unos 35 s)
  linradio --historial
  linradio --version

Sin argumentos se abrirá la ventana (todavía no existe).
"""


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _option(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    try:
        match command:
            case "--version":
                print(f"LinRadio {__version__}")
                return 0
            case "--emisoras":
                return run_stations()
            case "--buscar":
                return run_search(rest)
            case "--anadir":
                return run_add(rest)
            case "--importar":
                return run_import(rest)
            case "--titulo":
                return run_title(rest)
            case "--letra":
                return run_lyrics(" ".join(rest))
            case "--caratula":
                return run_artwork(" ".join(rest))
            case "--cuna":
                return run_intro(" ".join(rest))
            case "--historial":
                return run_history()
    except NetworkError as error:
        _err(f"✗ Fallo de red: {error}")
        return 1
    _err(f"Opción desconocida: {command}")
    return 2


def run_stations() -> int:
    stations = StationList.load()
    for n, s in enumerate(stations.stations, start=1):
        print(f"{n:2d}. {s.name}{'  · ' + s.detail if s.detail else ''}\n    {s.streamURL}")
    if not StationList.file().exists():
        print("\n(Es la lista de partida; se guarda al añadir o importar.)")
    return 0


def run_search(argv: list[str]) -> int:
    country = _option(argv, "--pais")
    words = [a for i, a in enumerate(argv) if a != "--pais" and (i == 0 or argv[i - 1] != "--pais")]
    name = " ".join(words)
    if not name:
        _err("Falta el nombre que buscar.")
        return 2
    found = catalog.search_stations(name, country)
    print(f"▸ {len(found)} emisoras para «{name}»\n")
    for n, s in enumerate(found, start=1):
        print(f"{n:2d}. {s.name}{'  · ' + s.detail if s.detail else ''}\n    {s.streamURL}")
    return 0 if found else 1


def run_add(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[-1].startswith(("http://", "https://")):
        _err("Uso: --anadir <nombre> <url>")
        return 2
    stations = StationList.load()
    if not stations.add(Station(name=" ".join(argv[:-1]), streamURL=argv[-1])):
        print("Ya estaba.")
        return 0
    stations.save()
    print(f"✓ Añadida. Ahora hay {len(stations.stations)}.")
    return 0


def run_import(argv: list[str]) -> int:
    if not argv:
        _err("Uso: --importar <archivo.json>")
        return 2
    try:
        data = json.loads(Path(argv[0]).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _err(f"✗ No se puede leer: {error}")
        return 1
    first_time = not StationList.file().exists()
    stations = StationList.load()
    added = stations.import_from(data, replace=first_time)
    stations.save()
    print(f"✓ {added} nuevas; {len(stations.stations)} en total.")
    return 0


def _split_song(text: str) -> tuple[str, str | None]:
    parsed = titles.parse(text)
    if parsed is None:
        return text.strip(), None
    return parsed.track, parsed.artist


def run_title(argv: list[str]) -> int:
    station = _option(argv, "--emisora") or ""
    raw = " ".join(a for i, a in enumerate(argv)
                   if a != "--emisora" and (i == 0 or argv[i - 1] != "--emisora"))
    parsed = titles.parse(raw, station)
    if parsed is None:
        print("No es una canción (un código, o la emisora anunciándose).")
        return 1
    print(f"artista: {parsed.artist or '—'}\ntítulo:  {parsed.track}\nclave:   {parsed.key}")
    return 0


def run_lyrics(text: str) -> int:
    track, artist = _split_song(text)
    outcome = lyrics.lookup(track, artist)
    if outcome.status is not lyrics.Status.FOUND or outcome.lyrics is None:
        print(f"✗ {outcome.status.value}")
        return 1
    found = outcome.lyrics
    if found.instrumental:
        print("♪ Instrumental")
        return 0
    kind = "sincronizada" if found.synced else "sin tiempos"
    length = f", {found.duration:.0f} s" if found.duration else ""
    print(f"▸ Letra {kind}{length}\n")
    if found.synced:
        for line in found.synced:
            minutes, seconds = divmod(line.time, 60)
            print(f"  [{int(minutes):02d}:{seconds:05.2f}] {line.text}")
    else:
        for text in found.plain:
            print(f"  {text}")
    return 0


def run_artwork(text: str) -> int:
    track, artist = _split_song(text)
    status, art = catalog.find_artwork(track, artist)
    if art is None:
        print(f"✗ {status.value}")
        return 1
    print(f"{art.image_url}\n  iTunes la llama «{art.track}» de {art.artist}")
    if titles.is_swapped(titles.StreamTitle(track, artist), art.artist):
        print("  ⚠︎ la emisora manda título y artista al revés")
    return 0


def run_intro(target: str) -> int:
    stations = StationList.load()
    station = next((s for s in stations.stations if s.name.lower() == target.lower()), None)
    url = station.streamURL if station else target
    if not url.startswith(("http://", "https://")):
        _err("Uso: --cuna <nombre de una de tus emisoras, o url>")
        return 2
    print(f"Midiendo {station.name if station else url} con dos conexiones (unos 35 s)…")
    found = intro.learn(url)
    if found is None:
        print("✗ No se pudo medir (la emisora no contestó).")
        return 1
    memory = StationMemory.load()
    memory.record_intro(url, found)
    memory.save()
    print(f"✓ Cuña de {found.length:,} bytes".replace(",", ".") if found.length
          else "✓ Esta emisora no tiene cuña")
    return 0


def run_history() -> int:
    history = History.load()
    if not history.songs:
        print("Todavía no hay canciones.")
        return 0
    for song in history.songs[:30]:
        heart = "♥" if song.favorite else " "
        print(f"{heart} {song.listened_at.replace('T', ' ')}  {song.artist or '?'} — {song.title}"
              f"  ({song.station_name})")
    return 0
