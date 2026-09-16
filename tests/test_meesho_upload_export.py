import pandas as pd

from app.database.repository import (
    insert_optimization_run,
    record_human_decision,
    upsert_listing_records,
)
from app.export.meesho_upload_export import CANONICAL_TO_RAW_COLUMN, build_meesho_upload_rows, export_meesho_upload
from app.ingestion.product_master import MeeshoListingRecord
from app.ingestion.schema_map import MEESHO_LISTING_COLUMNS

RAW_MEESHO_COLUMNS = [
    "Seller SKU",
    "Meesho SEO Title",
    "Meesho Description",
    "Trending Keywords",
    "Listing ID",
    "Bank Settlement Price",
    "Pack Qty",
    "Pack/Unit Detail",
    "Shipping Charges (Indicative Minimum ₹)",
    "Suggested Compact Dimension (L x W x H)",
    "Volumetric Weight kg",
    "Approx Actual Weight kg",
    "Chargeable Weight kg",
    "Suggested Category 1",
    "Suggested Category 2",
    "Suggested Category 3",
]


def _seed_unrun_listing(conn, seller_sku="SKU-UNRUN"):
    upsert_listing_records(
        conn,
        [
            MeeshoListingRecord(
                seller_sku=seller_sku,
                seo_title="Original title",
                description="Original description",
                keywords="original, keywords",
                category_1="Face Wipes",
            )
        ],
    )


def _seed_run(conn, seller_sku="SKU-A", approval_status="APPROVED", human_decision=None):
    upsert_listing_records(
        conn,
        [
            MeeshoListingRecord(
                seller_sku=seller_sku,
                seo_title="Original title",
                description="Original description",
                keywords="original, keywords",
                listing_id=123,
                settlement_price=99.5,
                category_1="Face Wipes",
            )
        ],
    )
    run_id = insert_optimization_run(
        conn,
        {
            "seller_sku": seller_sku,
            "audit_score": 60,
            "audit_issues": [],
            "generated_title": "Generated title",
            "generated_highlights": ["Gentle", "Travel friendly"],
            "generated_description": "Generated description",
            "generated_keywords": ["wet wipes", "aloe vera"],
            "fact_check_passed": approval_status != "REJECTED",
            "blocked_claims": ["fully biodegradable"] if approval_status == "REJECTED" else [],
            "critic_overall": 92,
            "critic_scores": {"seo": 90, "readability": 92, "completeness": 91, "brand_consistency": 95},
            "approval_status": approval_status,
        },
    )
    if human_decision:
        record_human_decision(conn, run_id, human_decision)
    return run_id


def test_canonical_to_raw_column_stays_in_sync_with_schema_map():
    """CANONICAL_TO_RAW_COLUMN hardcodes display-cased names rather than
    reusing schema_map's normalized ones (see the module docstring) --
    this catches the two drifting apart if a field is ever added to or
    removed from the Meesho listing schema."""
    assert set(CANONICAL_TO_RAW_COLUMN.keys()) == set(MEESHO_LISTING_COLUMNS.keys())


def test_approved_run_uses_generated_content(pg_conn):
    _seed_run(pg_conn, approval_status="APPROVED")
    rows = build_meesho_upload_rows(pg_conn)

    assert len(rows) == 1
    row = rows[0]
    assert row["seller_sku"] == "SKU-A"
    assert row["seo_title"] == "Generated title"
    assert row["description"] == "Generated description"
    assert row["keywords"] == "wet wipes, aloe vera"
    # Untouched fields always come from the original listing.
    assert row["listing_id"] == 123
    assert row["settlement_price"] == 99.5
    assert row["category_1"] == "Face Wipes"


def test_needs_review_run_keeps_original_content(pg_conn):
    _seed_run(pg_conn, approval_status="NEEDS_REVIEW")
    rows = build_meesho_upload_rows(pg_conn)

    row = rows[0]
    assert row["seo_title"] == "Original title"
    assert row["description"] == "Original description"
    assert row["keywords"] == "original, keywords"


def test_rejected_run_keeps_original_content(pg_conn):
    _seed_run(pg_conn, approval_status="REJECTED")
    rows = build_meesho_upload_rows(pg_conn)

    row = rows[0]
    assert row["seo_title"] == "Original title"
    assert row["description"] == "Original description"


def test_human_approved_needs_review_run_uses_generated_content(pg_conn):
    _seed_run(pg_conn, approval_status="NEEDS_REVIEW", human_decision="APPROVED")
    rows = build_meesho_upload_rows(pg_conn)

    row = rows[0]
    assert row["seo_title"] == "Generated title"
    assert row["description"] == "Generated description"


def test_sku_with_no_run_at_all_keeps_original_content(pg_conn):
    _seed_unrun_listing(pg_conn)
    rows = build_meesho_upload_rows(pg_conn)

    assert len(rows) == 1
    row = rows[0]
    assert row["seo_title"] == "Original title"
    assert row["keywords"] == "original, keywords"


def test_every_sku_appears_regardless_of_status(pg_conn):
    _seed_run(pg_conn, seller_sku="SKU-APPROVED", approval_status="APPROVED")
    _seed_run(pg_conn, seller_sku="SKU-PENDING", approval_status="NEEDS_REVIEW")
    _seed_unrun_listing(pg_conn, seller_sku="SKU-UNRUN")
    rows = build_meesho_upload_rows(pg_conn)

    assert {r["seller_sku"] for r in rows} == {"SKU-APPROVED", "SKU-PENDING", "SKU-UNRUN"}


def test_export_writes_xlsx_with_original_meesho_column_names(pg_conn, tmp_path):
    output = tmp_path / "upload.xlsx"
    _seed_run(pg_conn, approval_status="APPROVED")
    export_meesho_upload(pg_conn, output)

    df = pd.read_excel(output)
    assert list(df.columns) == RAW_MEESHO_COLUMNS
    assert df.loc[0, "Seller SKU"] == "SKU-A"
    assert df.loc[0, "Meesho SEO Title"] == "Generated title"


def test_export_writes_csv_when_extension_is_csv(pg_conn, tmp_path):
    output = tmp_path / "upload.csv"
    _seed_run(pg_conn, approval_status="APPROVED")
    export_meesho_upload(pg_conn, output)

    df = pd.read_csv(output)
    assert list(df.columns) == RAW_MEESHO_COLUMNS
