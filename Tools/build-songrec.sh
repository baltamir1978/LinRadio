#!/usr/bin/env bash
# Compila songrec (cliente no oficial de Shazam) sólo en modo consola y lo deja en
# build/songrec, de donde lo coge Tools/build-deb.sh. No está en Debian 13.
#
# Necesita (una vez): sudo apt install pkg-config libasound2-dev libssl-dev libglib2.0-dev \
#   libpipewire-0.3-dev libclang-dev clang libsoup-3.0-dev
# y un Rust reciente: el cargo de Debian 13 (rustc 1.85) es demasiado viejo para songrec y
# sus dependencias. Se usa el de rustup si está (~/.cargo/bin), instalado sin tocar el PATH:
#   curl https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path
# Tarda unos minutos la primera vez.
set -euo pipefail
cd "$(dirname "$0")/.."
CARGO=cargo
[ -x "$HOME/.cargo/bin/cargo" ] && CARGO="$HOME/.cargo/bin/cargo"
command -v "$CARGO" >/dev/null || { echo "✗ Falta cargo (ver arriba)"; exit 1; }
mkdir -p build
"$CARGO" install songrec --locked --no-default-features --root build/songrec-root
install -m 755 build/songrec-root/bin/songrec build/songrec
build/songrec --version
echo "✓ build/songrec listo. Vuelve a montar el paquete: Tools/build-deb.sh"
