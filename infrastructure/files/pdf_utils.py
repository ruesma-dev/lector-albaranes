# infrastructure/files/pdf_utils.py
from __future__ import annotations
# infrastructure/files/pdf_utils.py

from pathlib import Path
from typing import List
import fitz  # PyMuPDF


def pdf_to_png_pages(pdf_path: Path, out_dir: Path) -> List[Path]:
    """
    Renderiza cada página del PDF a PNG y devuelve la lista de rutas.
    out_dir: carpeta donde se guardan las imágenes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path.as_posix())
    out_paths: List[Path] = []
    try:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=200)  # 200 DPI suficiente para OCR LLM
            out_file = out_dir / f"{pdf_path.stem}_p{i:03d}.png"
            pix.save(out_file.as_posix())
            out_paths.append(out_file)
    finally:
        doc.close()
    return out_paths
