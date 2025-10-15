# infrastructure/ai/gemini_client.py
from __future__ import annotations
# infrastructure/ai/gemini_client.py

import json
import logging
import os
import random
import re
import time
from typing import Optional

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None

from pydantic import ValidationError, TypeAdapter

from config.settings import settings
from domain.schemas import ExtractResponse


class RateLimiter:
    """Limita a ~N requests/minuto (RPM)."""

    def __init__(self, rpm: int = 10) -> None:
        rpm = max(1, int(rpm or 10))
        self.min_interval = 60.0 / float(rpm)
        self._last = 0.0

    def wait(self) -> None:
        now = time.time()
        delay = self.min_interval - (now - self._last)
        if delay > 0:
            time.sleep(delay + random.uniform(0.0, 0.05))
        self._last = time.time()


def _should_retry(msg: str) -> bool:
    m = (msg or "").lower()
    return ("429" in m) or ("rate" in m) or ("quota" in m) or ("exceeded" in m) or ("unavailable" in m) or ("503" in m)


def _mask(s: str, keep: int = 8) -> str:
    if not s:
        return ""
    s = s.strip()
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep)


def _extract_retry_seconds(err_msg: str) -> Optional[float]:
    """
    Intenta leer del mensaje de error "Please retry in 19.50s".
    Si no aparece, devuelve None para que apliquemos backoff exponencial estándar.
    """
    m = re.search(r"retry in\s+(\d+(?:\.\d+)?)s", err_msg, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _configure(logger: logging.Logger) -> tuple[str, str, Optional[str], int, str]:
    if not genai:
        raise RuntimeError("Gemini SDK no disponible (google.generativeai).")

    # API key
    api_key = (os.getenv("GEMINI_API_KEY") or settings.gemini_api_key or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Falta API key. Define GEMINI_API_KEY en .env (o GOOGLE_API_KEY).")
    genai.configure(api_key=api_key)

    # Modelos
    model_name = os.getenv("GEMINI_MODEL_NAME", settings.gemini_model_name or "gemini-2.5-pro")
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "").strip() or None  # ej: gemini-2.5-flash

    # Rate/429
    rpm = int(os.getenv("GEMINI_RPM", str(settings.gemini_rpm or 5)))
    on429 = (os.getenv("GEMINI_ON_429", settings.gemini_on_429 or "wait") or "wait").strip().lower()

    logger.info(
        "Gemini configurado. Model=%s  Fallback=%s  RPM=%d  429=%s  KeyPrefix=%s",
        model_name, fallback_model or "-", rpm, on429, _mask(api_key),
    )
    return api_key, model_name, fallback_model, rpm, on429


class GeminiClient:
    """
    Cliente Gemini (google.generativeai) con:
    - RateLimiter por RPM.
    - Reintentos 429/503 con retry-after si viene en el mensaje ("Please retry in Xs").
    - Fallback de modelo opcional si sigue fallando por cuota.
    - Health-check opcional (no gasta cuota si está desactivado, por defecto desactivado).
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.api_key, self.model_name, self.fallback_model, rpm, self.on429 = _configure(self.logger)
        self.limiter = RateLimiter(rpm)
        self.temperature = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
        self.healthcheck = (os.getenv("GEMINI_HEALTHCHECK", "false").lower() == "true")

        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": self.temperature,
            },
        )

        if self.healthcheck:
            try:
                # Esta llamada cuenta para la cuota; por defecto está desactivada.
                _ = self.model.generate_content([{"text": '{"ping":"ok"}'}])
                self.logger.info("Health-check Gemini OK (la API key responde).")
            except Exception as e:
                # Si excede cuota en healthcheck, no tumbar todo: solo avisa.
                self.logger.warning("Health-check falló (continuamos sin él): %s", e)

    def _maybe_switch_model(self) -> None:
        """Si hay un modelo de fallback configurado, cámbialo."""
        if not self.fallback_model:
            return
        if getattr(self, "_on_fallback", False):
            return  # ya cambiamos
        self.logger.warning("Cambiando a modelo fallback: %s", self.fallback_model)
        self.model = genai.GenerativeModel(
            self.fallback_model,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": self.temperature,
            },
        )
        self._on_fallback = True  # marca

    def extract_from_image_bytes(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractResponse:
        """
        Envía una imagen y devuelve ExtractResponse (cabecera + líneas).
        Con reintentos “amables” ante 429 usando el delay sugerido.
        """
        system = (
            "Actúas como un administrativo de obra en España. "
            "Lees albaranes/facturas, con posible código de imputación manuscrito."
        )
        user_instructions = (
            "#OBJETIVO: Devuelve SOLO JSON con:\n"
            "cabecera: proveedor_nombre, proveedor_cif, fecha, numero_albaran, forma_pago, "
            "obra_codigo, obra_nombre, obra_direccion.\n"
            "lineas: codigo, cantidad, concepto, precio, descuento, precio_neto, codigo_imputacion.\n\n"
            "Reglas codigo_imputacion:\n"
            "- Puede estar señalado por raya/llave o por proximidad.\n"
            "- Si solo hay un código manuscrito, aplica a todas las líneas.\n"
            "- Si no se ve claro, usa null.\n"
            "No inventes valores. Usa null cuando falte información."
        )

        image_part = {"mime_type": mime_type, "data": image_bytes}
        adapter = TypeAdapter(ExtractResponse)

        attempts = 0
        max_attempts = int(os.getenv("GEMINI_MAX_ATTEMPTS", "6"))

        while True:
            attempts += 1
            self.limiter.wait()
            try:
                resp = self.model.generate_content([system, image_part, {"text": user_instructions}])
                if not resp or not getattr(resp, "text", ""):
                    raise RuntimeError("Respuesta vacía del modelo.")
                return adapter.validate_json(resp.text)

            except Exception as e:
                msg = str(e)
                if not _should_retry(msg) or attempts >= max_attempts or self.on429 != "wait":
                    # último recurso: si hay fallback configurado y aún no lo hemos usado, cámbialo y reintenta una vez más
                    if self.fallback_model and not getattr(self, "_on_fallback", False):
                        self._maybe_switch_model()
                        continue
                    raise

                # Si el servidor sugiere "retry in Xs", obedecemos
                retry_s = _extract_retry_seconds(msg)
                if retry_s is None:
                    # backoff exponencial con jitter
                    retry_s = min(60.0, (2 ** (attempts - 1)))
                sleep_s = float(retry_s) + random.uniform(0.0, 0.3)
                self.logger.warning("429/503 detectado. Reintentando en %.2fs (intento %d/%d)…", sleep_s, attempts, max_attempts)
                time.sleep(sleep_s)
                continue

    def extract_from_file(self, fp: str) -> ExtractResponse:
        lower = fp.lower()
        if lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif lower.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/jpeg"
        with open(fp, "rb") as f:
            b = f.read()
        return self.extract_from_image_bytes(b, mime_type=mime)
