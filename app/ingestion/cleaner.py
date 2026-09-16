"""Row/type cleaning for parsed catalogue sheets.

Meesho's bulk templates put an instructional example row directly under the
header (e.g. a "Product id" column literally containing the text
"Product id"). We detect and drop that by checking whether the row's id
field fails to parse as the type it should be, rather than assuming it's
always row 0.
"""

from __future__ import annotations

import pandas as pd

from app.ingestion.schema_map import SOURCE_ID_FIELD, SourceType

NUMERIC_FIELDS: dict[SourceType, list[str]] = {
    SourceType.INVENTORY_UPDATE: [
        "catalog_id",
        "product_id",
        "variation_id",
        "system_stock_count",
        "your_stock_count",
    ],
    SourceType.MEESHO_LISTING: [
        "listing_id",
        "settlement_price",
        "pack_qty",
        "shipping_charge",
        "volumetric_weight_kg",
        "actual_weight_kg",
        "chargeable_weight_kg",
    ],
}

REQUIRED_FIELDS: dict[SourceType, list[str]] = {
    SourceType.INVENTORY_UPDATE: ["product_id", "product_name"],
    SourceType.MEESHO_LISTING: ["seller_sku"],
}


def _strip_strings(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        df[col] = df[col].apply(
            lambda v: " ".join(v.split()) if isinstance(v, str) else v
        )
        df[col] = df[col].where(df[col].notna() & (df[col] != ""), None)
    return df


def _coerce_numeric(df: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    for field in fields:
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors="coerce")
    return df


def _drop_instruction_rows(df: pd.DataFrame, source_type: SourceType) -> pd.DataFrame:
    """Drop leading rows whose id field isn't parseable as the numeric type
    real data uses there (Meesho template instruction/example rows)."""
    id_field = SOURCE_ID_FIELD[source_type]
    if id_field not in NUMERIC_FIELDS.get(source_type, []):
        return df

    numeric_id = pd.to_numeric(df[id_field], errors="coerce")
    first_valid = numeric_id.first_valid_index()
    if first_valid is None:
        return df.iloc[0:0]
    return df.loc[first_valid:]


def _drop_blank_rows(df: pd.DataFrame, source_type: SourceType) -> pd.DataFrame:
    required = REQUIRED_FIELDS[source_type]
    present = [f for f in required if f in df.columns]
    return df.dropna(how="all", subset=present) if present else df


def clean_sheet(df: pd.DataFrame, source_type: SourceType) -> pd.DataFrame:
    df = df.copy()
    df = _strip_strings(df)
    df = _drop_instruction_rows(df, source_type)
    df = _coerce_numeric(df, NUMERIC_FIELDS.get(source_type, []))
    df = _drop_blank_rows(df, source_type)
    df = df.reset_index(drop=True)
    return df
