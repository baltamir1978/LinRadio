"""Los servicios de LinRadio sin red: letras, títulos, carátulas, historial, cuñas y lo
aprendido de cada emisora. Los casos vienen de lo que pasó con las emisoras de verdad en
MacRadio (ver su REVISION.md)."""

import json
from pathlib import Path

import pytest

from linradio import catalog, lyrics, titles
from linradio.catalog import Lookup, Station, StationList
from linradio.history import MAX_ENTRIES, History
from linradio.intro import MINIMUM_INTRO, IcyReframer, StreamIntro, intro_length
from linradio.memory import StationMemory
from linradio.titles import SongClock, StreamTitle


@pytest.fixture(autouse=True)
def xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))


# --- Letras --------------------------------------------------------------------------------


def test_lrc_con_varias_marcas_y_etiquetas() -> None:
    text = "[ar:Alguien]\n[offset:+500]\n[00:12.50]Primera\n[00:20.00][01:20.00]Estribillo\n" \
           "[00:15.00] Segunda \n"
    lines = lyrics.parse_lrc(text)
    assert [(l.time, l.text) for l in lines] == [
        (12.5, "Primera"), (15.0, "Segunda"), (20.0, "Estribillo"), (80.0, "Estribillo")]


def test_linea_que_suena() -> None:
    song = lyrics.SongLyrics(synced=lyrics.parse_lrc("[00:10.00]a\n[00:20.00]b\n[00:30.00]c"))
    assert song.line_index(5) is None
    assert song.line_index(10) == 0
    assert song.line_index(25) == 1
    assert song.line_index(99) == 2


def test_nombres_de_artistas() -> None:
    assert lyrics.artist_names("El Canto del Loco y Amaia Montero") == \
        ["El Canto del Loco", "Amaia Montero"]
    assert lyrics.artist_names("A & B feat. C") == ["A", "B", "C"]
    assert lyrics.artist_names("Daddy Yankee x Bad Bunny") == ["Daddy Yankee", "Bad Bunny"]
    # «y» sólo como palabra: no parte «Yuri» ni «Rey».
    assert lyrics.artist_names("Rey Ruiz") == ["Rey Ruiz"]


def test_quitar_adornos() -> None:
    # Como en MacRadio, deja el espacio de antes del paréntesis: quien la llama recorta.
    assert lyrics.strip_decorations("Miedo (Directo)").strip() == "Miedo"
    assert lyrics.strip_decorations("Canción [Remastered 2011]").strip() == "Canción"
    assert lyrics.strip_decorations("Algo feat. Otro") == "Algo"
    # Un paréntesis al principio no deja el título vacío.
    assert lyrics.strip_decorations("(I Can't Get No) Satisfaction") == "(I Can't Get No) Satisfaction"


HITS = [
    {"trackName": "Puede Ser", "artistName": "Otra Persona", "duration": 200,
     "syncedLyrics": "[00:01.00]no es esta"},
    {"trackName": "Puede ser (Remix)", "artistName": "El Canto del Loco", "duration": 30,
     "syncedLyrics": "[00:01.00]demasiado corta: basura"},
    {"trackName": "Puede ser", "artistName": "El Canto del Loco, Amaia Montero", "duration": 214,
     "plainLyrics": "sin tiempos"},
    {"trackName": "Puede ser", "artistName": "El Canto del Loco & Amaia Montero", "duration": 214,
     "syncedLyrics": "[00:10.00]Puede ser\n[00:15.00]que no"},
]


def test_elegir_la_letra_buena() -> None:
    outcome = lyrics.from_hits(HITS, "Puede ser", ["El Canto del Loco", "Amaia Montero"])
    assert outcome.status is lyrics.Status.FOUND and outcome.lyrics is not None
    assert [l.text for l in outcome.lyrics.synced] == ["Puede ser", "que no"]
    assert outcome.lyrics.duration == 214


def test_sin_artistas_vale_la_primera_sincronizada_que_case() -> None:
    outcome = lyrics.from_hits(HITS, "Puede ser", [])
    assert outcome.lyrics is not None
    assert outcome.lyrics.synced[0].text == "no es esta"


