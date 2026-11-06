"""Punto de entrada. Sin argumentos, o con una orden para la radio (`--play`, `--toggle`,
`--next`…), la ventana; si ya está abierta, la orden le llega a esa instancia. Con
cualquier otro argumento, el modo consola."""

import sys

WINDOW_COMMANDS = ("--gui", "--play", "--toggle", "--stop", "--next", "--previous",
                   "--identify", "--favorite")


def wants_window(args: list[str]) -> bool:
    return not args or args[0] in WINDOW_COMMANDS


def main() -> int:
    args = sys.argv[1:]
    if not wants_window(args):
        from . import cli
        return cli.main(args)
    try:
        from .ui.app import run
    except (ImportError, ValueError) as error:
        print(f"No se puede abrir la ventana: {error}\n"
              "Faltan GTK 4, libadwaita o GStreamer (sudo apt install python3-gi "
              "gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0).\n"
              "El modo consola sigue disponible: linradio --help", file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
