#!/usr/bin/env bash
# Monta el paquete .deb de LinRadio en build/.
#
#   Tools/build-deb.sh            → build/linradio_<versión>+<AAMMDDHHMM>_<arq>.deb
#   Tools/build-deb.sh --check    → además, comprueba el paquete por dentro
#
# Si hay un songrec compilado en build/songrec (Tools/build-songrec.sh), va dentro del
# paquete en /usr/lib/linradio/songrec y el paquete pasa a ser de la arquitectura de la
# máquina (amd64). Sin él es `all` y Shazam usa el songrec que encuentre en el sistema.
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' linradio/__init__.py)
[ -n "$VERSION" ] || { echo "✗ No encuentro __version__ en linradio/__init__.py"; exit 1; }
BUILD=$(date +%y%m%d%H%M)
FULL="$VERSION+$BUILD"
ARCH=all
[ -x build/songrec ] && ARCH=$(dpkg --print-architecture)
NAME="linradio_${FULL}_${ARCH}"
ROOT="build/$NAME"
APP_ID="io.github.baltamir1978.LinRadio"

rm -rf "$ROOT" "build/$NAME.deb"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/linradio/linradio/ui" \
         "$ROOT/usr/share/doc/linradio"

for f in linradio/*.py; do install -m 644 "$f" "$ROOT/usr/lib/linradio/linradio/"; done
for f in linradio/ui/*.py; do install -m 644 "$f" "$ROOT/usr/lib/linradio/linradio/ui/"; done
if [ "$ARCH" != all ]; then
    install -m 755 build/songrec "$ROOT/usr/lib/linradio/songrec"
fi

cat > "$ROOT/usr/bin/linradio" <<'X'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/lib/linradio")
from linradio.__main__ import main
sys.exit(main())
X
chmod 755 "$ROOT/usr/bin/linradio"

install -D -m 644 "data/$APP_ID.desktop" "$ROOT/usr/share/applications/$APP_ID.desktop"
install -D -m 644 "data/$APP_ID.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -D -m 644 "data/$APP_ID.metainfo.xml" "$ROOT/usr/share/metainfo/$APP_ID.metainfo.xml"

cat > "$ROOT/usr/share/doc/linradio/copyright" <<'X'
LinRadio
Copyright 2026 Bruno Altamirano
Código: https://github.com/baltamir1978/LinRadio

Letras: LRCLIB (lrclib.net). Carátulas: iTunes Search. Emisoras: Radio Browser.
Reconocimiento de canciones: songrec (GPL-3.0, https://github.com/marin-m/SongRec),
cliente no oficial de Shazam; si va dentro del paquete, en /usr/lib/linradio/songrec.
X
chmod 644 "$ROOT/usr/share/doc/linradio/copyright"

cat > "$ROOT/DEBIAN/postinst" <<'X'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    python3 -m compileall -q /usr/lib/linradio >/dev/null 2>&1 || true
fi
X
cat > "$ROOT/DEBIAN/prerm" <<'X'
#!/bin/sh
set -e
find /usr/lib/linradio -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
X
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"

SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<X
Package: linradio
Version: $FULL
Section: sound
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5),
 gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-base,
 gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-libav
Installed-Size: $SIZE
Maintainer: Bruno Altamirano <baltamir1978@users.noreply.github.com>
Homepage: https://github.com/baltamir1978/LinRadio
Description: radio por internet con letra sincronizada
 Tus emisoras con carátula, letra sincronizada de LRCLIB, historial con
 favoritas, búsqueda en Radio Browser, salto de la cuña de entrada,
 reconocimiento de canciones (songrec) y controles en GNOME por MPRIS.
X

find "$ROOT" -type d -exec chmod 755 {} +
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "build/$NAME.deb" >/dev/null
rm -rf "$ROOT"
echo "✓ build/$NAME.deb"

if [ "${1:-}" = "--check" ]; then
    dpkg-deb --info "build/$NAME.deb" | sed -n '/Package:/,$p'
    if dpkg-deb --contents "build/$NAME.deb" | grep -E '__pycache__|\.pyc$'; then
        echo "✗ El paquete lleva ficheros que no debería"; exit 1
    fi
    TMP=$(mktemp -d)
    dpkg-deb -x "build/$NAME.deb" "$TMP"
    PYTHONPATH="$TMP/usr/lib/linradio" python3 -m linradio --version
    PYTHONPATH="$TMP/usr/lib/linradio" python3 -c "import linradio.ui.app" && echo "✓ La ventana carga"
    rm -rf "$TMP"
    echo "✓ El paquete arranca"
fi
