"""El cerebro de «lo que suena», con la red y Shazam de mentira y todo síncrono."""

from pathlib import Path

import pytest

from linradio import catalog
from linradio.catalog import Lookup, Station
from linradio.history import History
from linradio.lyrics import LyricLine, Outcome, SongLyrics, Status
from linradio.memory import StationMemory
from linradio.recognizer import Match
from linradio.session import NO_TITLE_GRACE, Probe, Session, Source

STATION = Station("Cadena 100", "https://example.com/c100.mp3")
SYNCED = SongLyrics(synced=[LyricLine(0.0, "uno"), LyricLine(10.0, "dos")], duration=200.0)


@pytest.fixture(autouse=True)
def xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


class Rig:
    def __init__(self, lyrics: Outcome | None = None,
                 artwork: tuple[Lookup, catalog.Artwork | None] = (Lookup.NOT_FOUND, None)
                 ) -> None:
        self.matches: list[Match | None] = []
        self.identified = 0
        self.changes = 0
        self.history = History()
        self.memory = StationMemory()
        self.session = Session(
            self.history, self.memory, on_change=lambda _n: self._count(),
            post=lambda f: f(), identify=self._identify,
            lyrics_lookup=lambda t, a: lyrics or Outcome(Status.NOT_FOUND),
            artwork_lookup=lambda t, a: artwork, spawn=lambda f: f())

    def _count(self) -> None:
        self.changes += 1

    def _identify(self) -> Match | None:
        self.identified += 1
        return self.matches.pop(0) if self.matches else None


def match(track: str, artist: str = "X", offset: float = 30.0, at: float = 1000.0) -> Match:
    return Match(track=track, artist=artist, song_offset=offset, heard_at=at,
                 artwork_url="https://img/a.jpg", page_url=None)


def test_titulo_nuevo_apunta_en_el_historial() -> None:
    rig = Rig()
    rig.session.tune(STATION, now=0)
    rig.session.on_title("M-Clan - Carolina", heard_at=5)
    now = rig.session.now
    assert now.title is not None and now.title.artist == "M-Clan"
    assert rig.history.songs[0].title == "Carolina"
    assert not now.clock.exact          # el primer título es de una canción ya empezada
    rig.session.on_title("Fito & Fitipaldis - Soldadito marinero", heard_at=100)
    assert rig.session.now.clock.exact  # éste se ha visto cambiar
    assert len(rig.history.songs) == 2
    rig.session.on_title("Fito & Fitipaldis - Soldadito marinero", heard_at=101)
    assert len(rig.history.songs) == 2  # repetido por una reconexión


def test_eslogan_no_es_cancion() -> None:
    rig = Rig()
    rig.session.tune(STATION, now=0)
    rig.session.on_title("La Mejor Variedad Musical - CADENA 100", heard_at=1)
    assert rig.session.now.title is None
    assert rig.history.songs == []


def test_emisora_al_reves_se_corrige_con_itunes() -> None:
    art = catalog.Artwork("https://img/600.jpg", None, "Soldadito marinero", "Fito y Fitipaldis")
    rig = Rig(artwork=(Lookup.FOUND, art))
    rig.session.tune(STATION, now=0)
    rig.session.on_title("Soldadito marinero - Fito & Fitipaldis", heard_at=1)
    title = rig.session.now.title
    assert title is not None and title.track == "Soldadito marinero"
    assert rig.history.songs[0].artist == "Fito & Fitipaldis"
    assert rig.history.songs[0].artwork_url == "https://img/600.jpg"


def test_emisora_muda_shazam_nombra() -> None:
    rig = Rig()
    rig.session.tune(STATION, now=0)
    rig.matches = [match("Canción A", at=25)]
    rig.session.tick(now=NO_TITLE_GRACE + 1)
    now = rig.session.now
    assert rig.identified == 1
    assert now.source is Source.SHAZAM and now.title and now.title.track == "Canción A"
    assert now.clock.exact and now.artwork_url == "https://img/a.jpg"
    assert rig.history.songs[0].title == "Canción A"


