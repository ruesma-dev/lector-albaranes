# infrastructure/export/excel_writer.py
from __future__ import annotations
# infrastructure/export/excel_writer.py

from pathlib import Path
from typing import Iterable, Mapping, Any

import pandas as pd


def write_two_sheet_excel(xlsx_path: Path,
                          cabecera_rows: Iterable[Mapping[str, Any]],
                          lineas_rows: Iterable[Mapping[str, Any]]) -> Path:
    """
    Crea un Excel con dos hojas:
      - 'cabecera' (lista de dicts; normalmente una fila)
      - 'lineas'
    """
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    df_cab = pd.DataFrame(list(cabecera_rows))
    df_lin = pd.DataFrame(list(lineas_rows))

    with pd.ExcelWriter(xlsx_path.as_posix(), engine="openpyxl") as writer:
        df_cab.to_excel(writer, index=False, sheet_name="cabecera")
        df_lin.to_excel(writer, index=False, sheet_name="lineas")
    return xlsx_path
