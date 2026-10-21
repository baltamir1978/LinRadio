"""Emisoras: las propias, la búsqueda en Radio Browser y la carátula en iTunes."""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from . import paths
from .net import NetworkError, get_json


@dataclass
class Station:
    """Mismas claves que la `Station` de MacRadio, para importar su lista tal cual."""

    name: str
    streamURL: str
    logoURL: str | None = None
    country: str | None = None
    genre: str | None = None
    stationuuid: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()).upper())

    @property
    def detail(self) -> str:
        """Género y país, para la segunda línea bajo el nombre."""
        return " · ".join(p for p in ((self.genre or "").capitalize(), self.country or "") if p)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Station | None":
        name, url = data.get("name"), data.get("streamURL")
        if not isinstance(name, str) or not isinstance(url, str) or not url:
            return None
        station = cls(name=name, streamURL=url)
        for key in ("logoURL", "country", "genre", "stationuuid"):
            if isinstance(data.get(key), str):
                setattr(station, key, data[key])
        if isinstance(data.get("id"), str):
            station.id = data["id"]
        return station


# La misma lista de partida que MacRadio y RadioApp.
DEFAULTS = [
    Station("Vive Segovia", "https://streaming.viveradio.es/vivesegovia",
            "https://viveradio.es/dist/images/favicons/apple-touch-icon.webp", "ES", "Regional"),
    Station("Cassette FM", "https://stream.costafm.es/listen/cassettefm_-_em/radio.mp3",
            "https://media.emisorasmusicales.net/wp-content/uploads/2021/05/11022133/Cassette.png",
            "ES", "Pop"),
    Station("Cadena 100", "https://cadena100-cope-rrcast.flumotion.com/cope/cadena100-low.mp3",
            "https://www.cadena100.es/estaticos/apple-touch-icon-192x192.png", "ES", "Pop"),
    Station("Kiss FM", "https://bbkissfm.kissfmradio.cires21.com/bbkissfm.mp3",
            "https://www.kissfm.es/wp-content/uploads/2024/10/Logo-KISS-FM_Negativo-Color.png",
            "ES", "Dance"),
    Station("La Indie", "https://stream.emisorasmusicales.net/listen/la_indie/laindie.mp3",
            "https://media.emisorasmusicales.net/wp-content/uploads/2020/04/11023707/LA-INDIE.png",
            "ES", "Indie"),
    Station("Los 40 Classic",
            "http://playerservices.streamtheworld.com/api/livestream-redirect/LOS40_CLASSIC.mp3",
            "https://los40es00.epimg.net/iconos/v1.x/v1.0/promos/promo_og_los40.png", "ES", "Pop"),
    Station("SER Oriente",
            "https://playerservices.streamtheworld.com/api/livestream-redirect/SER_ASO_ORIENTE.mp3",
            "https://cadenaser00.epimg.net/favicon.png", "ES", "Talk"),
    Station("COPE Madrid", "https://flucast09-h-cloud.flumotion.com/cope/madrid.mp3",
            "https://www.cope.es/estaticos/apple-touch-icon-192x192.png", "ES", "Talk"),
]


