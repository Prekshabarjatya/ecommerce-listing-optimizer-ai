"""Shared LLM client, matching the sibling ai-logistics-workforce project's
convention: an OpenAI-compatible client pointed at Groq, model + key read
from environment variables (see .env.example — copy it to .env and fill in
your own GROQ_API_KEY).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_api_key = os.environ.get("GROQ_API_KEY")
if not _api_key:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Copy .env.example to .env and fill in your key."
    )

client = OpenAI(
    api_key=_api_key,
    base_url="https://api.groq.com/openai/v1",
    # Groq occasionally stalls or rate-limits under a long sequential batch
    # (scripts/run_pipeline.py --all makes ~3 calls per SKU). A shorter
    # per-request timeout plus the SDK's built-in retry (exponential
    # backoff on timeouts/connection errors/429/5xx) recovers from that
    # instead of hanging on the default 10-minute timeout with no retry.
    timeout=30.0,
    max_retries=4,
)
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# The critic agent can optionally run on a different model than the
# generator (content_agent). Left unset, it defaults to MODEL, same as
# before. Set GROQ_CRITIC_MODEL to something else to reduce a real risk:
# the same model grading its own output shares that model's blind spots
# with the thing it's judging, so a critic score computed this way is not
# independent evidence of quality -- it's correlated with the generator in
# ways a truly independent judge wouldn't be. See docs/evaluation.md.
CRITIC_MODEL = os.environ.get("GROQ_CRITIC_MODEL", MODEL)
