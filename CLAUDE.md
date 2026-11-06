# LinRadio — contexto del repositorio

Versión para Linux de **MacRadio** (macOS), escrita **desde cero en Python**, no portada. Lo común
a las apps de Linux (pila, `.deb`, dónde se prueba, la bandeja) está en el `CLAUDE.md` de la
carpeta de proyectos; aquí va lo propio de esta.

## Estado (6-nov-2026)

**Ya en Debian 13 (Acer de Bruno), con reproductor y ventana** (0.2.0, 51 pruebas):
- `player.py`: `playbin3` con reconexión (1, 2, 4, 8, 15, 30 s). Los títulos ICY se leen como
  eventos TAG en el `audio-filter`, después del búfer, así que llegan cuando su audio va a
  sonar (`SINK_LATENCY` = 0,2 s). En el mismo filtro, un `tee` deja el audio a 16 kHz mono
  en `recognizer.PcmRing` para Shazam, sin segunda conexión y ya sin la ráfaga inicial.
  Probado con Cadena 100 y La Indie (títulos y anillo lleno al ritmo real).
- `proxy.py`: proxy local con `IcyReframer` sólo para las emisoras con cuña medida. Probado:
  La Indie, cuña de 320.991 bytes medida en Debian y saltada conservando el `icy-metaint`.
- `session.py`: lo que suena (sin GTK, con pruebas): historial, carátula con corrección de
  «Título - Artista», letra, reloj, y las cinco razones para preguntar a Shazam (emisora
  muda, sintonizar a mitad, medir `title_lag`, título quedado, botón).
- `recognizer.py`: songrec con un WAV de 12 s. **Probado con Cadena 100**: reconoce la misma
  canción que anuncia la emisora, con su posición, en 0,4 s. **songrec no está en Debian 13**:
  se compila con `Tools/build-songrec.sh` y va dentro del `.deb` (`/usr/lib/linradio/songrec`),
  que pasa a ser `amd64`. songrec 0.8.1 pide **rustc ≥ 1.92** y Debian 13 trae la 1.85 (ni la
  0.6.7 compila: sus dependencias piden 1.88): se usa Rust de rustup en `~/.cargo`, instalado
  con `--no-modify-path`. Paquetes de desarrollo que pide: ver la cabecera del script.
- `mpris.py`: `org.mpris.MediaPlayer2.linradio`. Probado con `gdbus`: estado, metadatos con
  carátula, PlayPause, Quit.
- Ventana (`linradio/ui/`): emisoras a la izquierda (logo, subir/bajar, renombrar, quitar;
  buscar en Radio Browser, añadir a mano, importar el JSON de MacRadio), «Ahora» (carátula,
  controles, favorita, Shazam, volumen, letra con − / + / ↺ y clic en la línea) e
  «Historial» (búsqueda, sólo favoritas, borrar, borrar para siempre, títulos ignorados,
  vaciar dejando las favoritas). Atajos: espacio, Ctrl+P, Ctrl+←/→, Ctrl+I, Ctrl+D,
  Ctrl+Alt+←/→.
- Una sola instancia: `linradio --play <emisora>`, `--toggle`, `--stop`, `--next`,
  `--previous`, `--identify`, `--favorite` llegan a la abierta (probado).
- Al cerrar la ventana sigue sonando (opción del menú); los controles quedan en GNOME.
- Al despertar del reposo (`PrepareForSleep` de logind) se reconecta.

**No hecho, a propósito:**
- **Bandeja (StatusNotifierItem)**: GNOME no la muestra sin la extensión AppIndicator, que
  Bruno no tiene. MPRIS da los controles y la carátula en el menú del sistema.
- **gettext / cinco idiomas**: la interfaz está sólo en español.

**Sin probar todavía:** el sonido por altavoces (los del Acer no funcionan; todo se probó con
`LINRADIO_AUDIO_SINK=fakesink`).

## Cómo se prueba

La ventana necesita PyGObject (apt), que no está en el `.venv`: se arranca con el Python del
sistema, `python3 -m linradio`. **Sin sonar en los altavoces**: `LINRADIO_AUDIO_SINK=fakesink`.

```sh
.venv/bin/pytest && .venv/bin/mypy
XDG_DATA_HOME=… XDG_STATE_HOME=… .venv/bin/python -m linradio --letra "M-Clan - Carolina"
```

## Decisiones tomadas aquí (21-oct-2026)

- **Peticiones con 20 s de espera y dos reintentos si el servidor dice «ocupado»** (503/429, a
  los 2 y a los 4 s). LRCLIB se sobrecarga a ratos y al azar (la misma búsqueda da 503 y al
  momento 200) y alguna búsqueda tarda 14 s, más que los 12 de MacRadio. A MacRadio le pasa lo
  mismo y no lo trata: si Bruno ve letras que no salen a la primera, es esto.
