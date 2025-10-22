# infrastructure/ai/ai_client_factory.py
from __future__ import annotations
# infrastructure/ai/ai_client_factory.py

import logging

from config.settings import settings

# Importamos localmente para no forzar dependencias si no se usan
from infrastructure.ai.gemini_client import GeminiClient  # ya existe
try:
    from infrastructure.ai.openai_client import OpenAIClient
except Exception:  # pragma: no cover
    OpenAIClient = None  # type: ignore


def build_ai_client(logger: logging.Logger):
    """
    Devuelve una instancia de cliente IA según settings.ai_provider.
    La interfaz esperada es la misma que GeminiClient:
      - extract_from_file(path) -> ExtractResponse
      - extract_from_image_bytes(bytes, mime_type) -> ExtractResponse
    """
    provider = (settings.ai_provider or "gemini").lower()
    if provider == "openai":
        if not OpenAIClient:
            raise RuntimeError("OpenAIClient no disponible. Instala 'openai' y añade OPENAI_API_KEY en .env.")
        logger.info("IA Provider seleccionado: OpenAI (%s)", settings.openai_model_name)
        return OpenAIClient(logger)
    logger.info("IA Provider seleccionado: Gemini (%s)", settings.gemini_model_name)
    return GeminiClient(logger)
