# application/services/batch_runner.py
from __future__ import annotations
# application/services/batch_runner.py

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Dict, Any

from config.settings import settings
from infrastructure.files.pdf_utils import pdf_to_png_pages
from interface_adapters.controllers.extract_controller import ExtractController
from infrastructure.export.excel_writer import write_two_sheet_excel


IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTS = {".pdf"}


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for ext in list(IMG_EXTS | PDF_EXTS):
        yield from root.rglob(f"*{ext}")


def _to_images(fp: Path, work_dir: Path) -> List[Path]:
    if fp.suffix.lower() in IMG_EXTS:
        return [fp]
    if fp.suffix.lower() in PDF_EXTS:
        pdf_out_dir = work_dir / "pdf_pages"
        return pdf_to_png_pages(fp, pdf_out_dir)
    return []


def run_batch(path: str, print_json: bool, logger: logging.Logger) -> Dict[str, Any]:
    """
    Ejecuta el pipeline sobre una ruta (carpeta o fichero) y
    devuelve cabeceras y líneas acumuladas. Además genera JSON batch y Excel batch.
    """
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Ruta no encontrada: {target}")

    ctrl = ExtractController(logger)
    all_cabeceras: list[dict] = []
    all_lineas: list[dict] = []

    work_dir = Path(settings.output_dir, ".work")
    work_dir.mkdir(parents=True, exist_ok=True)

    count_docs = 0
    for fp in _iter_files(target):
        images = _to_images(fp, work_dir)
        if not images:
            logger.warning("Archivo ignorado (ext no soportada): %s", fp.name)
            continue

        for img in images:
            try:
                result = ctrl.extract_from_image(img.as_posix())
                all_cabeceras.extend(result.get("output_json", {}).get("cabecera", []))
                all_lineas.extend(result.get("output_json", {}).get("lineas", []))
                count_docs += 1
                if print_json:
                    logger.info("JSON %s:\n%s", img.name, json.dumps(result["output_json"], ensure_ascii=False, indent=2))
            except Exception as e:
                logger.exception("Error procesando %s: %s", img.name, e)

    # salida de lote (2 JSON + 1 Excel)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cabecera_batch = out_dir / f"cabecera_batch_{ts}.json"
    lineas_batch = out_dir / f"lineas_batch_{ts}.json"
    cabecera_batch.write_text(json.dumps(all_cabeceras, ensure_ascii=False, indent=2), encoding="utf-8")
    lineas_batch.write_text(json.dumps(all_lineas, ensure_ascii=False, indent=2), encoding="utf-8")

    # excel batch (2 hojas)
    excel_batch = out_dir / f"batch_{ts}.xlsx"
    write_two_sheet_excel(excel_batch, all_cabeceras, all_lineas)

    logger.info("Procesados documentos/imágenes: %d", count_docs)
    logger.info("Cabeceras lote → %s", cabecera_batch)
    logger.info("Líneas lote    → %s", lineas_batch)
    logger.info("Excel lote     → %s", excel_batch)

    return {
        "count": count_docs,
        "cabeceras": all_cabeceras,
        "lineas": all_lineas,
        "cabecera_batch_path": str(cabecera_batch),
        "lineas_batch_path": str(lineas_batch),
        "excel_batch_path": str(excel_batch),
    }
