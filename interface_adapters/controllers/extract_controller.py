# interface_adapters/controllers/extract_controller.py
from __future__ import annotations
# interface_adapters/controllers/extract_controller.py

import logging
from typing import Dict, Any

from application.pipeline.pipeline import Pipeline
from application.pipeline.steps.load_image import step_load_image
from application.pipeline.steps.call_gemini_extract import step_call_gemini_extract
from application.pipeline.steps.postprocess import step_postprocess
from infrastructure.ai.ai_client_factory import build_ai_client


class ExtractController:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        # ← ahora elegimos el cliente según .env (gemini | openai)
        self.client = build_ai_client(self.logger)

    def extract_from_image(self, image_path: str) -> Dict[str, Any]:
        pipeline = Pipeline(steps=[step_load_image, step_call_gemini_extract, step_postprocess])
        ctx: Dict[str, Any] = {
            "logger": self.logger,
            "image_path": image_path,
            # Compatibilidad: el step actual espera 'gemini_client'.
            # Ponemos el cliente elegido (Gemini u OpenAI) en la misma clave.
            "gemini_client": self.client,
        }
        return pipeline.run(ctx)
