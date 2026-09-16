from unittest.mock import patch

from agents.models import AuditResult, CriticResult, CriticScores, GeneratedListing
from app.database.repository import get_latest_optimization, upsert_listing_records
from app.ingestion.product_master import MeeshoListingRecord
from app.orchestration.listing_pipeline import run_pipeline
from app.rag.loader import Chunk
from app.rag.retriever import KnowledgeBaseRetriever


def _seed_listing(conn):
    record = MeeshoListingRecord(
        seller_sku="TEST-SKU-1",
        seo_title="wipes",
        description=None,
        keywords=None,
        category_1="Beauty & Personal Care > Face Wipes",
    )
    upsert_listing_records(conn, [record])


def _empty_retriever() -> KnowledgeBaseRetriever:
    return KnowledgeBaseRetriever(chunks=[Chunk(source_file="x.md", heading="x", text="brand voice")])


def test_pipeline_approves_when_fact_check_passes_and_score_is_high(pg_conn):
    audit = AuditResult(score=50, issues=["Title too generic"], priority="HIGH")
    generated = GeneratedListing(
        title="Santerra Aloe Vera Wipes Pack of 2",
        highlights=["Gentle on skin"],
        description="Refreshing wipes for daily use.",
        keywords=["wet wipes", "aloe vera"],
    )
    critic = CriticResult(
        scores=CriticScores(seo=92, readability=90, completeness=91, brand_consistency=95),
        overall=93,
        notes=["Strong coverage"],
    )

    _seed_listing(pg_conn)
    with (
        patch("app.orchestration.listing_pipeline.audit_listing", return_value=audit),
        patch("app.orchestration.listing_pipeline.generate_listing", return_value=generated),
        patch("app.orchestration.listing_pipeline.critique_listing", return_value=critic),
    ):
        result = run_pipeline(pg_conn, "TEST-SKU-1", retriever=_empty_retriever())

    assert result.approval_status == "APPROVED"
    assert result.run_id is not None

    stored = get_latest_optimization(pg_conn, "TEST-SKU-1")
    assert stored["approval_status"] == "APPROVED"
    assert stored["generated_title"] == "Santerra Aloe Vera Wipes Pack of 2"
    assert stored["critic_overall"] == 93


def test_pipeline_rejects_regardless_of_critic_score_when_fact_check_fails(pg_conn):
    audit = AuditResult(score=50, issues=[], priority="MEDIUM")
    generated = GeneratedListing(
        title="Santerra Wipes",
        highlights=["Fully biodegradable"],
        description="Our wipes are fully biodegradable.",
        keywords=["wet wipes"],
    )
    critic = CriticResult(
        scores=CriticScores(seo=99, readability=99, completeness=99, brand_consistency=99),
        overall=99,
        notes=[],
    )

    _seed_listing(pg_conn)
    with (
        patch("app.orchestration.listing_pipeline.audit_listing", return_value=audit),
        patch("app.orchestration.listing_pipeline.generate_listing", return_value=generated),
        patch("app.orchestration.listing_pipeline.critique_listing", return_value=critic),
    ):
        result = run_pipeline(pg_conn, "TEST-SKU-1", retriever=_empty_retriever())

    assert result.approval_status == "REJECTED"
    assert "fully biodegradable" in result.fact_result.blocked_claims


def test_pipeline_needs_review_when_score_below_threshold(pg_conn):
    audit = AuditResult(score=60, issues=[], priority="MEDIUM")
    generated = GeneratedListing(
        title="Santerra Wipes",
        highlights=["Gentle"],
        description="Wipes for daily use.",
        keywords=["wipes"],
    )
    critic = CriticResult(
        scores=CriticScores(seo=80, readability=80, completeness=80, brand_consistency=80),
        overall=80,
        notes=["Could be stronger"],
    )

    _seed_listing(pg_conn)
    with (
        patch("app.orchestration.listing_pipeline.audit_listing", return_value=audit),
        patch("app.orchestration.listing_pipeline.generate_listing", return_value=generated),
        patch("app.orchestration.listing_pipeline.critique_listing", return_value=critic),
    ):
        result = run_pipeline(pg_conn, "TEST-SKU-1", retriever=_empty_retriever())

    assert result.approval_status == "NEEDS_REVIEW"


def test_pipeline_raises_for_unknown_seller_sku(pg_conn):
    try:
        run_pipeline(pg_conn, "DOES-NOT-EXIST", retriever=_empty_retriever())
        assert False, "expected ValueError"
    except ValueError:
        pass
