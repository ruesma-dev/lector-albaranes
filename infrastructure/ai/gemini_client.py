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
            "Eres un administrativo de obra en España que registra albaranes y facturas de subcontratistas y "
            "proveedores de materiales. Conoces formatos habituales (albaranes, facturas simplificadas y completas), "
            "abreviaturas (CIF/NIF/NIE), y la práctica de obra: el jefe de obra anota a mano el código de imputación "
            "de partida por línea o para todas las líneas (con llaves, flechas, rayas o por proximidad/altura). "
            "Trabajas con documentación escaneada o fotografiada (posibles inclinaciones, sombras, sellos, texto borroso "
            "o manuscrito). Tu objetivo es leer con precisión y devolver SOLO JSON con una cabecera y sus líneas, sin "
            "añadir texto adicional.\n\n"
            "Convenciones:\n"
            "- Idioma: es-ES. Moneda esperada: EUR (no devuelvas símbolos, sólo números).\n"
            "- Fechas: intenta ISO YYYY-MM-DD si es posible; si no, deja la fecha tal cual y el resto a null.\n"
            "- Números: usa punto decimal (1234.56). Sin separador de miles. Sin “€” ni “%”.\n"
            "- Si un dato no está o hay dudas, devuelve null.\n"
            "- No inventes valores. No mezcles ni fusiones líneas.\n"
            "- Si el documento es multipágina, prioriza la página con el cuerpo de líneas; si hay varias, procesa todas.\n\n"
            "Control de calidad:\n"
            "- Si hay cantidad y precio, puedes calcular un precio_neto aproximado aplicando descuento si aparece en la línea "
            "(no incluyas IVA salvo que figure explícito por línea). Si no cuadra, deja lo dudoso en null."
        )

        user_instructions = (
            "Lee la imagen del albarán/factura y devuelve SOLO JSON con esta estructura exacta:\n\n"
            "{\n"
            '  "cabecera": {\n'
            '    "proveedor_nombre": string|null,\n'
            '    "proveedor_cif": string|null,\n'
            '    "fecha": string|null,\n'
            '    "numero_albaran": string|null,\n'
            '    "forma_pago": string|null,\n'
            '    "obra_codigo": string|null,\n'
            '    "obra_nombre": string|null,\n'
            '    "obra_direccion": string|null,\n'
            '    "id": string|null\n'
            "  },\n"
            '  "lineas": [\n'
            "    {\n"
            '      "id": string|null,\n'
            '      "cabecera_id": null,\n'
            '      "codigo": string|null,\n'
            '      "cantidad": number|null,\n'
            '      "concepto": string|null,\n'
            '      "precio": number|null,\n'
            '      "descuento": number|null,\n'
            '      "precio_neto": number|null,\n'
            '      "codigo_imputacion": string|null,\n'
            '      "confianza_pct": number|null\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Reglas CABECERA:\n"
            "- proveedor_nombre: razón social del proveedor (emisor del albarán).\n"
            "- proveedor_cif: captura CIF/NIF/NIE del proveedor (prioriza el del emisor si hay varios).\n"
            "- fecha: la del albarán (preferible YYYY-MM-DD si inequívoca).\n"
            "- numero_albaran: identificador del documento (no pedido/cliente).\n"
            "- forma_pago: deducible de textos como 'contado', 'transferencia', '30 días', etc.\n"
            "- obra_*: captura código/nombre y dirección de la obra si figuran.\n\n"
            "Reglas LÍNEAS:\n"
            "- Identifica cada línea de concepto (evita subtotales/totales/IVA/portes/observaciones).\n"
            "- cantidad: número de unidades (solo el número; ignora 'kg', 'm', etc.).\n"
            "- precio: precio unitario sin IVA. Si sólo hay precio bruto y descuento, devuelve precio unitario bruto y rellena descuento.\n"
            "- descuento: si aparece (p. ej. '20%'), devuélvelo como número (20.0). Si hay varios, usa el más claro y no inventes.\n"
            "- precio_neto: si figura explícito, léelo; si no, calcula cantidad*precio*(1 - descuento/100) cuando sea posible; si falta algo, null.\n\n"
            "Código de imputación manuscrito (clave):\n"
            "- Puede indicarse con flechas, rayas, llaves `{}`, referencias tipo '->', o por proximidad/altura respecto a las líneas.\n"
            "- Si hay un único código manuscrito visible sin ambigüedad, aplícalo a TODAS las líneas.\n"
            "- Si hay varios, asigna por cercanía vertical y señales gráficas (llave abarcando varias líneas → aplícalo a esas líneas).\n"
            "- Si una línea no puede asociarse con claridad a ningún código, usa codigo_imputacion = null.\n"
            "- Para cada línea, devuelve confianza_pct (0–100) estimando certeza de la asignación de codigo_imputacion:\n"
            "  * Flecha/llave directa: 85–100\n"
            "  * Misma altura y muy próximo: 60–85\n"
            "  * Ambiguo / varios candidatos: 20–60\n"
            "  * No legible: 0–15\n"
            "- No uses el símbolo '%'; confianza_pct es un número puro (ej. 87.5).\n\n"
            "Desempates (si un código podría aplicar a dos líneas):\n"
            "1) Señal explícita (flecha/llave) gana a proximidad.\n"
            "2) Misma altura gana a proximidad diagonal.\n"
            "3) Si sigue el empate, elige la línea más cercana y reduce confianza_pct.\n"
            "4) Si no hay base suficiente: codigo_imputacion = null y confianza_pct bajo (p. ej. 25.0).\n\n"
            "Salida: devuelve únicamente el JSON anterior, sin texto adicional ni bloques de código. Usa null cuando falte información."
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
