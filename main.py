# main.py
from __future__ import annotations
# main.py

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from config.settings import settings
from interface_adapters.controllers.extract_controller import ExtractController
from infrastructure.files.pdf_utils import pdf_to_png_pages


def _setup_logging() -> None:
    lvl = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTS = {".pdf"}


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for ext in list(IMG_EXTS | PDF_EXTS):
        yield from root.rglob(f"*{ext}")


def _to_images(fp: Path, work_dir: Path) -> List[Path]:
    """
    Devuelve una lista de rutas de imagen a procesar.
    - Si fp es imagen -> [fp]
    - Si fp es PDF -> páginas convertidas a PNG en work_dir
    """
    if fp.suffix.lower() in IMG_EXTS:
        return [fp]
    if fp.suffix.lower() in PDF_EXTS:
        pdf_out_dir = work_dir / "pdf_pages"
        return pdf_to_png_pages(fp, pdf_out_dir)
    return []


def main(argv: list[str] | None = None) -> int:
    _setup_logging()

    parser = argparse.ArgumentParser(description="Extractor de albaranes/facturas con Gemini 2.5 Pro (carpeta o fichero)")
    parser.add_argument(
        "path",
        nargs="?",
        default="input",  # <= por defecto subcarpeta input
        help="Ruta a carpeta o fichero (.pdf/.jpg/.jpeg/.png/.webp). Por defecto: ./input",
    )
    parser.add_argument("--print", dest="print_json", action="store_true", help="Imprime el JSON combinado por documento")
    args = parser.parse_args(argv)

    target = Path(args.path).resolve()
    if not target.exists():
        print(f"Ruta no encontrada: {target}")
        return 2

    ctrl = ExtractController(logging.getLogger("extract"))
    # agregados de toda la ejecución
    all_cabeceras: list[dict] = []
    all_lineas: list[dict] = []

    work_dir = Path(settings.output_dir, ".work")
    work_dir.mkdir(parents=True, exist_ok=True)

    count_docs = 0

    for fp in _iter_files(target):
        images = _to_images(fp, work_dir)
        if not images:
            logging.getLogger("main").warning("Archivo ignorado (ext no soportada): %s", fp.name)
            continue

        for img in images:
            try:
                result = ctrl.extract_from_image(img.as_posix())
                # acumular por lote
                all_cabeceras.extend(result.get("output_json", {}).get("cabecera", []))
                all_lineas.extend(result.get("output_json", {}).get("lineas", []))
                count_docs += 1
                if args.print_json:
                    print(json.dumps(result["output_json"], ensure_ascii=False, indent=2))
            except Exception as e:
                logging.getLogger("main").exception("Error procesando %s: %s", img.name, e)

    # Escribir salida agregada en 2 JSON (para Postgres/Excel)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cabecera_batch = out_dir / f"cabecera_batch_{ts}.json"
    lineas_batch = out_dir / f"lineas_batch_{ts}.json"
    cabecera_batch.write_text(json.dumps(all_cabeceras, ensure_ascii=False, indent=2), encoding="utf-8")
    lineas_batch.write_text(json.dumps(all_lineas, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Procesados documentos/imágenes: {count_docs}")
    print(f"Cabeceras lote → {cabecera_batch}")
    print(f"Líneas lote    → {lineas_batch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