- **La primera importación de emisoras sustituye a la lista de partida**: si no, volverían las
  que se quitaron en el Mac (SER Oriente). Las siguientes sólo añaden.
- **`Station` usa las claves de MacRadio** (`streamURL`, `logoURL`…), aunque no sea el estilo de
  Python, para leer su JSON tal cual.
- Un fallo de TLS con el servidor de Cadena 100 resultó ser **puntual del servidor**: al minuto
  entraba con el TLS por omisión. No hace falta rebajar la seguridad.
- **Riesgo conocido**: `urllib` no entiende la línea de estado `ICY 200 OK` de los servidores
  SHOUTcast viejos. Ninguna de las emisoras de Bruno la usa; con GStreamer no importa.

## La especificación es el original

`../MacRadio` (`github.com/baltamir1978/MacRadio`): leer su `README.md` y su `REVISION.md`. Qué
hace: emisoras propias y búsqueda en Radio Browser, carátula (iTunes Search o Shazam), **letra
sincronizada** de LRCLIB con ajuste por emisora (− / + / ↺, y clic en la línea que suena para
sincronizar), historial con favoritas, búsqueda y títulos ignorados (eslóganes de emisora), salto
de la cuña de entrada, minirreproductor en la barra, teclas multimedia, y cinco idiomas (es, en, fr,
de, pt).

## Cómo se hace en Linux

| En el Mac | Aquí |
|---|---|
| `AVPlayer` + proxy local + reconexión | **GStreamer `playbin3`**: los títulos de la emisora (ICY) llegan como mensajes `TAG`. El proxy seguramente sobra: comprobarlo con las emisoras que lo necesitaban |
| `MTAudioProcessingTap` / `StreamDecoder` para Shazam | Rama del audio a un `appsink` (`tee` dentro del `audio-filter` de `playbin3`), sin abrir una segunda conexión |
| ShazamKit | **songrec**, cliente no oficial de Shazam (Rust): se le pasa un trozo de 10–12 s en WAV. Puede romperse si Shazam cambia algo. Comprobar si está en Debian 13; si no, se compila y va dentro del `.deb`, que entonces deja de ser `all` |
| `MPNowPlayingInfoCenter`, teclas multimedia | **MPRIS** (`org.mpris.MediaPlayer2.linradio`) por D-Bus: GNOME pone los controles y la carátula y gestiona las teclas |
| `MenuBarExtra` con minirreproductor | Bandeja con StatusNotifierItem y menú (ver el `CLAUDE.md` común) |
| Widget de escritorio | **No hay en GNOME.** La letra va en la ventana; los controles, en MPRIS |
| `NSWorkspace.didWakeNotification` | Señal `PrepareForSleep` de logind por D-Bus |
| App Intents (Atajos) | Línea de órdenes que habla con la instancia abierta: `linradio --play <emisora>`, `--toggle`, `--next` (`Gio.Application` lo trae hecho) |
| `Localizable.strings` | gettext |

## Trampas que vienen del original (ver la memoria de MacRadio)

- **El retraso de la letra es de la emisora**, que cambia el título tarde. El título ICY llega al
  reproductor casi en su punto del audio. El retraso se aprende por emisora con Shazam
  (`title_lag`).
- **No guardar entre sesiones un «retraso de conexión»**: cambia con la cuña y el búfer y desfasa la
  letra (se probó y se quitó).
- **Algunas emisoras mandan «Título - Artista» al revés** (las de costafm y emisorasmusicales): se
  corrige con el artista que devuelve iTunes.
- **Títulos que se quedan**: si pasada la duración de la canción (de LRCLIB) más 20 s el título no
  cambia (300 s si no se sabe la duración), se pregunta a Shazam; si es otra canción, Shazam nombra
  las canciones hasta que la emisora cambie el título.
- **Al abrir una conexión, algunas emisoras mandan una ráfaga de audio atrasado** (Cadena 100: 5,2 s
  en medio segundo). No pasársela a Shazam, o la posición sale corrida.
- **LRCLIB no encuentra las colaboraciones** («El Canto del Loco y Amaia Montero»): buscar también
  por el artista principal y por título filtrando por artista.
- Con Shazam situando la canción, el ajuste manual de la letra vuelve a ±0 en cada canción nueva.
- **Las pruebas que hacen sonar la radio suenan en los altavoces de Bruno** y le cortan lo que esté
  escuchando: probar sin salida de audio (`fakesink`) o avisar antes.

## Las emisoras

Las de Bruno están en MacRadio. Hay que poder importarlas: decidir el formato (el JSON de MacRadio
o un M3U/PLS) cuando se empiece.
