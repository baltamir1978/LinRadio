# LinRadio

Radio por internet con carátula, **letra
sincronizada**, historial con favoritas y reconocimiento de canciones.

Versión para Linux de [MacRadio](https://github.com/baltamir1978/MacRadio), la app de macOS. No
es un port: se escribe desde cero en Python, con la app original como especificación.

**Estado (6-nov-2026): ventana GTK 4 + libadwaita y reproductor GStreamer.** Emisoras propias y
búsqueda en Radio Browser, carátula, letra sincronizada con ajuste por emisora, historial con
favoritas, salto de la cuña de entrada, Shazam (con songrec), controles en GNOME (MPRIS) y
órdenes desde la terminal para la radio abierta.

## Instalar en Debian

```sh
Tools/build-songrec.sh      # opcional: Shazam (Rust reciente de rustup; ver el propio script)
Tools/build-deb.sh          # genera build/linradio_<versión>_<arq>.deb
sudo apt install ./build/linradio_*.deb
```

## Órdenes para la radio abierta

```sh
linradio --play "Cadena 100"    # o sin nombre: la última
linradio --toggle | --stop | --next | --previous | --identify | --favorite
```

## Probarlo ya, por consola

```sh
python3 -m venv .venv && .venv/bin/pip install pytest mypy
.venv/bin/python -m linradio --letra "M-Clan - Carolina"
.venv/bin/python -m linradio --caratula "Fito y Fitipaldis - Soldadito marinero"
.venv/bin/python -m linradio --buscar "cadena 100" --pais ES
.venv/bin/python -m linradio --cuna "La Indie"      # mide la cuña de entrada (unos 35 s)
```

Las emisoras de MacRadio se traen así, en el Mac:

```sh
Tools/exportar-macradio.py > emisoras.json
linradio --importar emisoras.json
```

## Desarrollo

```sh
.venv/bin/pytest        # 37 pruebas, sin red
.venv/bin/mypy
```
