"""Shazam (songrec): leer su respuesta y preparar la muestra, sin red."""

import wave
from pathlib import Path

from linradio.__main__ import wants_window
from linradio.recognizer import RATE, PcmRing, parse, write_wav

RESPONSE = {
    "matches": [{"id": "1", "offset": 61.2, "timeskew": 0.0}],
    "track": {"title": "Puede ser", "subtitle": "El Canto del Loco & Amaia Montero",
              "images": {"coverart": "https://img/400.jpg", "coverarthq": "https://img/hq.jpg"},
              "url": "https://www.shazam.com/track/1"},
}


def test_respuesta_reconocida() -> None:
    match = parse(RESPONSE, heard_at=100.0, sample_seconds=12.0)
    assert match is not None
    assert match.track == "Puede ser"
    assert match.artist == "El Canto del Loco & Amaia Montero"
    assert match.song_offset == 73.2          # el offset es el del principio de la muestra
    assert match.artwork_url == "https://img/hq.jpg"


def test_sin_resultado() -> None:
    assert parse({"matches": [], "track": None}, 0, 12) is None
    assert parse({"matches": []}, 0, 12) is None
    assert parse("basura", 0, 12) is None


def test_anillo_guarda_lo_ultimo(tmp_path: Path) -> None:
    ring = PcmRing(seconds=2)
    second = b"\x01\x00" * RATE
    for i in range(5):
        ring.push(second, at=float(i))
    assert ring.seconds() == 2.0
    pcm, at = ring.snapshot(1.5)
    assert len(pcm) == int(1.5 * RATE) * 2 and at == 4.0
    wav = tmp_path / "m.wav"
    write_wav(wav, pcm)
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2)
        assert w.getnframes() == int(1.5 * RATE)


def test_cuando_abrir_la_ventana() -> None:
    assert wants_window([])
    assert wants_window(["--play", "Cadena 100"])
    assert wants_window(["--toggle"])
    assert not wants_window(["--letra", "M-Clan - Carolina"])
