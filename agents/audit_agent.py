"""Scores a current Meesho listing and flags what's weak about it, ahead of
regenerating it. See architecture: Listing Audit Agent.
"""

from __future__ import annotations

import json

from agents.llm_client import MODEL, client
from agents.models import AuditResult
from agents.telemetry import CallMetrics, timed_chat_completion

# Bumped whenever SYSTEM_PROMPT changes meaningfully. Stored on every run
# (listing_optimizations.audit_prompt_version) so an ablation can group
# past runs by which prompt actually produced them -- see docs/evaluation.md.
PROMPT_VERSION = "audit-v1"

SYSTEM_PROMPT = """You are a Meesho marketplace listing auditor for Santerra Hygiene, an FMCG
hygiene brand.

Score the given listing on SEO title quality, keyword coverage, description
completeness, and category fit. Return ONLY a JSON object with exactly these keys:

score: integer 0-100, overall listing quality
issues: array of short strings, each a specific problem (e.g. "Title omits pack size",
  "No benefit-led language", "Missing category-relevant keywords"). Empty array if none.
priority: one of "LOW", "MEDIUM", "HIGH" — how urgently this listing needs rework

Be specific and grounded in the listing content given — do not invent issues that
aren't evidenced by the text."""


def audit_listing(
    seller_sku: str,
    seo_title: str | None,
    description: str | None,
    keywords: str | None,
    category: str | None,
    metrics: list[CallMetrics] | None = None,
) -> AuditResult:
    listing_text = (
        f"Seller SKU: {seller_sku}\n"
        f"Title: {seo_title or '(missing)'}\n"
        f"Description: {description or '(missing)'}\n"
        f"Keywords: {keywords or '(missing)'}\n"
        f"Category: {category or '(missing)'}"
    )

    response, call_metrics = timed_chat_completion(
        client,
        agent="audit",
        prompt_version=PROMPT_VERSION,
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": listing_text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    if metrics is not None:
        metrics.append(call_metrics)

    data = json.loads(response.choices[0].message.content)
    return AuditResult(**data)
