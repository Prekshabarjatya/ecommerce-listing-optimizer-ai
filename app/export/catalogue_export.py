"""Produces the human-reviewable optimized catalogue: original vs. generated
listing fields side by side with scores and approval status, for a person
to inspect before anything goes to Meesho. See architecture: Meesho export
layer — writes a new file rather than touching the original workbook.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg

from app.database.repository import list_latest_optimizations_with_listing

EXPORT_COLUMNS = [
    "seller_sku",
    "effective_status",
    "approval_status",
    "human_decision",
    "original_title",
    "generated_title",
    "original_description",
    "generated_description",
    "category",
    "generated_highlights",
    "generated_keywords",
    "audit_score",
    "audit_issues",
    "critic_overall",
    "fact_check_passed",
    "blocked_claims",
    "created_at",
]


def build_export_rows(
    conn: psycopg.Connection, effective_status: str | None = None
) -> list[dict]:
    records = list_latest_optimizations_with_listing(conn, effective_status=effective_status)
    rows = []
    for r in records:
        rows.append(
            {
                "seller_sku": r["seller_sku"],
                "effective_status": r["effective_status"],
                "approval_status": r["approval_status"],
                "human_decision": r["human_decision"],
                "original_title": r["original_title"],
                "generated_title": r["generated_title"],
                "original_description": r["original_description"],
                "generated_description": r["generated_description"],
                "category": r["category"],
                "generated_highlights": " | ".join(r["generated_highlights"]),
                "generated_keywords": ", ".join(r["generated_keywords"]),
                "audit_score": r["audit_score"],
                "audit_issues": "; ".join(r["audit_issues"]),
                "critic_overall": r["critic_overall"],
                "fact_check_passed": r["fact_check_passed"],
                "blocked_claims": ", ".join(r["blocked_claims"]),
                "created_at": r["created_at"],
            }
        )
    return rows


def export_catalogue(
    conn: psycopg.Connection,
    output_path: str | Path,
    effective_status: str | None = None,
) -> int:
    rows = build_export_rows(conn, effective_status=effective_status)
    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix == ".csv":
        df.to_csv(output_path, index=False)
    else:
        df.to_excel(output_path, index=False, sheet_name="Optimized Catalogue")

    return len(df)
