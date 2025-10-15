# application/pipeline/steps/call_gemini_extract.py
from __future__ import annotations
# application/pipeline/steps/call_gemini_extract.py

import logging
from typing import Any, Dict

from infrastructure.ai.gemini_client import GeminiClient


def step_call_gemini_extract(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Llama a Gemini con la imagen y obtiene ExtractResponse (cabecera + lineas).
    """
    logger: logging.Logger = context["logger"]
    client: GeminiClient = context["gemini_client"]
    image_bytes: bytes = context["image_bytes"]
    mime: str = context["image_mime"]

    result = client.extract_from_image_bytes(image_bytes, mime_type=mime)
    context["extract_result"] = result
    logger.info("Extracción OK: %d líneas", len(result.lineas or []))
    return context
