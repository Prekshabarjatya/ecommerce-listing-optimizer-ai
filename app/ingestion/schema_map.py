"""Column-name schema maps for the Santerra catalogue export formats.

Meesho's bulk-template exports change column wording between releases, so we
match on normalized column *names* rather than positions, and identify which
known source a sheet is by which required columns it contains.
"""

from __future__ import annotations

from enum import Enum


def normalize_column(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


class SourceType(str, Enum):
    INVENTORY_UPDATE = "inventory_update"
    MEESHO_LISTING = "meesho_listing"


# canonical_field -> normalized raw column name(s) that may carry it
INVENTORY_UPDATE_COLUMNS: dict[str, str] = {
    "serial_no": "serial no",
    "catalog_name": "catalog name",
    "catalog_id": "catalog id",
    "product_name": "product name",
    "product_id": "product id",
    "style_id": "style id",
    "variation_id": "variation id",
    "variation": "variation",
    "stock_status": "stock",
    "system_stock_count": "system stock count",
    "your_stock_count": "your stock count",
}

MEESHO_LISTING_COLUMNS: dict[str, str] = {
    "seller_sku": "seller sku",
    "seo_title": "meesho seo title",
    "description": "meesho description",
    "keywords": "trending keywords",
    "listing_id": "listing id",
    "settlement_price": "bank settlement price",
    "pack_qty": "pack qty",
    "pack_unit_detail": "pack/unit detail",
    "shipping_charge": "shipping charges (indicative minimum ₹)",
    "dimensions": "suggested compact dimension (l x w x h)",
    "volumetric_weight_kg": "volumetric weight kg",
    "actual_weight_kg": "approx actual weight kg",
    "chargeable_weight_kg": "chargeable weight kg",
    "category_1": "suggested category 1",
    "category_2": "suggested category 2",
    "category_3": "suggested category 3",
}

# The subset of columns that must be present (by normalized name) to
# recognize a sheet as a given source type.
SOURCE_SIGNATURES: dict[SourceType, set[str]] = {
    SourceType.INVENTORY_UPDATE: {"product id", "style id", "variation id", "stock"},
    SourceType.MEESHO_LISTING: {"seller sku", "meesho seo title", "pack qty"},
}

SOURCE_COLUMN_MAPS: dict[SourceType, dict[str, str]] = {
    SourceType.INVENTORY_UPDATE: INVENTORY_UPDATE_COLUMNS,
    SourceType.MEESHO_LISTING: MEESHO_LISTING_COLUMNS,
}

# Canonical field used to detect and drop the instructional/example row that
# Meesho templates sometimes place directly under the header row.
SOURCE_ID_FIELD: dict[SourceType, str] = {
    SourceType.INVENTORY_UPDATE: "product_id",
    SourceType.MEESHO_LISTING: "seller_sku",
}


def detect_source_type(raw_columns: list[str]) -> SourceType | None:
    normalized = {normalize_column(c) for c in raw_columns}
    for source_type, required in SOURCE_SIGNATURES.items():
        if required.issubset(normalized):
            return source_type
    return None