def test_instrumental_y_nada() -> None:
    inst = lyrics.from_hits([{"trackName": "Tema", "duration": 180, "instrumental": True}], "Tema", [])
    assert inst.lyrics is not None and inst.lyrics.instrumental
    assert lyrics.from_hits([{"trackName": "Otra", "duration": 180, "plainLyrics": "x"}],
                            "Tema", []).status is lyrics.Status.NOT_FOUND


def test_busquedas_de_repuesto(monkeypatch: pytest.MonkeyPatch) -> None:
    # Orden en que se pregunta: tal cual, al revés, por el artista principal, por el título.
    asked: list[tuple[str, str | None]] = []

    def fake(track: str, artist: str | None, by_any_of: list[str] | None = None) -> lyrics.Outcome:
        asked.append((track, artist))
        if artist is None:
            return lyrics.Outcome(lyrics.Status.FOUND, lyrics.SongLyrics(plain=["ok"]))
        return lyrics.Outcome(lyrics.Status.NOT_FOUND)

    monkeypatch.setattr(lyrics, "search", fake)
    found = lyrics.lookup("Puede ser", "El Canto del Loco y Amaia Montero")
    assert found.status is lyrics.Status.FOUND
    assert asked == [("Puede ser", "El Canto del Loco y Amaia Montero"),
                     ("El Canto del Loco y Amaia Montero", "Puede ser"),
                     ("Puede ser", "El Canto del Loco"), ("Puede ser", None)]


def test_un_fallo_de_red_no_es_un_no_hay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lyrics, "search",
                        lambda *a, **k: lyrics.Outcome(lyrics.Status.FAILED))
    # Con la red caída no se sigue probando variantes: se vuelve a preguntar más tarde.
    assert lyrics.lookup("x", "y").status is lyrics.Status.FAILED


# --- Títulos de la emisora ---------------------------------------------------------------


def test_artista_y_titulo() -> None:
    t = titles.parse("Fito & Fitipaldis - Soldadito marinero")
    assert t == StreamTitle("Soldadito marinero", "Fito & Fitipaldis")


def test_guion_sin_espacios_no_parte_m_clan() -> None:
    t = titles.parse("M-Clan - Carolina")
    assert t is not None and t.artist == "M-Clan" and t.track == "Carolina"


def test_titulo_sin_artista() -> None:
    assert titles.parse("Programa de la mañana") == StreamTitle("Programa de la mañana", None)


def test_codigos_y_eslogan_no_son_canciones() -> None:
    assert titles.parse("1234567") is None                         # Los 40 Classic
    assert titles.parse("La Mejor Variedad Musical - CADENA 100", "Cadena 100") is None
    assert titles.parse("KISS FM", "Kiss FM") is None


def test_latin1_mal_leido() -> None:
    mangled = "El Último".encode("cp1252").decode("cp1256")
    assert mangled != "El Último"
    assert titles.repair_latin1(mangled) == "El Último"
    assert titles.repair_latin1("Normal") == "Normal"


def test_misma_cancion() -> None:
    assert titles.same_song("Miedo (Directo)", "Miedo")
    assert not titles.same_song("Miedo", "Otra")
    assert not titles.same_song("", "Miedo")


def test_emisora_que_manda_titulo_y_artista_al_reves() -> None:
    # Cassette FM manda «Título - Artista»: lo que parece el título es el artista de iTunes.
    t = titles.parse("Soldadito marinero - Fito y Fitipaldis")
    assert t is not None
    assert titles.is_swapped(t, "Fito & Fitipaldis")
    assert not titles.is_swapped(StreamTitle("Soldadito marinero", "Fito & Fitipaldis"),
                                 "Fito & Fitipaldis")


def test_retraso_del_titulo() -> None:
    assert titles.learn_title_lag(None, 3.0) == 3.0
    assert titles.learn_title_lag(3.0, 5.0) == 4.0           # promediado
    assert titles.learn_title_lag(3.0, 90.0) is None         # inverosímil: no se aprende


