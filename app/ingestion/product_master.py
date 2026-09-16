"""Canonical, validated records built from cleaned catalogue sheets.

The Inventory Update file and the Meesho Listing file use unrelated
identifier systems (numeric Product/Style/Variation IDs vs. human-readable
Seller SKUs) with no reliable join key between them, so this stage keeps
them as two separate product masters rather than guessing a merge.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ValidationError


class InventoryRecord(BaseModel):
    catalog_name: str | None = None
    catalog_id: int | None = None
    product_name: str
    product_id: int
    style_id: str | None = None
    variation_id: int | None = None
    variation: str | None = None
    stock_status: str | None = None
    system_stock_count: float | None = None
    your_stock_count: float | None = None


class MeeshoListingRecord(BaseModel):
    seller_sku: str
    seo_title: str | None = None
    description: str | None = None
    keywords: str | None = None
    listing_id: float | None = None
    settlement_price: float | None = None
    pack_qty: float | None = None
    pack_unit_detail: str | None = None
    shipping_charge: float | None = None
    dimensions: str | None = None
    volumetric_weight_kg: float | None = None
    actual_weight_kg: float | None = None
    chargeable_weight_kg: float | None = None
    category_1: str | None = None
    category_2: str | None = None
    category_3: str | None = None


class IngestionResult(BaseModel):
    records: list
    row_errors: list[str]
    duplicate_keys_dropped: int


def _build(
    df: pd.DataFrame, model: type[BaseModel], key_field: str
) -> IngestionResult:
    seen_keys: set = set()
    records = []
    row_errors: list[str] = []
    duplicates_dropped = 0

    for i, row in enumerate(df.to_dict(orient="records")):
        # pandas silently upcasts all-None object columns to float64 NaN
        # (e.g. an unfilled "dimensions" column), so normalize NaN -> None
        # at this boundary rather than fighting column dtypes upstream.
        row = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in row.items()}
        try:
            record = model.model_validate(row)
        except ValidationError as e:
            row_errors.append(f"row {i}: {e}")
            continue

        key = getattr(record, key_field)
        if key in seen_keys:
            duplicates_dropped += 1
            continue
        seen_keys.add(key)
        records.append(record)

    return IngestionResult(
        records=records,
        row_errors=row_errors,
        duplicate_keys_dropped=duplicates_dropped,
    )


def build_inventory_master(df: pd.DataFrame) -> IngestionResult:
    return _build(df, InventoryRecord, key_field="product_id")


def build_listing_master(df: pd.DataFrame) -> IngestionResult:
    return _build(df, MeeshoListingRecord, key_field="seller_sku")