def test_sintonizar_a_mitad_shazam_situa_la_letra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linradio.session.time.time", lambda: 50.0)
    rig = Rig(lyrics=Outcome(Status.FOUND, SYNCED))
    rig.session.tune(STATION, now=0)
    rig.session.on_title("A - Canción", heard_at=2)
    assert Probe.POSITION in rig.session._probes
    rig.matches = [match("Canción", offset=40, at=60)]
    rig.session.tick(now=60)
    clock = rig.session.now.clock
    assert clock.exact and clock.started_at == 20
    assert len(rig.history.songs) == 1           # situar no toca el historial


def test_retraso_del_titulo_se_aprende(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linradio.session.time.time", lambda: 0.0)
    rig = Rig(lyrics=Outcome(Status.FOUND, SYNCED))
    rig.session.tune(STATION, now=0)
    rig.session.on_title("A - Primera", heard_at=1)
    rig.session.on_title("B - Segunda", heard_at=100)     # se ve cambiar: reloj exacto
    assert Probe.LAG in rig.session._probes
    # La canción empezó en 96: la emisora cambió el título 4 s tarde.
    rig.matches = [match("Segunda", offset=30, at=126)]
    rig.session.tick(now=130)
    assert rig.memory.title_lag(STATION.streamURL) == pytest.approx(4.0)
    assert rig.session.now.clock.started_at == 96


def test_titulo_quedado_pasa_a_shazam_y_vuelve() -> None:
    rig = Rig(lyrics=Outcome(Status.FOUND, SongLyrics(plain=["x"], duration=100.0)))
    rig.session.tune(STATION, now=0)
    rig.session.on_title("A - Vieja", heard_at=0)
    rig.session.on_title("B - Quedada", heard_at=10)
    rig.matches = [match("Otra distinta", at=200)]
    rig.session.tick(now=10 + 100 + 21)
    now = rig.session.now
    assert now.source is Source.SHAZAM and now.title and now.title.track == "Otra distinta"
    rig.session.on_title("B - Quedada", heard_at=210)        # el título viejo: se ignora
    assert rig.session.now.title.track == "Otra distinta"   # type: ignore[union-attr]
    rig.session.on_title("C - Nueva de verdad", heard_at=300)
    assert rig.session.now.source is Source.STATION
    assert rig.session.now.title.track == "Nueva de verdad"  # type: ignore[union-attr]


def test_shazam_sin_resultado_vuelve_al_logo() -> None:
    rig = Rig()
    rig.session.tune(STATION, now=0)
    rig.session.on_title("B - Quedada", heard_at=10)
    rig.matches = [None]
    rig.session.tick(now=10 + 300 + 21)
    assert rig.session.now.title is None
    assert rig.session._probes[Probe.STALE] > 0


def test_manual_avisa_si_no_reconoce() -> None:
    rig = Rig()
    rig.session.tune(STATION, now=0)
    rig.matches = [None]
    rig.session.identify_now()
    assert "no reconoce" in rig.session.now.message
    rig.matches = [match("Algo")]
    rig.session.identify_now()
    assert rig.session.now.title and rig.session.now.title.track == "Algo"
    assert not rig.session._naming      # sin título de la emisora no hay nada quedado


def test_favorita_y_ajuste_de_letra() -> None:
    rig = Rig(lyrics=Outcome(Status.FOUND, SYNCED))
    rig.session.tune(STATION, now=0)
    rig.session.on_title("A - Canción", heard_at=0)
    rig.session.toggle_favorite()
    assert rig.session.now.favorite and rig.history.songs[0].favorite
    rig.session.nudge_lyrics(0.5)
    rig.session.nudge_lyrics(0.5)
    assert rig.memory.lyrics_offset(STATION.streamURL) == 1.0
    rig.session.reset_lyrics_offset()
    assert rig.memory.lyrics_offset(STATION.streamURL) == 0.0
