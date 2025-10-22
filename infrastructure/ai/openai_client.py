# infrastructure/ai/openai_client.py
from __future__ import annotations
# infrastructure/ai/openai_client.py

import base64
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter

from config.settings import settings
from domain.schemas import ExtractResponse

try:
    from openai import OpenAI
    from openai import APIError, RateLimitError, InternalServerError, APITimeoutError
except Exception as e:  # pragma: no cover
    raise RuntimeError("Falta paquete 'openai'. Instala con: pip install openai") from e


class RateLimiter:
    """Limita a ~N requests/minuto (RPM)."""
    def __init__(self, rpm: int = 5) -> None:
        rpm = max(1, int(rpm or 5))
        self.min_interval = 60.0 / float(rpm)
        self._last = 0.0

    def wait(self) -> None:
        now = time.time()
        delay = self.min_interval - (now - self._last)
        if delay > 0:
            time.sleep(delay + random.uniform(0.0, 0.05))
        self._last = time.time()


def _should_retry(exc: Exception) -> bool:
    m = str(exc).lower()
    return any(t in m for t in ("429", "rate", "quota", "exceeded", "unavailable", "timeout", "503"))


def _extract_retry_seconds(err_msg: str) -> Optional[float]:
    """
    Intenta leer del mensaje de error 'Please retry in 19.50s'.
    Si no aparece, devuelve None para backoff exponencial estándar.
    """
    m = re.search(r"retry in\s+(\d+(?:\.\d+)?)s", err_msg, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _retry_after_from_exc(e: Exception) -> Optional[float]:
    """Lee Retry-After en segundos del error del SDK si está disponible."""
    try:
        resp = getattr(e, "response", None)
        if resp is None:
            return None
        ra = resp.headers.get("retry-after")
        if ra is None:
            return None
        try:
            return float(ra)
        except Exception:
            return None
    except Exception:
        return None


class OpenAIClient:
    """
    Cliente OpenAI Responses API (gpt-5) con:
    - Para imágenes: se envían como data URL base64 en 'input_image'.
    - Para PDF: se suben a Files (purpose=user_data) y se pasan como 'input_file'.
    - Llamada → JSON validado (ExtractResponse).
    - Rate limit por RPM + reintentos amables en 429/503.
    - SIN uso de 'temperature' (evitamos 400 con gpt-5).
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

        api_key = (getattr(settings, "openai_api_key", "") or os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY no configurada en .env")

        # Desactivamos reintentos automáticos del SDK para no solaparlos con los nuestros
        self.client = OpenAI(api_key=api_key, max_retries=0, timeout=60.0)

        self.model = getattr(settings, "openai_model_name", None) or "gpt-5"
        self.on429 = (getattr(settings, "openai_on_429", "wait") or "wait").lower()
        self.max_attempts = int(getattr(settings, "openai_max_attempts", 6) or 6)
        self.limiter = RateLimiter(int(getattr(settings, "openai_rpm", 5) or 5))

        self.logger.info(
            "OpenAI configurado. Model=%s  RPM=%s  429=%s",
            self.model, getattr(settings, "openai_rpm", 5), self.on429
        )
        self.adapter = TypeAdapter(ExtractResponse)

    # ------------------------- API pública (interfaz igual a GeminiClient) -------------------------

    def extract_from_file(self, fp: str) -> ExtractResponse:
        lower = fp.lower()
        if lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif lower.endswith(".webp"):
            mime = "image/webp"
        elif lower.endswith(".pdf"):
            mime = "application/pdf"
        else:
            mime = "image/jpeg"

        with open(fp, "rb") as f:
            data = f.read()
        return self.extract_from_image_bytes(data, mime_type=mime, file_name=Path(fp).name)

    def extract_from_image_bytes(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        file_name: str = "albaran",
    ) -> ExtractResponse:
        """
        Si mime_type == application/pdf -> sube a Files y usa input_file.
        Si mime_type empieza por image/ -> data URL base64 en input_image (sin Files).
        """
        attempts = 0
        while True:
            attempts += 1
            self.limiter.wait()
            try:
                # -------- 1) Preparar contenido multimodal según tipo --------
                content_items = []

                # System prompt
                system = (
                    "Actúas como un administrativo de obra en España. "
                    "Lees albaranes/facturas con códigos de imputación manuscritos."
                )
                content_items.append({"role": "system", "content": [{"type": "input_text", "text": system}]})

                # User content array
                user_content = []

                if mime_type == "application/pdf":
                    # Subimos el PDF a Files
                    up = self.client.files.create(file=(file_name, image_bytes, mime_type), purpose="user_data")
                    user_content.append({"type": "input_file", "file_id": up.id})
                elif mime_type.startswith("image/"):
                    # Enviar imagen como data URL base64 (no subir a Files)
                    b64 = base64.b64encode(image_bytes).decode("ascii")
                    data_url = f"data:{mime_type};base64,{b64}"
                    user_content.append({"type": "input_image", "image_url": data_url})
                else:
                    # Intento como imagen genérica
                    b64 = base64.b64encode(image_bytes).decode("ascii")
                    data_url = f"data:image/jpeg;base64,{b64}"
                    user_content.append({"type": "input_image", "image_url": data_url})

                # Instrucciones de usuario y formato esperado
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
                user_content.append({"type": "input_text", "text": user_instructions})

                content_items.append({"role": "user", "content": user_content})

                # -------- 2) Construir request (SIN temperature) --------
                req = dict(
                    model=self.model,
                    input=content_items,
                )

                # -------- 3) Llamar a Responses API --------
                resp = self.client.responses.create(**req)

                text = (resp.output_text or "").strip()
                if not text:
                    raise RuntimeError("Respuesta vacía del modelo.")
                return self.adapter.validate_json(text)

            except (RateLimitError, APITimeoutError, InternalServerError, APIError) as e:
                # Reintentos amables para 429/503/timeouts, etc.
                if not _should_retry(e) or attempts >= self.max_attempts or self.on429 != "wait":
                    raise

                # 1) Intentar Retry-After del header
                retry_s = _retry_after_from_exc(e)

                # 2) Si no viene, mirar mensaje "retry in Xs"
                if retry_s is None:
                    retry_s = _extract_retry_seconds(str(e))

                # 3) Si sigue sin venir, usar backoff exponencial con límite
                if retry_s is None:
                    retry_s = min(30.0, 2 ** (attempts - 1))

                # Jitter pequeño
                retry_s += random.uniform(0.05, 0.35)

                self.logger.warning(
                    "OpenAI 429/503 detectado. Reintentando en %.2fs (intento %d/%d)…",
                    retry_s, attempts, self.max_attempts
                )
                time.sleep(retry_s)
                continue

            except Exception:
                # Otras excepciones no reintentables
                raise