def test_reloj_de_la_letra() -> None:
    clock = SongClock()
    clock.title_changed(heard_at=1000, title_lag=3, seen_title_before=False)
    assert clock.started_at == 997 and not clock.exact       # sintonizado a mitad
    clock.title_changed(heard_at=1200, title_lag=3, seen_title_before=True)
    assert clock.exact
    assert clock.elapsed(now=1197 + 10) == pytest.approx(10 + titles.LYRICS_LEAD)
    clock.nudge(20)
    assert clock.offset == titles.MAX_OFFSET                  # con tope
    clock.offset = 0
    # Pulsar la línea de los 30 s a los 1240: la emisora va ~10 s tarde.
    clock.sync_to_line(line_time=30, clicked_at=1240, reaction=0)
    assert clock.offset == pytest.approx(1197 - 1210 - titles.LYRICS_LEAD)


def test_pulsar_una_linea_sin_saber_el_principio() -> None:
    clock = SongClock()
    clock.sync_to_line(line_time=30, clicked_at=1240, reaction=0)
    assert clock.exact
    # La línea pulsada queda justo como la que suena (sin el adelanto de un segundo).
    assert clock.elapsed(now=1240) == pytest.approx(30)


def test_cuando_preguntar_si_el_titulo_se_ha_quedado() -> None:
    clock = SongClock(started_at=1000, exact=True)
    assert clock.stale_deadline(200) == 1000 + 200 + titles.STALE_GRACE
    assert clock.stale_deadline(None) == 1000 + titles.ASSUMED_SONG_LENGTH + titles.STALE_GRACE


# --- Emisoras y carátulas ----------------------------------------------------------------


def test_importar_las_de_macradio() -> None:
    exported = [{"id": "A", "name": "Kiss FM", "streamURL": catalog.DEFAULTS[3].streamURL},
                {"id": "B", "name": "Nueva", "streamURL": "https://nueva.test/radio.mp3",
                 "logoURL": "https://nueva.test/logo.png"},
                {"name": "Sin URL"}]
    stations = StationList()
    assert stations.import_from(exported) == 1               # la repetida no se duplica
    stations.save()
    again = StationList.load()
    assert [s.name for s in again.stations][-1] == "Nueva"
    assert again.stations[-1].logoURL == "https://nueva.test/logo.png"


def test_la_primera_importacion_sustituye_a_la_lista_de_partida() -> None:
    # En MacRadio se quitó SER Oriente: no puede volver al importar.
    exported = [{"name": s.name, "streamURL": s.streamURL} for s in catalog.DEFAULTS
                if s.name != "SER Oriente"]
    stations = StationList()
    assert stations.import_from(exported, replace=True) == len(exported)
    assert "SER Oriente" not in [s.name for s in stations.stations]


def test_lista_de_partida_si_no_hay_archivo() -> None:
    assert len(StationList.load().stations) == len(catalog.DEFAULTS)


def test_detalle_de_la_emisora() -> None:
    assert Station("X", "https://x", genre="pop", country="ES").detail == "Pop · ES"
    assert Station("X", "https://x").detail == ""


def test_caratula_de_itunes() -> None:
    status, art = catalog.artwork_from({"results": [{
        "artworkUrl100": "https://is1.mzstatic.com/x/100x100bb.jpg", "trackName": "Carolina",
        "artistName": "M-Clan", "trackViewUrl": "https://music.apple.com/x"}]})
    assert status is Lookup.FOUND and art is not None
    assert art.image_url.endswith("600x600bb.jpg")
    assert catalog.artwork_from({"results": []})[0] is Lookup.NOT_FOUND
    assert catalog.artwork_from("basura")[0] is Lookup.FAILED


# --- Historial -----------------------------------------------------------------------------


def test_apuntar_sin_repetir_la_ultima() -> None:
    h = History()
    first = h.record("Carolina", "M-Clan", "Cadena 100")
    assert h.record("Carolina", "M-Clan", "Cadena 100") == first     # una reconexión
    assert h.record("Otra", None, "Cadena 100") != first
    assert len(h.songs) == 2