class StationList:
    """La lista de emisoras de Bruno, en ~/.local/share/linradio/emisoras.json."""

    def __init__(self, stations: list[Station] | None = None) -> None:
        self.stations = stations if stations is not None else [Station(**asdict(s))
                                                                for s in DEFAULTS]

    @staticmethod
    def file() -> Path:
        return paths.data_dir() / "emisoras.json"

    @classmethod
    def load(cls) -> "StationList":
        try:
            data = json.loads(cls.file().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            return cls()
        return cls.from_json(data)

    @classmethod
    def from_json(cls, data: Any) -> "StationList":
        if not isinstance(data, list):
            return cls()
        stations = [s for s in (Station.from_json(d) for d in data if isinstance(d, dict)) if s]
        return cls(stations or None)

    def save(self) -> None:
        paths.write_json(self.file(), [asdict(s) for s in self.stations])

    def contains(self, station: Station) -> bool:
        return any(s.streamURL == station.streamURL for s in self.stations)

    def add(self, station: Station) -> bool:
        if self.contains(station):
            return False
        self.stations.append(station)
        return True

    def import_from(self, data: Any, replace: bool = False) -> int:
        """Añade las de otra lista (la exportada de MacRadio) que no estén ya. Con `replace`
        —la primera importación, cuando aún no hay lista propia— la importada sustituye a la
        de partida: si no, volverían las que se quitaron en el Mac."""
        incoming = StationList.from_json(data).stations if isinstance(data, list) and data else []
        if replace and incoming:
            self.stations = []
        return sum(1 for s in incoming if self.add(s))


# --- Radio Browser --------------------------------------------------------------------------

RADIO_BROWSER = "https://de1.api.radio-browser.info/json"


def _to_station(raw: dict[str, Any]) -> Station | None:
    url, name = raw.get("url_resolved"), raw.get("name")
    if not isinstance(url, str) or not url or not isinstance(name, str):
        return None
    tags = raw.get("tags") if isinstance(raw.get("tags"), str) else ""
    favicon = raw.get("favicon") if isinstance(raw.get("favicon"), str) else ""
    return Station(name=name.strip(), streamURL=url, logoURL=favicon or None,
                   country=raw.get("countrycode") or None,
                   genre=(tags.split(",")[0].strip() or None) if tags else None,
                   stationuuid=raw.get("stationuuid"))


def search_stations(name: str, country: str | None = None, limit: int = 40) -> list[Station]:
    params = {"name": name, "limit": str(limit), "hidebroken": "true", "order": "votes",
              "reverse": "true"}
    if country:
        params["countrycode"] = country
    data = get_json(f"{RADIO_BROWSER}/stations/search", params)
    return [s for s in (_to_station(r) for r in data if isinstance(r, dict)) if s] \
        if isinstance(data, list) else []


def top_stations(country: str | None = None, limit: int = 50) -> list[Station]:
    params = {"limit": str(limit), "hidebroken": "true"}
    if country:
        params["countrycode"] = country
    data = get_json(f"{RADIO_BROWSER}/stations/topvote", params)
    return [s for s in (_to_station(r) for r in data if isinstance(r, dict)) if s] \
        if isinstance(data, list) else []


# --- Carátulas ---------------------------------------------------------------------------


class Lookup(Enum):
    FOUND = "encontrada"
    NOT_FOUND = "no hay"
    FAILED = "falló la red"


@dataclass(frozen=True)
class Artwork:
    image_url: str           # 600×600
    page_url: str | None     # la canción en Apple Music (de momento, sólo informativo)
    track: str | None        # cómo la llama iTunes: sirve para ver si la emisora va al revés
    artist: str | None


def find_artwork(track: str, artist: str | None) -> tuple[Lookup, Artwork | None]:
    """La emisora sólo manda el título; la carátula sale de iTunes Search (gratis, sin clave).
    iTunes corta las ráfagas con un 403: eso es «falló», no «no hay»."""
    term = " ".join(p for p in (artist, track) if p)
    if not term:
        return Lookup.NOT_FOUND, None
    try:
        data = get_json("https://itunes.apple.com/search",
                        {"term": term, "entity": "song", "limit": "1"})
    except NetworkError:
        return Lookup.FAILED, None
    return artwork_from(data)


def artwork_from(data: Any) -> tuple[Lookup, Artwork | None]:
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return Lookup.FAILED, None
    if not results or not isinstance(results[0], dict):
        return Lookup.NOT_FOUND, None
    hit = results[0]
    art = hit.get("artworkUrl100")
    if not isinstance(art, str):
        return Lookup.NOT_FOUND, None
    return Lookup.FOUND, Artwork(image_url=art.replace("100x100bb", "600x600bb"),
                                 page_url=hit.get("trackViewUrl"), track=hit.get("trackName"),
                                 artist=hit.get("artistName"))


def macradio_preferences() -> Path:
    """Dónde guarda MacRadio sus emisoras en el Mac (para exportarlas)."""
    return Path(os.path.expanduser(
        "~/Library/Containers/Altamirano.MacRadio/Data/Library/Preferences/"
        "Altamirano.MacRadio.plist"))
