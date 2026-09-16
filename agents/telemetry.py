"""Lightweight LLM call instrumentation: tokens, latency, and an approximate
cost estimate, recorded per call so the pipeline's actual spend and speed can
be reported instead of assumed.

Deliberately dependency-free (stdlib only) and defensive about malformed or
mocked `usage` objects -- tests that mock the Groq client don't need to also
mock token accounting for this to stay a no-op there. See
scripts/usage_report.py for how this gets surfaced, and docs/evaluation.md
for the ablation/self-correlation-bias context this exists to support.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Approximate Groq per-million-token pricing (input, output) in USD, as of
# this writing. Groq's pricing changes; treat this as a ballpark for the
# usage report, not a billing source of truth. An unknown model falls back
# to (0.0, 0.0) rather than raising, so instrumentation never blocks a run.
PRICING_PER_MILLION_TOKENS_USD: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}


@dataclass
class CallMetrics:
    agent: str
    model: str
    prompt_version: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_rate, out_rate = PRICING_PER_MILLION_TOKENS_USD.get(model, (0.0, 0.0))
    return (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000


def _safe_int(value, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def timed_chat_completion(client, *, agent: str, prompt_version: str, **create_kwargs):
    """Calls client.chat.completions.create(**create_kwargs), timing it and
    extracting token usage. Returns (response, CallMetrics).

    Never raises on missing or mocked usage data -- a unit test that patches
    the client with a bare MagicMock still gets a CallMetrics back (with
    zeroed token counts), it just isn't meaningful there. Only real API
    responses produce real numbers.
    """
    model = create_kwargs.get("model", "unknown")
    start = time.perf_counter()
    response = client.chat.completions.create(**create_kwargs)
    latency_ms = (time.perf_counter() - start) * 1000

    usage = getattr(response, "usage", None)
    prompt_tokens = _safe_int(getattr(usage, "prompt_tokens", 0) if usage is not None else 0)
    completion_tokens = _safe_int(getattr(usage, "completion_tokens", 0) if usage is not None else 0)
    total_tokens = _safe_int(getattr(usage, "total_tokens", 0) if usage is not None else 0)
    if total_tokens == 0 and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens

    metrics = CallMetrics(
        agent=agent,
        model=model,
        prompt_version=prompt_version,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=round(latency_ms, 1),
        estimated_cost_usd=round(_estimate_cost_usd(model, prompt_tokens, completion_tokens), 6),
    )
    return response, metrics
