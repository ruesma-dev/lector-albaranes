# domain/schemas.py
from __future__ import annotations
# domain/schemas.py

from typing import Optional, List
from pydantic import BaseModel, Field


class Cabecera(BaseModel):
    proveedor_nombre: Optional[str] = Field(None, description="Nombre del proveedor")
    proveedor_cif: Optional[str] = Field(None, description="CIF/NIF del proveedor")
    fecha: Optional[str] = Field(
        None, description="Fecha del albarán/factura (ideal ISO YYYY-MM-DD, pero acepta otras)"
    )
    numero_albaran: Optional[str] = Field(None, description="Número de albarán/factura")
    forma_pago: Optional[str] = Field(None, description="Forma de pago si aparece")
    obra_codigo: Optional[str] = Field(None, description="Código de la obra si aparece")
    obra_nombre: Optional[str] = Field(None, description="Nombre de la obra si aparece")
    obra_direccion: Optional[str] = Field(None, description="Dirección de la obra si aparece")


class Linea(BaseModel):
    codigo: Optional[str] = Field(None, description="Código de artículo/servicio si existe")
    # Aceptamos str | float porque el LLM puede devolver cualquier tipo numérico
    cantidad: Optional[float | str] = Field(None, description="Cantidad")
    concepto: Optional[str] = Field(None, description="Descripción de la línea")
    precio: Optional[float | str] = Field(None, description="Precio unitario")
    descuento: Optional[float | str] = Field(None, description="Descuento (importe o % si aparece)")
    precio_neto: Optional[float | str] = Field(None, description="Importe neto de la línea")
    codigo_imputacion: Optional[str] = Field(
        None,
        description="Código manuscrito/indicaciones del jefe de obra para imputación de la línea",
    )


class ExtractResponse(BaseModel):
    cabecera: Cabecera
    lineas: List[Linea] = Field(default_factory=list)
