import pytest

from app.database.repository import (
    get_optimization_by_id,
    insert_optimization_run,
    list_all_seller_skus,
    list_optimizations,
    list_seller_skus_with_optimization,
    record_human_decision,
    upsert_listing_records,
)
from app.ingestion.product_master import MeeshoListingRecord


def _seed_run(conn, seller_sku="SKU-A", approval_status="NEEDS_REVIEW") -> int:
    upsert_listing_records(
        conn, [MeeshoListingRecord(seller_sku=seller_sku, seo_title="wipes", category_1="Wipes")]
    )
    return insert_optimization_run(
        conn,
        {
            "seller_sku": seller_sku,
            "audit_score": 60,
            "audit_issues": [],
            "generated_title": "Santerra Wipes",
            "generated_highlights": [],
            "generated_description": "",
            "generated_keywords": [],
            "fact_check_passed": approval_status != "REJECTED",
            "blocked_claims": ["fully biodegradable"] if approval_status == "REJECTED" else [],
            "critic_overall": 80,
            "critic_scores": {"seo": 80, "readability": 80, "completeness": 80, "brand_consistency": 80},
            "approval_status": approval_status,
        },
    )


def test_new_run_has_no_human_decision_and_effective_status_matches_pipeline(pg_conn):
    run_id = _seed_run(pg_conn)
    run = get_optimization_by_id(pg_conn, run_id)

    assert run["human_decision"] is None
    assert run["human_reviewed_at"] is None
    assert run["effective_status"] == "NEEDS_REVIEW"


def test_record_human_decision_approves_a_needs_review_run(pg_conn):
    run_id = _seed_run(pg_conn)
    record_human_decision(pg_conn, run_id, "APPROVED")
    run = get_optimization_by_id(pg_conn, run_id)

    assert run["human_decision"] == "APPROVED"
    assert run["human_reviewed_at"] is not None
    assert run["effective_status"] == "APPROVED"


def test_record_human_decision_rejects_invalid_decision_value(pg_conn):
    run_id = _seed_run(pg_conn)
    with pytest.raises(ValueError):
        record_human_decision(pg_conn, run_id, "MAYBE")


def test_record_human_decision_refuses_to_override_a_fact_check_rejection(pg_conn):
    run_id = _seed_run(pg_conn, approval_status="REJECTED")
    with pytest.raises(ValueError):
        record_human_decision(pg_conn, run_id, "APPROVED")


def test_record_human_decision_refuses_unknown_run_id(pg_conn):
    with pytest.raises(ValueError):
        record_human_decision(pg_conn, 9999, "APPROVED")


def test_list_all_seller_skus_returns_every_loaded_sku(pg_conn):
    upsert_listing_records(
        pg_conn,
        [
            MeeshoListingRecord(seller_sku="SKU-B", seo_title="a"),
            MeeshoListingRecord(seller_sku="SKU-A", seo_title="b"),
        ],
    )
    skus = list_all_seller_skus(pg_conn)

    assert skus == ["SKU-A", "SKU-B"]


def test_list_seller_skus_with_optimization_only_includes_skus_that_have_a_run(pg_conn):
    upsert_listing_records(
        pg_conn,
        [
            MeeshoListingRecord(seller_sku="SKU-A", seo_title="a"),
            MeeshoListingRecord(seller_sku="SKU-B", seo_title="b"),
        ],
    )
    _seed_run(pg_conn, seller_sku="SKU-A")

    done = list_seller_skus_with_optimization(pg_conn)

    assert done == {"SKU-A"}


def test_list_optimizations_excludes_human_reviewed_runs_from_pending_queue(pg_conn):
    run_id_1 = _seed_run(pg_conn, seller_sku="SKU-A")
    _seed_run(pg_conn, seller_sku="SKU-B")
    record_human_decision(pg_conn, run_id_1, "REJECTED")

    pending = [
        r for r in list_optimizations(pg_conn, approval_status="NEEDS_REVIEW")
        if r["human_decision"] is None
    ]

    assert len(pending) == 1
    assert pending[0]["seller_sku"] == "SKU-B"
