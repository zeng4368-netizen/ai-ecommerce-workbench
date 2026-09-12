from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


def normalize_name(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-:/\\()\[\]（）【】]+", "", text)


def find_column(df: pd.DataFrame, aliases: list[str], required: bool = False) -> str | None:
    normalized = {normalize_name(col): col for col in df.columns}
    for alias in aliases:
        hit = normalized.get(normalize_name(alias))
        if hit:
            return hit
    for alias in aliases:
        needle = normalize_name(alias)
        if not needle:
            continue
        for key, col in normalized.items():
            if needle in key or key in needle:
                return col
    if required:
        raise ValueError(f"Missing required column. Tried aliases: {aliases}")
    return None


def read_excel(path: str | Path, sheet_name: str | int | None = 0) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name)


def write_workbook(path: str | Path, sheets: dict[str, pd.DataFrame]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31] or "Sheet"
            df.to_excel(writer, sheet_name=safe_name, index=False)
    return output_path
