"""Re-upload-ready export: same column names, order, and sheet name as the
Meesho listing file this catalogue was originally downloaded as (see
data/raw/santerra_listing_sample.xls, sheet "Meesho") -- unlike
catalogue_export.py's side-by-side review file, this is meant to go
straight back into Meesho's bulk upload tool, not in front of a person.

Every SKU in the catalogue appears, in the same shape it came in. Only the
title, description, and keywords of an *effectively APPROVED* run (human
decision if one exists, else the pipeline's own verdict) get swapped in --
everything else, including title/description/keywords for a SKU that's
still NEEDS_REVIEW, REJECTED, or never run at all, stays exactly what
Meesho gave us. That makes this safe to re-upload as an incremental update:
it only changes the rows that actually passed review.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg

from app.database.repository import list_all_listings_with_latest_optimization

# canonical_field -> original display-cased column name, same name, order,
# and casing as Meesho's own template (see
# data/raw/santerra_listing_sample.xls, sheet "Meesho"). Deliberately not
# reused from app/ingestion/schema_map.py's MEESHO_LISTING_COLUMNS: that
# dict's values are normalize_column()-ed (lowercased) for matching against
# a workbook with unknown casing, not the display casing Meesho actually
# ships -- exporting those directly would write "seller sku" instead of
# "Seller SKU".
CANONICAL_TO_RAW_COLUMN = {
    "seller_sku": "Seller SKU",
    "seo_title": "Meesho SEO Title",
    "description": "Meesho Description",
    "keywords": "Trending Keywords",
    "listing_id": "Listing ID",
    "settlement_price": "Bank Settlement Price",
    "pack_qty": "Pack Qty",
    "pack_unit_detail": "Pack/Unit Detail",
    "shipping_charge": "Shipping Charges (Indicative Minimum ₹)",
    "dimensions": "Suggested Compact Dimension (L x W x H)",
    "volumetric_weight_kg": "Volumetric Weight kg",
    "actual_weight_kg": "Approx Actual Weight kg",
    "chargeable_weight_kg": "Chargeable Weight kg",
    "category_1": "Suggested Category 1",
    "category_2": "Suggested Category 2",
    "category_3": "Suggested Category 3",
}


def build_meesho_upload_rows(conn: psycopg.Connection) -> list[dict]:
    records = list_all_listings_with_latest_optimization(conn)
    rows = []
    for r in records:
        approved = r["effective_status"] == "APPROVED"
        rows.append(
            {
                "seller_sku": r["seller_sku"],
                "seo_title": r["generated_title"] if approved else r["seo_title"],
                "description": r["generated_description"] if approved else r["description"],
                "keywords": (
                    ", ".join(r["generated_keywords"]) if approved else r["keywords"]
                ),
                # Never touched by the pipeline -- always the original value.
                "listing_id": r["listing_id"],
                "settlement_price": r["settlement_price"],
                "pack_qty": r["pack_qty"],
                "pack_unit_detail": r["pack_unit_detail"],
                "shipping_charge": r["shipping_charge"],
                "dimensions": r["dimensions"],
                "volumetric_weight_kg": r["volumetric_weight_kg"],
                "actual_weight_kg": r["actual_weight_kg"],
                "chargeable_weight_kg": r["chargeable_weight_kg"],
                "category_1": r["category_1"],
                "category_2": r["category_2"],
                "category_3": r["category_3"],
            }
        )
    return rows


def export_meesho_upload(conn: psycopg.Connection, output_path: str | Path) -> int:
    rows = build_meesho_upload_rows(conn)
    df = pd.DataFrame(rows, columns=list(CANONICAL_TO_RAW_COLUMN.keys()))
    df = df.rename(columns=CANONICAL_TO_RAW_COLUMN)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix == ".csv":
        df.to_csv(output_path, index=False)
    else:
        # Sheet name matches the original download so this drops into the
        # same workbook shape, even though Meesho's own file also carries
        # Flipkart/Amazon sheets this project doesn't touch.
        df.to_excel(output_path, index=False, sheet_name="Meesho")

    return len(df)
