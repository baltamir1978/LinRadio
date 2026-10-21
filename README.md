# LinRadio

Radio por internet con carátula, **letra
sincronizada**, historial con favoritas y reconocimiento de canciones.

Versión para Linux de [MacRadio](https://github.com/baltamir1978/MacRadio), la app de macOS. No
es un port: se escribe desde cero en Python, con la app original como especificación.

**Estado (21-oct-2026): los servicios funcionan; falta el reproductor.** Letras (LRCLIB),
carátulas (iTunes), búsqueda de emisoras (Radio Browser), historial y el salto de la cuña de
entrada están hechos y probados. La reproducción con GStreamer, Shazam, los controles del
sistema y la ventana llegarán cuando haya un Debian donde probarlos.

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
