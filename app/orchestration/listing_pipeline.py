"""Ties Stages 1-4 together: pull a listing from the product master DB,
ground generation in retrieved brand context, run it through
audit -> generate -> fact-validate -> critique, apply the deterministic
approval policy, and persist the run.

Also logs one agents.telemetry.CallMetrics per LLM call made along the way
(tokens, latency, estimated cost) to llm_call_log, and stamps the run with
which prompt version and model produced it -- both needed to run an
ablation or a cost/latency report after the fact. See docs/evaluation.md.
"""

from __future__ import annotations

import psycopg

from agents.audit_agent import PROMPT_VERSION as AUDIT_PROMPT_VERSION, audit_listing
from agents.content_agent import PROMPT_VERSION as CONTENT_PROMPT_VERSION, generate_listing
from agents.critic_agent import PROMPT_VERSION as CRITIC_PROMPT_VERSION, critique_listing
from agents.fact_validator import validate_claims
from agents.llm_client import CRITIC_MODEL, MODEL
from agents.telemetry import CallMetrics
from app.database.repository import get_listing, insert_llm_call_log, insert_optimization_run
from app.orchestration.models import PipelineResult
from app.orchestration.policy import decide_approval_status
from app.rag.retriever import KnowledgeBaseRetriever


def run_pipeline(
    conn: psycopg.Connection,
    seller_sku: str,
    retriever: KnowledgeBaseRetriever | None = None,
) -> PipelineResult:
    listing = get_listing(conn, seller_sku)
    if listing is None:
        raise ValueError(f"No listing found for seller_sku={seller_sku!r}")

    retriever = retriever or KnowledgeBaseRetriever()
    query = " ".join(
        filter(None, [listing["seo_title"], listing["category_1"], listing["keywords"]])
    )
    context_chunks = retriever.retrieve(query, top_k=3)
    brand_context = [sc.chunk.text for sc in context_chunks]

    call_metrics: list[CallMetrics] = []

    audit = audit_listing(
        seller_sku=seller_sku,
        seo_title=listing["seo_title"],
        description=listing["description"],
        keywords=listing["keywords"],
        category=listing["category_1"],
        metrics=call_metrics,
    )

    generated = generate_listing(
        seller_sku=seller_sku,
        current_title=listing["seo_title"],
        current_description=listing["description"],
        current_keywords=listing["keywords"],
        category=listing["category_1"],
        audit=audit,
        brand_context=brand_context,
        metrics=call_metrics,
    )

    fact_result = validate_claims(generated)  # deterministic -- no LLM call, no metrics
    critic = critique_listing(generated, metrics=call_metrics)
    approval_status = decide_approval_status(fact_result, critic)

    run_id = insert_optimization_run(
        conn,
        {
            "seller_sku": seller_sku,
            "audit_score": audit.score,
            "audit_issues": audit.issues,
            "generated_title": generated.title,
            "generated_highlights": generated.highlights,
            "generated_description": generated.description,
            "generated_keywords": generated.keywords,
            "fact_check_passed": fact_result.passed,
            "blocked_claims": fact_result.blocked_claims,
            "critic_overall": critic.overall,
            "critic_scores": critic.scores.model_dump(),
            "approval_status": approval_status,
            "audit_prompt_version": AUDIT_PROMPT_VERSION,
            "content_prompt_version": CONTENT_PROMPT_VERSION,
            "critic_prompt_version": CRITIC_PROMPT_VERSION,
            "generation_model": MODEL,
            "critic_model": CRITIC_MODEL,
        },
    )
    insert_llm_call_log(conn, run_id, seller_sku, call_metrics)

    return PipelineResult(
        run_id=run_id,
        seller_sku=seller_sku,
        audit=audit,
        generated=generated,
        fact_result=fact_result,
        critic=critic,
        approval_status=approval_status,
    )
