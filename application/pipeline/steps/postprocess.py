# application/pipeline/steps/postprocess.py
from __future__ import annotations
# application/pipeline/steps/postprocess.py

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings
from domain.schemas import ExtractResponse, Cabecera, Linea


def _parse_num(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    elif s.count(",") > 1 and s.count(".") == 0:
        parts = s.split(",")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except ValueError:
        return None


def step_postprocess(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Genera JSON por documento:
      - cabecera_*.json  (lista con una fila)
      - lineas_*.json    (lista con n filas)
    Mantiene también el JSON "combinado" legacy: albaran_*.json
    """
    logger: logging.Logger = context["logger"]
    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result: ExtractResponse = context["extract_result"]
    cabecera_id = str(uuid.uuid4())

    cabecera_obj = result.cabecera or Cabecera()
    cabecera_row = {
        "id": cabecera_id,
        "proveedor_nombre": cabecera_obj.proveedor_nombre,
        "proveedor_cif": cabecera_obj.proveedor_cif,
        "fecha": cabecera_obj.fecha,
        "numero_albaran": cabecera_obj.numero_albaran,
        "forma_pago": cabecera_obj.forma_pago,
        "obra_codigo": cabecera_obj.obra_codigo,
        "obra_nombre": cabecera_obj.obra_nombre,
        "obra_direccion": cabecera_obj.obra_direccion,
    }

    lineas_out = []
    for l in (result.lineas or []):
        lineas_out.append(
            {
                "cabecera_id": cabecera_id,
                "codigo": l.codigo,
                "cantidad": _parse_num(l.cantidad),
                "concepto": l.concepto,
                "precio": _parse_num(l.precio),
                "descuento": _parse_num(l.descuento),
                "precio_neto": _parse_num(l.precio_neto),
                "codigo_imputacion": l.codigo_imputacion,
            }
        )

    # JSON combinado legacy
    final_json = {
        "cabecera": [cabecera_row],
        "lineas": lineas_out,
    }
    combined_file = out_dir / f"albaran_{cabecera_id}.json"
    combined_file.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # Nuevos JSON separados (por documento)
    cabecera_file = out_dir / f"cabecera_{cabecera_id}.json"
    lineas_file = out_dir / f"lineas_{cabecera_id}.json"
    cabecera_file.write_text(json.dumps([cabecera_row], ensure_ascii=False, indent=2), encoding="utf-8")
    lineas_file.write_text(json.dumps(lineas_out, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Guardado: %s, %s (y combinado %s)", cabecera_file.name, lineas_file.name, combined_file.name)

    context["cabecera_row"] = cabecera_row
    context["lineas_rows"] = lineas_out
    context["output_file"] = str(combined_file)
    context["output_json"] = final_json
    return context
