# LinRadio — contexto del repositorio

Versión para Linux de **MacRadio** (macOS), escrita **desde cero en Python**, no portada. Lo común
a las apps de Linux (pila, `.deb`, dónde se prueba, la bandeja) está en el `CLAUDE.md` de la
carpeta de proyectos; aquí va lo propio de esta.

## Estado (21-oct-2026)

**Sin empezar.** Conviene hacerla a la vez que RadioDroid (Android), porque comparten el diseño
del motor, aunque no el código.

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