def test_ignorar_y_purgar_respeta_favoritas() -> None:
    h = History()
    fav = h.record("La Mejor Variedad", None, "Cadena 100")
    assert fav is not None
    h.toggle_favorite(fav)
    h.record("Canción", None, "Cadena 100")
    h.record("LA MEJOR VARIEDAD", None, "Cadena 100")
    h.ignore_and_purge(h.songs[0])
    assert [s.title for s in h.songs] == ["Canción", "La Mejor Variedad"]   # la favorita queda
    assert h.record("la mejor variedad", None, "Cadena 100") is None         # ya no se apunta
    assert h.record("La Mejor Variedad", None, "Kiss FM") is not None        # en otra, sí


def test_vaciar_deja_las_favoritas() -> None:
    h = History()
    keep = h.record("Guardada", None, "R")
    assert keep is not None
    h.toggle_favorite(keep)
    h.record("Otra", None, "R")
    h.clear_non_favorites()
    assert [s.title for s in h.songs] == ["Guardada"]


def test_tope_sin_tocar_favoritas() -> None:
    h = History()
    old = h.record("La más vieja", None, "R")
    assert old is not None
    h.toggle_favorite(old)
    for i in range(MAX_ENTRIES + 5):
        h.record(f"c{i}", None, "R")
    assert len(h.songs) == MAX_ENTRIES
    assert h.songs[-1].title == "La más vieja"


def test_historial_ida_y_vuelta() -> None:
    h = History()
    h.record("Carolina", "M-Clan", "Cadena 100")
    h.ignore_and_purge(h.songs[0])
    h.record("Otra", None, "Kiss FM")
    h.save()
    again = History.load()
    assert [s.title for s in again.songs] == ["Otra"]
    assert again.is_ignored("Carolina", "Cadena 100")


# --- Cuñas de entrada -----------------------------------------------------------------------


def _mp3ish(seed: int, size: int) -> bytes:
    """Bytes que parecen tramas MP3: una palabra de sincronía cada 417 bytes."""
    import random
    rnd = random.Random(seed)
    out = bytearray()
    while len(out) < size:
        out += b"\xff\xfb" + bytes(rnd.getrandbits(8) for _ in range(415))
    return bytes(out[:size])


def test_medir_la_cuna() -> None:
    intro = _mp3ish(1, 100_000)
    a = intro + _mp3ish(2, 50_000)          # dos conexiones: la misma cuña, directo distinto
    b = intro + _mp3ish(3, 50_000)
    n = intro_length(a, b)
    assert abs(n - len(intro)) <= 8 and a[n] == 0xFF          # cortado en la sincronía


def test_sin_cuna() -> None:
    assert intro_length(_mp3ish(4, 100_000), _mp3ish(5, 100_000)) == 0
    # Coincidir hasta el final es una captura cortada, no una cuña.
    same = _mp3ish(6, 100_000)
    assert intro_length(same, same) == 0
    # Coincidir menos de 32 KB es la cabecera común, no una cuña.
    short = _mp3ish(7, MINIMUM_INTRO - 1000)
    assert intro_length(short + _mp3ish(8, 9000), short + _mp3ish(9, 9000)) == 0


