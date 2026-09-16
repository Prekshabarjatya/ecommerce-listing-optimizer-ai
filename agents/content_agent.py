"""Generates an optimized listing (title, highlights, description, keywords)
grounded in retrieved brand-knowledge context, so voice and claims stay
consistent with what Santerra actually says about itself rather than
whatever the model would otherwise invent. See architecture: Content
Generation Agent.
"""

from __future__ import annotations

import json

from agents.llm_client import MODEL, client
from agents.models import AuditResult, GeneratedListing
from agents.telemetry import CallMetrics, timed_chat_completion

# Bumped whenever SYSTEM_PROMPT changes meaningfully. Stored on every run
# (listing_optimizations.content_prompt_version) so an ablation can compare
# critic scores / human agreement across prompt versions -- see
# docs/evaluation.md and scripts/run_eval.py.
PROMPT_VERSION = "content-v1"

SYSTEM_PROMPT = """You write Meesho marketplace listings for Santerra Hygiene, an FMCG
hygiene brand. Use ONLY the brand context provided — do not invent facts, certifications,
or claims not present in it or in the current listing.

Follow Santerra's voice: warm, helpful, educational, reassuring, transparent, positive,
trustworthy. Avoid: aggressive, fear-driven, overly technical, luxury-exclusive, clinical
language. Do not make medical claims, disease-prevention claims, or unverified
sustainability claims (e.g. "fully biodegradable", "carbon neutral", "100% sustainable")
unless they appear verbatim as approved in the brand context.

Return ONLY a JSON object with exactly these keys:
title: string, <= 100 characters, includes pack size/quantity if known
highlights: array of 3-5 short benefit-led bullet strings
description: string, 2-4 sentences, benefit-led, ends with a light call to action
keywords: array of 5-10 relevant search keywords"""


def generate_listing(
    seller_sku: str,
    current_title: str | None,
    current_description: str | None,
    current_keywords: str | None,
    category: str | None,
    audit: AuditResult,
    brand_context: list[str],
    metrics: list[CallMetrics] | None = None,
) -> GeneratedListing:
    context_block = "\n\n".join(brand_context) if brand_context else "(no brand context retrieved)"

    user_content = (
        f"CURRENT LISTING\n"
        f"Seller SKU: {seller_sku}\n"
        f"Title: {current_title or '(missing)'}\n"
        f"Description: {current_description or '(missing)'}\n"
        f"Keywords: {current_keywords or '(missing)'}\n"
        f"Category: {category or '(missing)'}\n\n"
        f"AUDIT ISSUES TO FIX\n"
        + ("\n".join(f"- {issue}" for issue in audit.issues) or "(none flagged)")
        + f"\n\nBRAND CONTEXT (ground your claims in this)\n{context_block}"
    )

    response, call_metrics = timed_chat_completion(
        client,
        agent="content",
        prompt_version=PROMPT_VERSION,
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    if metrics is not None:
        metrics.append(call_metrics)

    data = json.loads(response.choices[0].message.content)
    return GeneratedListing(**data)
