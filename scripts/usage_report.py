"""CLI: report LLM token usage, estimated cost, and latency logged by the
pipeline (llm_call_log), aggregated by agent / model / prompt version so a
prompt or model change is visible as a cost/latency delta, not just a
vibe. See docs/evaluation.md.

Usage:
    python scripts/usage_report.py
    python scripts/usage_report.py --seller-sku SOME-SKU
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.database.repository import get_usage_summary, list_llm_calls


def _print_per_sku(conn, seller_sku: str) -> None:
    calls = list_llm_calls(conn, seller_sku=seller_sku)
    if not calls:
        print(f"No logged LLM calls for {seller_sku} (it may predate usage logging).")
        return

    total_cost = sum(c["estimated_cost_usd"] or 0 for c in calls)
    total_tokens = sum(c["total_tokens"] or 0 for c in calls)
    print(f"{seller_sku}: {len(calls)} call(s), {total_tokens} tokens, ${total_cost:.6f} estimated\n")
    for c in calls:
        print(
            f"  [{c['agent']:8s}] {c['model']:26s} {c['prompt_version']:14s} "
            f"{c['total_tokens'] or 0:>6} tok  {c['latency_ms'] or 0:>7.1f} ms  "
            f"${c['estimated_cost_usd'] or 0:.6f}"
        )


def _print_summary(conn) -> None:
    summary = get_usage_summary(conn)
    if not summary:
        print("No LLM calls logged yet -- run scripts/run_pipeline.py first.")
        return

    print(
        f"{'agent':10s} {'model':26s} {'prompt_ver':12s} {'calls':>6s} "
        f"{'tokens':>9s} {'avg ms':>8s} {'est. cost':>11s}"
    )
    print("-" * 90)
    total_cost = 0.0
    total_tokens = 0
    for row in summary:
        total_cost += row["estimated_cost_usd"] or 0
        total_tokens += row["total_tokens"] or 0
        print(
            f"{row['agent']:10s} {row['model']:26s} {row['prompt_version']:12s} "
            f"{row['calls']:>6} {row['total_tokens'] or 0:>9} "
            f"{row['avg_latency_ms'] or 0:>8.1f} ${row['estimated_cost_usd'] or 0:>10.6f}"
        )
    print("-" * 90)
    print(f"{'TOTAL':10s} {'':26s} {'':12s} {'':>6s} {total_tokens:>9} {'':>8s} ${total_cost:>10.6f}")
    print(
        "\nNote: cost is estimated from a hard-coded per-model rate table "
        "(agents/telemetry.py) that can drift from Groq's actual pricing -- "
        "treat it as directional, not a bill."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seller-sku")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    with get_db(args.database_url) as conn:
        if args.seller_sku:
            _print_per_sku(conn, args.seller_sku)
        else:
            _print_summary(conn)


if __name__ == "__main__":
    main()
