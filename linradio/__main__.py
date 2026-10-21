"""Punto de entrada: con argumentos, consola; sin ellos, la ventana (todavía no existe)."""

import sys


def main() -> int:
    args = sys.argv[1:]
    if args:
        from . import cli
        return cli.main(args)
    print("La ventana de LinRadio todavía no existe; de momento, sólo el modo consola.\n"
          "Prueba: linradio --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
