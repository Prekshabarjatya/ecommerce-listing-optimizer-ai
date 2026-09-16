"""CLI: work the human-review queue -- optimization runs the pipeline
scored below the auto-approval threshold (NEEDS_REVIEW). A blocked-claim
(REJECTED) run isn't listed here: that gate isn't something a human review
step should rubber-stamp past, it needs regenerated content instead.

Usage:
    python scripts/review_queue.py                    # list the queue
    python scripts/review_queue.py --show RUN_ID       # full detail for one run
    python scripts/review_queue.py --approve RUN_ID
    python scripts/review_queue.py --reject RUN_ID
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.database.repository import (
    get_optimization_by_id,
    list_optimizations,
    record_human_decision,
)


def _print_queue(conn) -> None:
    pending = [
        r for r in list_optimizations(conn, approval_status="NEEDS_REVIEW")
        if r["human_decision"] is None
    ]
    if not pending:
        print("Review queue is empty.")
        return

    print(f"{len(pending)} run(s) awaiting review:\n")
    for r in pending:
        print(f"[{r['id']}] {r['seller_sku']}  critic={r['critic_overall']}  audit={r['audit_score']}")
        print(f"    title: {r['generated_title']}")
        if r["audit_issues"]:
            print(f"    audit issues: {'; '.join(r['audit_issues'])}")
        print()


def _print_detail(conn, run_id: int) -> None:
    run = get_optimization_by_id(conn, run_id)
    if run is None:
        print(f"No run with id={run_id}")
        return

    print(f"run {run['id']} -- {run['seller_sku']}  ({run['approval_status']})")
    print(f"  title:       {run['generated_title']}")
    print(f"  highlights:  {'; '.join(run['generated_highlights'])}")
    print(f"  description: {run['generated_description']}")
    print(f"  keywords:    {', '.join(run['generated_keywords'])}")
    print(f"  audit score: {run['audit_score']}  issues: {'; '.join(run['audit_issues']) or '(none)'}")
    print(f"  critic overall: {run['critic_overall']}  scores: {run['critic_scores']}")
    print(f"  fact check: {'PASSED' if run['fact_check_passed'] else 'BLOCKED'}")
    print(f"  human decision: {run['human_decision'] or '(pending)'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", type=int, metavar="RUN_ID")
    parser.add_argument("--approve", type=int, metavar="RUN_ID")
    parser.add_argument("--reject", type=int, metavar="RUN_ID")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    with get_db(args.database_url) as conn:
        if args.approve is not None:
            record_human_decision(conn, args.approve, "APPROVED")
            print(f"run {args.approve} marked APPROVED")
        elif args.reject is not None:
            record_human_decision(conn, args.reject, "REJECTED")
            print(f"run {args.reject} marked REJECTED")
        elif args.show is not None:
            _print_detail(conn, args.show)
        else:
            _print_queue(conn)


if __name__ == "__main__":
    main()
