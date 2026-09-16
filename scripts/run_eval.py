"""CLI: a small, fixed evaluation set for the listing pipeline -- build it,
export a human-labeling template, then compute agreement (critic vs. a
human) and error-mode analysis (no human labels needed). See
docs/evaluation.md for the methodology and what this can and can't prove.

Usage:
    python scripts/run_eval.py --build-set --n 20
        Pick (once) a fixed random sample of seller_skus from the DB,
        ensure each has an optimization run (generating one if missing),
        and write eval/human_labels_template.csv for a human to fill in.
        Re-running reuses the same eval/eval_set.csv and skips SKUs that
        already have a run, so it's cheap to re-run after adding labels.

    python scripts/run_eval.py --agreement eval/human_labels_filled.csv
        Compare a filled-in labels file's human_score column against the
        critic's own critic_overall: mean absolute error, correlation, and
        agreement at the APPROVED threshold (critic >= 90).

    python scripts/run_eval.py --error-modes
        Analyze every run already in the database -- approval-status mix,
        weakest critic dimension, most common audit issues, most common
        blocked claims. Needs no human labels; works today.
"""

from __future__ import annotations

import argparse
import os
import csv
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.database.repository import (
    get_latest_optimization,
    get_listing,
    list_all_seller_skus,
    list_optimizations,
)
from app.orchestration.listing_pipeline import run_pipeline
from app.rag.retriever import KnowledgeBaseRetriever

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"
EVAL_SET_PATH = EVAL_DIR / "eval_set.csv"
LABELS_TEMPLATE_PATH = EVAL_DIR / "human_labels_template.csv"

# Fixed seed: the eval set must be the same list of SKUs every time it's
# built fresh, or a prompt/model comparison across two --build-set runs
# would be comparing different SKUs, not different prompts.
SAMPLE_SEED = 42


def _load_or_sample_eval_set(conn, n: int) -> list[str]:
    if EVAL_SET_PATH.exists():
        with EVAL_SET_PATH.open(newline="", encoding="utf-8") as f:
            skus = [row["seller_sku"] for row in csv.DictReader(f)]
        print(f"Reusing existing eval set: {EVAL_SET_PATH} ({len(skus)} SKUs)")
        return skus

    all_skus = list_all_seller_skus(conn)
    if not all_skus:
        raise SystemExit("No seller_skus in the database yet -- run scripts/load_database.py first.")

    sample_n = min(n, len(all_skus))
    skus = sorted(random.Random(SAMPLE_SEED).sample(all_skus, sample_n))

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with EVAL_SET_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["seller_sku"])
        writer.writerows([[s] for s in skus])
    print(f"Sampled {len(skus)} SKUs (seed={SAMPLE_SEED}) -> wrote {EVAL_SET_PATH}")
    return skus


def _build_set(conn, n: int, force: bool) -> None:
    retriever = KnowledgeBaseRetriever()
    skus = _load_or_sample_eval_set(conn, n)

    rows = []
    generated_count = 0
    for sku in skus:
        run = None if force else get_latest_optimization(conn, sku)
        if run is None:
            print(f"  generating run for {sku} ...")
            result = run_pipeline(conn, sku, retriever=retriever)
            run = get_latest_optimization(conn, sku)
            generated_count += 1
        listing = get_listing(conn, sku)
        rows.append(
            {
                "run_id": run["id"],
                "seller_sku": sku,
                "original_title": (listing or {}).get("seo_title") or "",
                "generated_title": run["generated_title"] or "",
                "generated_description": run["generated_description"] or "",
                "approval_status": run["approval_status"],
                "critic_overall": run["critic_overall"],
                "human_score": "",
                "human_pass": "",
                "human_notes": "",
            }
        )

    with LABELS_TEMPLATE_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"\n{len(rows)} SKUs in eval set ({generated_count} newly generated). "
        f"Wrote {LABELS_TEMPLATE_PATH}"
    )
    print(
        "Next: open that file, fill in human_score (0-100, your own read of "
        "generated_title/generated_description) and human_pass (y/n -- would "
        "you actually ship this?) for each row, save a copy, then run:\n"
        f"  python scripts/run_eval.py --agreement {LABELS_TEMPLATE_PATH.name}"
    )


