"""Tests for app/api.py -- the HTTP layer over Stages 1-8.

The `pg_conn` fixture (tests/conftest.py) TRUNCATEs the test Postgres
database before each test; api_module.DATABASE_URL is monkeypatched to
point at that same database, so a test seeds data via `pg_conn` and then
hits the API, which opens its own connection to the same DSN per request
(app/api.py never reuses a connection across requests -- see its module
docstring). No LLM calls are made here -- /pipeline/run/* isn't exercised
beyond the 404 path (mocked-agent coverage lives in
tests/test_pipeline.py); this file covers the DB-backed routes (catalogue
listing, review queue, export, usage) and error handling.
"""

from __future__ import annotations

import app.api as api_module
from app.database.repository import (
    insert_llm_call_log,
    insert_optimization_run,
    upsert_listing_records,
)
from app.ingestion.product_master import MeeshoListingRecord
from fastapi.testclient import TestClient
from tests.conftest import TEST_DATABASE_URL


def _seed_run(conn, seller_sku="SKU-A", approval_status="NEEDS_REVIEW", human_decision=None):
    upsert_listing_records(
        conn,
        [MeeshoListingRecord(seller_sku=seller_sku, seo_title="wipes", category_1="Wipes")],
    )
    run_id = insert_optimization_run(
        conn,
        {
            "seller_sku": seller_sku,
            "audit_score": 60,
            "audit_issues": [],
            "generated_title": "Santerra Wipes",
            "generated_highlights": ["gentle", "biodegradable pack"],
            "generated_description": "desc",
            "generated_keywords": ["wipes", "santerra"],
            "fact_check_passed": approval_status != "REJECTED",
            "blocked_claims": ["fully biodegradable"] if approval_status == "REJECTED" else [],
            "critic_overall": 80,
            "critic_scores": {
                "seo": 80, "readability": 80, "completeness": 80, "brand_consistency": 80,
            },
            "approval_status": approval_status,
        },
    )
    if human_decision:
        conn.execute(
            "UPDATE listing_optimizations SET human_decision = %s WHERE id = %s",
            (human_decision, run_id),
        )
        conn.commit()
    return run_id


def _client(monkeypatch):
    monkeypatch.setattr(api_module, "DATABASE_URL", TEST_DATABASE_URL)
    return TestClient(api_module.app)


def test_health():
    client = TestClient(api_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_skus_reflects_effective_status(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    _seed_run(pg_conn, seller_sku="SKU-A", approval_status="NEEDS_REVIEW")
    upsert_listing_records(
        pg_conn, [MeeshoListingRecord(seller_sku="SKU-B", seo_title="mop", category_1="Cleaning")]
    )

    resp = client.get("/skus")
    assert resp.status_code == 200
    by_sku = {row["seller_sku"]: row for row in resp.json()}
    assert by_sku["SKU-A"]["has_run"] is True
    assert by_sku["SKU-A"]["effective_status"] == "NEEDS_REVIEW"
    assert by_sku["SKU-B"]["has_run"] is False
    assert by_sku["SKU-B"]["effective_status"] is None


def test_review_queue_excludes_already_reviewed_and_rejected(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    pending_id = _seed_run(pg_conn, seller_sku="SKU-PENDING", approval_status="NEEDS_REVIEW")
    _seed_run(pg_conn, seller_sku="SKU-DECIDED", approval_status="NEEDS_REVIEW", human_decision="APPROVED")
    _seed_run(pg_conn, seller_sku="SKU-REJECTED", approval_status="REJECTED")

    resp = client.get("/review/queue")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {pending_id}


def test_review_detail_404_for_missing_run(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/review/999999")
    assert resp.status_code == 404


def test_approve_run_then_reflected_in_detail_and_skus(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    run_id = _seed_run(pg_conn, seller_sku="SKU-A", approval_status="NEEDS_REVIEW")

    resp = client.post(f"/review/{run_id}/approve")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": run_id, "human_decision": "APPROVED"}

    detail = client.get(f"/review/{run_id}").json()
    assert detail["human_decision"] == "APPROVED"
    assert detail["effective_status"] == "APPROVED"

    skus = {row["seller_sku"]: row for row in client.get("/skus").json()}
    assert skus["SKU-A"]["effective_status"] == "APPROVED"


def test_approve_rejects_a_fact_check_failed_run(pg_conn, monkeypatch):
    """A REJECTED (blocked-claim) run can't be rubber-stamped past via the
    review endpoint -- same rule as scripts/review_queue.py /
    record_human_decision."""
    client = _client(monkeypatch)
    run_id = _seed_run(pg_conn, seller_sku="SKU-A", approval_status="REJECTED")

    resp = client.post(f"/review/{run_id}/approve")
    assert resp.status_code == 400


def test_export_returns_a_file(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    _seed_run(pg_conn, seller_sku="SKU-A", approval_status="APPROVED")

    resp = client.get("/export?fmt=csv")
    assert resp.status_code == 200
    assert "SKU-A" in resp.text


def test_meesho_upload_export_returns_a_file(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    _seed_run(pg_conn, seller_sku="SKU-A", approval_status="APPROVED")

    resp = client.get("/export/meesho-upload?fmt=csv")
    assert resp.status_code == 200
    assert "SKU-A" in resp.text
    assert "Seller SKU" in resp.text


def test_usage_summary_reflects_logged_calls(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    run_id = _seed_run(pg_conn, seller_sku="SKU-A")
    from agents.telemetry import CallMetrics

    insert_llm_call_log(
        pg_conn,
        run_id,
        "SKU-A",
        [
            CallMetrics(
                agent="content", model="test-model", prompt_version="v1",
                prompt_tokens=100, completion_tokens=50, total_tokens=150,
                latency_ms=250.0, estimated_cost_usd=0.0001,
            )
        ],
    )

    resp = client.get("/usage/summary")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["agent"] == "content"
    assert rows[0]["calls"] == 1

    per_sku = client.get("/usage/SKU-A").json()
    assert len(per_sku) == 1
    assert per_sku[0]["model"] == "test-model"


def test_run_pipeline_404_for_unknown_sku(pg_conn, monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/pipeline/run/NO-SUCH-SKU")
    assert resp.status_code == 404
