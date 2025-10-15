# application/pipeline/steps/load_image.py
from __future__ import annotations
# application/pipeline/steps/load_image.py

import logging
from pathlib import Path
from typing import Any, Dict


def step_load_image(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Carga bytes de imagen desde 'image_path' en el context.
    """
    logger: logging.Logger = context["logger"]
    image_path = Path(context["image_path"])
    if not image_path.exists():
        raise FileNotFoundError(f"No existe el fichero: {image_path}")

    with image_path.open("rb") as f:
        image_bytes = f.read()

    context["image_bytes"] = image_bytes
    context["image_mime"] = _guess_mime(image_path.suffix.lower())
    logger.info("Imagen cargada: %s (%d bytes)", image_path.name, len(image_bytes))
    return context


def _guess_mime(ext: str) -> str:
    if ext == ".png":
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"