def _agreement(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"No such file: {path}")

    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    labeled = [r for r in rows if str(r.get("human_score", "")).strip() != ""]
    skipped = len(rows) - len(labeled)
    if not labeled:
        raise SystemExit(
            "No rows have human_score filled in yet -- label at least a few before "
            "computing agreement."
        )

    critic_scores = np.array([float(r["critic_overall"]) for r in labeled])
    human_scores = np.array([float(r["human_score"]) for r in labeled])

    mae = float(np.mean(np.abs(critic_scores - human_scores)))
    correlation = (
        float(np.corrcoef(critic_scores, human_scores)[0, 1]) if len(labeled) >= 2 else float("nan")
    )

    def _human_pass(r: dict) -> bool:
        raw = str(r.get("human_pass", "")).strip().lower()
        if raw in ("y", "yes", "true", "1"):
            return True
        if raw in ("n", "no", "false", "0"):
            return False
        return float(r["human_score"]) >= 80  # fallback threshold if human_pass left blank

    both_approve = both_hold = critic_over_human = critic_under_human = 0
    for r in labeled:
        critic_ok = float(r["critic_overall"]) >= 90
        human_ok = _human_pass(r)
        if critic_ok and human_ok:
            both_approve += 1
        elif not critic_ok and not human_ok:
            both_hold += 1
        elif critic_ok and not human_ok:
            critic_over_human += 1  # critic auto-approved something a human wouldn't -- the risky direction
        else:
            critic_under_human += 1  # critic held back something a human would've shipped

    print(f"Labeled rows: {len(labeled)}" + (f"  (skipped {skipped} unlabeled)" if skipped else ""))
    if len(labeled) < 10:
        print("Sample is small -- read this directionally, not statistically.\n")
    print(f"Mean absolute error (critic_overall vs. human_score): {mae:.1f} points")
    print(f"Pearson correlation:                                   {correlation:.2f}\n")
    print("Agreement at the APPROVED threshold (critic >= 90):")
    print(f"  both approve                                : {both_approve}")
    print(f"  both hold back                               : {both_hold}")
    print(f"  critic approved, human would NOT have (risk) : {critic_over_human}")
    print(f"  critic held back, human WOULD have (over-cautious): {critic_under_human}")


def _error_modes(conn) -> None:
    runs = list_optimizations(conn)
    if not runs:
        print("No optimization runs yet -- run scripts/run_pipeline.py first.")
        return

    status_counts = Counter(r["approval_status"] for r in runs)
    effective_counts = Counter(r["effective_status"] for r in runs)

    print(f"{len(runs)} run(s) total.\n")
    print("By pipeline verdict (approval_status):")
    for status, count in status_counts.most_common():
        print(f"  {status:14s} {count:>4}  ({count / len(runs):.0%})")
    print("\nBy effective status (human override applied where present):")
    for status, count in effective_counts.most_common():
        print(f"  {status:14s} {count:>4}  ({count / len(runs):.0%})")

    dims = ["seo", "readability", "completeness", "brand_consistency"]

    def _avg_scores(subset):
        if not subset:
            return None
        return {
            dim: sum(r["critic_scores"].get(dim, 0) for r in subset) / len(subset)
            for dim in dims
        }

    print("\nAverage critic sub-scores, overall vs. by verdict:")
    overall_avg = _avg_scores([r for r in runs if r["critic_scores"]])
    if overall_avg:
        print("  " + "  ".join(f"{d}={overall_avg[d]:.1f}" for d in dims) + "   [all runs]")
    for status in status_counts:
        subset = [r for r in runs if r["approval_status"] == status and r["critic_scores"]]
        avg = _avg_scores(subset)
        if avg:
            print("  " + "  ".join(f"{d}={avg[d]:.1f}" for d in dims) + f"   [{status}]")

    issue_counter = Counter(issue for r in runs for issue in r["audit_issues"])
    if issue_counter:
        print("\nMost common audit issues (pre-generation, exact-string match):")
        for issue, count in issue_counter.most_common(8):
            print(f"  {count:>3}x  {issue}")

    claim_counter = Counter(claim for r in runs for claim in r["blocked_claims"])
    if claim_counter:
        rejected = [r for r in runs if r["approval_status"] == "REJECTED"]
        print(
            f"\nBlocked claims that fired ({len(rejected)}/{len(runs)} runs REJECTED "
            "because of one):"
        )
        for claim, count in claim_counter.most_common():
            print(f"  {count:>3}x  \"{claim}\"")

    paired = [
        (r["audit_score"], r["critic_overall"])
        for r in runs
        if r["audit_score"] is not None and r["critic_overall"] is not None
    ]
    if len(paired) >= 2:
        audit_arr = np.array([p[0] for p in paired])
        critic_arr = np.array([p[1] for p in paired])
        corr = float(np.corrcoef(audit_arr, critic_arr)[0, 1])
        print(
            f"\nCorrelation between pre-generation audit_score and post-generation "
            f"critic_overall: {corr:.2f}"
        )
        print(
            "  (near 0: the pipeline's rewrite quality doesn't depend on how bad the "
            "original listing was -- worth confirming that's actually true rather than "
            "assuming it.)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-set", action="store_true")
    parser.add_argument("--n", type=int, default=20, help="eval set size when first built (default 20)")
    parser.add_argument("--force", action="store_true", help="regenerate runs even if one already exists")
    parser.add_argument("--agreement", type=Path, metavar="LABELS_CSV")
    parser.add_argument("--error-modes", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    if not any([args.build_set, args.agreement, args.error_modes]):
        parser.error("pass one of --build-set, --agreement LABELS_CSV, or --error-modes")

    with get_db(args.database_url) as conn:
        if args.build_set:
            _build_set(conn, args.n, args.force)
        if args.agreement:
            _agreement(args.agreement)
        if args.error_modes:
            _error_modes(conn)


if __name__ == "__main__":
    main()
