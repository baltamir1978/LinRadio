#!/usr/bin/env bash
# Compila songrec (cliente no oficial de Shazam) sólo en modo consola y lo deja en
# build/songrec, de donde lo coge Tools/build-deb.sh. No está en Debian 13.
#
# Necesita (una vez): sudo apt install cargo pkg-config libasound2-dev libssl-dev
# Tarda unos minutos la primera vez.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v cargo >/dev/null || {
    echo "✗ Falta cargo: sudo apt install cargo pkg-config libasound2-dev libssl-dev"; exit 1; }
mkdir -p build
cargo install songrec --locked --no-default-features --root build/songrec-root
install -m 755 build/songrec-root/bin/songrec build/songrec
build/songrec --version
echo "✓ build/songrec listo. Vuelve a montar el paquete: Tools/build-deb.sh"
