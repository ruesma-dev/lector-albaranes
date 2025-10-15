# main.py
from __future__ import annotations
# main.py

import argparse
import logging

from config.settings import settings
from application.services.batch_runner import run_batch


def _setup_logging() -> None:
    lvl = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    logger = logging.getLogger("main")

    parser = argparse.ArgumentParser(description="Extractor de albaranes/facturas con Gemini 2.5 Pro (carpeta o fichero)")
    parser.add_argument(
        "path",
        nargs="?",
        default="input",
        help="Ruta a carpeta o fichero (.pdf/.jpg/.jpeg/.png/.webp). Por defecto: ./input",
    )
    parser.add_argument("--print", dest="print_json", action="store_true", help="Imprime JSON por documento en el log")
    args = parser.parse_args(argv)

    result = run_batch(args.path, args.print_json, logging.getLogger("extract"))

    print(f"Procesados: {result['count']}")
    print(f"Cabeceras lote → {result['cabecera_batch_path']}")
    print(f"Líneas lote    → {result['lineas_batch_path']}")
    print(f"Excel lote     → {result['excel_batch_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