def _icy(audio: bytes, metaint: int, titles_by_block: dict[int, bytes]) -> bytes:
    """Monta un stream ICY: un bloque de metadatos cada `metaint` bytes de audio."""
    out = bytearray()
    block = 0
    for i in range(0, len(audio), metaint):
        out += audio[i:i + metaint]
        if len(audio[i:i + metaint]) == metaint:
            meta = titles_by_block.get(block, b"")
            if meta:
                padded = meta + b"\x00" * (-len(meta) % 16)
                out += bytes([len(padded) // 16]) + padded
            else:
                out += b"\x00"
            block += 1
    return bytes(out)


def _deframe(stream: bytes, metaint: int) -> tuple[bytes, list[bytes]]:
    audio, metas = bytearray(), []
    i = 0
    while i < len(stream):
        audio += stream[i:i + metaint]
        i += metaint
        if i >= len(stream):
            break
        length = stream[i] * 16
        if length:
            metas.append(stream[i + 1:i + 1 + length].rstrip(b"\x00"))
        i += 1 + length
    return bytes(audio), metas


def test_quitar_la_cuna_conserva_los_titulos() -> None:
    metaint = 8192
    intro_audio = _mp3ish(10, 40_960)
    live = _mp3ish(11, 81_920)
    stream = _icy(intro_audio + live, metaint, {7: b"StreamTitle='M-Clan - Carolina';"})
    reframer = IcyReframer(metaint, StreamIntro(len(intro_audio), intro_audio[:8192], 0))
    out = b"".join(reframer.feed(stream[i:i + 1000]) for i in range(0, len(stream), 1000))
    assert reframer.skipped and not reframer.mismatch
    audio, metas = _deframe(out, metaint)
    assert audio == live[:len(audio)] and len(live) - len(audio) < metaint
    assert metas == [b"StreamTitle='M-Clan - Carolina';"]   # el título sobrevive al recorte


def test_si_la_cuna_ha_cambiado_pasa_todo_tal_cual() -> None:
    metaint = 8192
    audio = _mp3ish(12, 81_920)
    stream = _icy(audio, metaint, {})
    reframer = IcyReframer(metaint, StreamIntro(40_960, _mp3ish(13, 8192), 0))
    out = reframer.feed(stream)
    assert reframer.mismatch and not reframer.skipped
    assert _deframe(out, metaint)[0] == audio[:len(_deframe(out, metaint)[0])]


# --- Lo aprendido de cada emisora ----------------------------------------------------------


def test_memoria_de_la_emisora() -> None:
    url = "https://radio.test/stream.mp3"
    m = StationMemory()
    assert m.learn_title_lag(url, 3.0) and m.title_lag(url) == 3.0
    assert not m.learn_title_lag(url, 120)                    # no se aprende lo inverosímil
    m.set_lyrics_offset(url, 2.5)
    m.record_intro(url, StreamIntro(40_000, b"\xff\xfb\x00", 1000.0))
    m.save()
    again = StationMemory.load()
    assert again.title_lag(url) == 3.0
    assert again.lyrics_offset(url) == 2.5
    intro = again.intro(url)
    assert intro is not None and intro.prefix == b"\xff\xfb\x00"
    again.set_lyrics_offset(url, 0)                            # ↺ a cero: se olvida
    assert "lyrics_offset" not in again.data[url]


def test_cada_cuanto_se_vuelve_a_medir_la_cuna() -> None:
    url = "https://radio.test/s.mp3"
    m = StationMemory()
    assert m.needs_learning_intro(url)
    m.record_intro(url, StreamIntro(40_000, b"x", 1000.0))
    assert not m.needs_learning_intro(url, now=1000 + 1800)
    assert m.needs_learning_intro(url, now=1000 + 3601)        # con cuña: cada hora
    m.record_intro(url, StreamIntro(0, b"", 1000.0))
    assert not m.needs_learning_intro(url, now=1000 + 2 * 86400)
    assert m.needs_learning_intro(url, now=1000 + 4 * 86400)   # sin cuña: cada 3 días


def test_una_conexion_distinta_no_borra_la_cuna() -> None:
    url = "https://radio.test/s.mp3"
    m = StationMemory()
    m.record_intro(url, StreamIntro(40_000, b"x", 1000.0))
    m.mark_intro_stale(url)
    m.save()
    again = StationMemory.load()
    intro = again.intro(url)
    assert intro is not None and intro.length == 40_000 and intro.prefix == b"x"
    assert again.needs_learning_intro(url, now=1000 + 1)       # se mide otra vez ya
    m.mark_intro_stale("https://radio.test/otra.mp3")          # sin cuña recordada, nada
    assert m.intro("https://radio.test/otra.mp3") is None


def test_el_formato_de_las_emisoras_es_el_de_macradio() -> None:
    # Las claves que escribe MacRadio (Codable de su `Station`).
    stations = StationList([Station("Kiss FM", "https://k.test", genre="Dance")])
    stations.save()
    saved = json.loads(StationList.file().read_text())
    assert set(saved[0]) >= {"id", "name", "streamURL", "logoURL", "country", "genre",
                             "stationuuid"}
