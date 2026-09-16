"""CLI: run the listing optimization pipeline for one or more seller SKUs
already loaded into the product master DB (see scripts/load_database.py),
or for the whole catalogue with --all.

Usage:
    python scripts/run_pipeline.py SELLER_SKU [SELLER_SKU ...]
    python scripts/run_pipeline.py --all
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.database.repository import list_all_seller_skus, list_seller_skus_with_optimization
from app.orchestration.listing_pipeline import run_pipeline
from app.rag.retriever import KnowledgeBaseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seller_skus", nargs="*")
    parser.add_argument(
        "--all", action="store_true", help="run every seller_sku in the product master DB"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="skip SKUs that already have a run -- use this to resume --all after a "
        "timeout/crash partway through, without re-spending API calls on completed SKUs",
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    if not args.all and not args.seller_skus:
        parser.error("pass one or more SELLER_SKU, or --all")

    retriever = KnowledgeBaseRetriever()
    status_counts: Counter = Counter()
    errors: list[tuple[str, str]] = []

    with get_db(args.database_url) as conn:
        seller_skus = list_all_seller_skus(conn) if args.all else args.seller_skus
        if args.skip_existing:
            already_done = list_seller_skus_with_optimization(conn)
            skipped = [s for s in seller_skus if s in already_done]
            seller_skus = [s for s in seller_skus if s not in already_done]
            if skipped:
                print(f"Skipping {len(skipped)} already-completed SKU(s)\n")
        total = len(seller_skus)

        for i, seller_sku in enumerate(seller_skus, 1):
            print(f"[{i}/{total}] {seller_sku} ...")
            try:
                result = run_pipeline(conn, seller_sku, retriever=retriever)
            except Exception as e:  # one bad SKU (LLM hiccup, malformed data) shouldn't kill the batch
                print(f"  ! {type(e).__name__}: {e}")
                errors.append((seller_sku, str(e)))
                continue

            status_counts[result.approval_status] += 1
            print(f"  audit score: {result.audit.score} ({result.audit.priority})")
            print(f"  generated title: {result.generated.title}")
            fact_status = "PASSED" if result.fact_result.passed else "BLOCKED"
            claims = f" ({', '.join(result.fact_result.blocked_claims)})" if result.fact_result.blocked_claims else ""
            print(f"  fact check: {fact_status}{claims}")
            print(f"  critic overall: {result.critic.overall}")
            print(f"  approval status: {result.approval_status}  (run_id={result.run_id})")
            print()

    print("=" * 40)
    print(f"Completed {sum(status_counts.values())}/{len(seller_skus)}")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}")
    if errors:
        print(f"  ERRORS: {len(errors)}")
        for sku, msg in errors:
            print(f"    {sku}: {msg}")


if __name__ == "__main__":
    main()
