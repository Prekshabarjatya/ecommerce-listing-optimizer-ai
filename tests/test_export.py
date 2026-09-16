import pandas as pd

from app.database.repository import (
    insert_optimization_run,
    record_human_decision,
    upsert_listing_records,
)
from app.export.catalogue_export import build_export_rows, export_catalogue
from app.ingestion.product_master import MeeshoListingRecord


def _seed(conn):
    upsert_listing_records(
        conn,
        [
            MeeshoListingRecord(
                seller_sku="SKU-A",
                seo_title="wipes",
                description="old description",
                category_1="Face Wipes",
            )
        ],
    )
    insert_optimization_run(
        conn,
        {
            "seller_sku": "SKU-A",
            "audit_score": 55,
            "audit_issues": ["Title too generic"],
            "generated_title": "Santerra Aloe Vera Wipes Pack of 2",
            "generated_highlights": ["Gentle on skin", "Travel friendly"],
            "generated_description": "Refreshing wipes for daily use.",
            "generated_keywords": ["wet wipes", "aloe vera"],
            "fact_check_passed": True,
            "blocked_claims": [],
            "critic_overall": 92,
            "critic_scores": {"seo": 90, "readability": 92, "completeness": 91, "brand_consistency": 95},
            "approval_status": "APPROVED",
        },
    )


def test_build_export_rows_flattens_lists_for_spreadsheet(pg_conn):
    _seed(pg_conn)
    rows = build_export_rows(pg_conn)

    assert len(rows) == 1
    row = rows[0]
    assert row["seller_sku"] == "SKU-A"
    assert row["original_title"] == "wipes"
    assert row["generated_title"] == "Santerra Aloe Vera Wipes Pack of 2"
    assert row["generated_highlights"] == "Gentle on skin | Travel friendly"
    assert row["generated_keywords"] == "wet wipes, aloe vera"
    assert row["approval_status"] == "APPROVED"
    assert row["fact_check_passed"] is True


def test_build_export_rows_only_includes_latest_run_per_sku(pg_conn):
    _seed(pg_conn)
    # a second, later run for the same SKU
    insert_optimization_run(
        pg_conn,
        {
            "seller_sku": "SKU-A",
            "audit_score": 70,
            "audit_issues": [],
            "generated_title": "Santerra Aloe Vera Wipes Pack of 2 (v2)",
            "generated_highlights": [],
            "generated_description": "",
            "generated_keywords": [],
            "fact_check_passed": True,
            "blocked_claims": [],
            "critic_overall": 95,
            "critic_scores": {"seo": 95, "readability": 95, "completeness": 95, "brand_consistency": 95},
            "approval_status": "APPROVED",
        },
    )
    rows = build_export_rows(pg_conn)

    assert len(rows) == 1
    assert rows[0]["generated_title"] == "Santerra Aloe Vera Wipes Pack of 2 (v2)"


def test_export_catalogue_filters_by_effective_status(pg_conn, tmp_path):
    _seed(pg_conn)
    n_approved = export_catalogue(pg_conn, tmp_path / "out.xlsx", effective_status="APPROVED")
    n_rejected = export_catalogue(pg_conn, tmp_path / "out2.xlsx", effective_status="REJECTED")

    assert n_approved == 1
    assert n_rejected == 0


def test_export_reflects_human_override_of_needs_review(pg_conn):
    upsert_listing_records(
        pg_conn,
        [MeeshoListingRecord(seller_sku="SKU-B", seo_title="wipes", category_1="Wipes")],
    )
    run_id = insert_optimization_run(
        pg_conn,
        {
            "seller_sku": "SKU-B",
            "audit_score": 60,
            "audit_issues": [],
            "generated_title": "Santerra Wipes",
            "generated_highlights": [],
            "generated_description": "",
            "generated_keywords": [],
            "fact_check_passed": True,
            "blocked_claims": [],
            "critic_overall": 80,
            "critic_scores": {"seo": 80, "readability": 80, "completeness": 80, "brand_consistency": 80},
            "approval_status": "NEEDS_REVIEW",
        },
    )

    rows_before = build_export_rows(pg_conn, effective_status="APPROVED")
    assert rows_before == []

    record_human_decision(pg_conn, run_id, "APPROVED")
    rows_after = build_export_rows(pg_conn, effective_status="APPROVED")

    assert len(rows_after) == 1
    assert rows_after[0]["approval_status"] == "NEEDS_REVIEW"
    assert rows_after[0]["human_decision"] == "APPROVED"
    assert rows_after[0]["effective_status"] == "APPROVED"


def test_export_catalogue_writes_readable_xlsx(pg_conn, tmp_path):
    output = tmp_path / "catalogue.xlsx"
    _seed(pg_conn)
    export_catalogue(pg_conn, output)

    df = pd.read_excel(output)
    assert list(df["seller_sku"]) == ["SKU-A"]
    assert df.loc[0, "generated_title"] == "Santerra Aloe Vera Wipes Pack of 2"


def test_export_catalogue_writes_csv_when_extension_is_csv(pg_conn, tmp_path):
    output = tmp_path / "catalogue.csv"
    _seed(pg_conn)
    export_catalogue(pg_conn, output)

    df = pd.read_csv(output)
    assert list(df["seller_sku"]) == ["SKU-A"]
