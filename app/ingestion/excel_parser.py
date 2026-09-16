"""Load a Santerra catalogue workbook and identify + rename each sheet's
columns to canonical field names, without assuming fixed column positions.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.ingestion.schema_map import (
    SOURCE_COLUMN_MAPS,
    SourceType,
    detect_source_type,
    normalize_column,
)


class UnrecognizedSheetError(Exception):
    pass


def _rename_to_canonical(df: pd.DataFrame, source_type: SourceType) -> pd.DataFrame:
    column_map = SOURCE_COLUMN_MAPS[source_type]
    normalized_to_canonical = {raw: field for field, raw in column_map.items()}

    rename = {}
    for col in df.columns:
        canonical = normalized_to_canonical.get(normalize_column(col))
        if canonical:
            rename[col] = canonical
    df = df.rename(columns=rename)

    # Keep only recognized canonical columns, in a stable order.
    keep = [field for field in column_map if field in df.columns]
    return df[keep]


def parse_workbook(path: str | Path) -> dict[SourceType, pd.DataFrame]:
    """Parse every sheet in the workbook, returning one cleaned-columns
    DataFrame per recognized source type found. Sheets that don't match a
    known signature are skipped."""
    path = Path(path)
    xl = pd.ExcelFile(path)

    results: dict[SourceType, pd.DataFrame] = {}
    for sheet_name in xl.sheet_names:
        raw = xl.parse(sheet_name, dtype=str)
        source_type = detect_source_type(list(raw.columns))
        if source_type is None:
            continue
        results[source_type] = _rename_to_canonical(raw, source_type)

    return results


def parse_source(path: str | Path, source_type: SourceType) -> pd.DataFrame:
    """Parse a workbook and return only the sheet matching source_type."""
    sheets = parse_workbook(path)
    if source_type not in sheets:
        raise UnrecognizedSheetError(
            f"No sheet in {path} matched source type {source_type.value!r}"
        )
    return sheets[source_type]
