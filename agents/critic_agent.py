"""Scores a generated listing holistically before it's allowed into the
approval queue. See architecture: Critic Agent. Fact-check failures are
handled separately and deterministically by fact_validator — this agent
only judges the qualities an LLM is actually suited to judge (SEO framing,
readability, completeness, brand-voice fit).

Runs on CRITIC_MODEL rather than MODEL. Left unconfigured, that's the same
model content_agent used to write the listing -- which means this "critic"
can share the generator's blind spots instead of independently catching
them. Setting GROQ_CRITIC_MODEL to a different model is a real (if partial)
mitigation for that self-correlation bias; see docs/evaluation.md for the
full discussion and for how to check whether it actually helps (compare
critic_prompt_version / critic_model against human-labeled agreement via
scripts/run_eval.py).
"""

from __future__ import annotations

import json

from agents.llm_client import CRITIC_MODEL, client
from agents.models import CriticResult, GeneratedListing
from agents.telemetry import CallMetrics, timed_chat_completion

# Bumped whenever SYSTEM_PROMPT changes meaningfully. Stored on every run
# (listing_optimizations.critic_prompt_version) -- see docs/evaluation.md.
PROMPT_VERSION = "critic-v1"

SYSTEM_PROMPT = """You are a quality critic for Santerra Hygiene Meesho listings. Score the
generated listing below on four dimensions, each 0-100:

seo: keyword coverage, title structure, search intent match
readability: clarity, natural language, no keyword stuffing
completeness: covers pack size/quantity, category fit, benefits, use case
brand_consistency: matches Santerra's warm/helpful/educational/transparent voice,
  avoids aggressive or clinical language

Return ONLY a JSON object with exactly these keys:
scores: object with integer keys seo, readability, completeness, brand_consistency
overall: integer 0-100, your overall judgment (not required to be a plain average)
notes: array of short strings explaining the scores, especially any deductions"""


def critique_listing(
    generated: GeneratedListing,
    metrics: list[CallMetrics] | None = None,
) -> CriticResult:
    listing_text = (
        f"Title: {generated.title}\n"
        f"Highlights: {'; '.join(generated.highlights)}\n"
        f"Description: {generated.description}\n"
        f"Keywords: {', '.join(generated.keywords)}"
    )

    response, call_metrics = timed_chat_completion(
        client,
        agent="critic",
        prompt_version=PROMPT_VERSION,
        model=CRITIC_MODEL,
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
    return CriticResult(**data)
