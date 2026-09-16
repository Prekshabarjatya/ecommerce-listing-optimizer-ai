"""One-off: migrate the pre-Stage-9 SQLite database (data/santerra.db) into
Postgres, preserving every row, its original id, and first_seen_at history
-- not a fresh re-ingestion. Run this once when cutting a real catalogue
over from the SQLite era; scripts/load_database.py is for ongoing catalogue
updates afterward.

Converts what changed between the two schemas (see app/database/schema.py):
JSON columns were TEXT (manually json.dumps'd) under SQLite, now JSONB;
fact_check_passed was a 0/1 INTEGER, now a real BOOLEAN. Everything else
copies straight across. SERIAL sequences are reset afterward so the next
INSERT continues from the highest migrated id instead of colliding with it.

Usage:
    python scripts/migrate_sqlite_to_postgres.py path/to/santerra.db [--database-url ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Json

from app.database.db import DEFAULT_DATABASE_URL, get_db

INVENTORY_COLUMNS = [
    "product_id", "catalog_name", "catalog_id", "product_name", "style_id",
    "variation_id", "variation", "stock_status", "system_stock_count",
    "your_stock_count", "first_seen_at", "last_updated_at",
]

LISTING_COLUMNS = [
    "seller_sku", "seo_title", "description", "keywords", "listing_id",
    "settlement_price", "pack_qty", "pack_unit_detail", "shipping_charge",
    "dimensions", "volumetric_weight_kg", "actual_weight_kg",
    "chargeable_weight_kg", "category_1", "category_2", "category_3",
    "first_seen_at", "last_updated_at",
]

OPTIMIZATION_JSON_COLUMNS = [
    "audit_issues", "generated_highlights", "generated_keywords", "blocked_claims",
    "critic_scores",
]

OPTIMIZATION_COLUMNS = [
    "id", "seller_sku", "audit_score", "audit_issues", "generated_title",
    "generated_highlights", "generated_description", "generated_keywords",
    "fact_check_passed", "blocked_claims", "critic_overall", "critic_scores",
    "approval_status", "created_at", "human_decision", "human_reviewed_at",
    "audit_prompt_version", "content_prompt_version", "critic_prompt_version",
    "generation_model", "critic_model",
]

LLM_CALL_LOG_COLUMNS = [
    "id", "run_id", "seller_sku", "agent", "model", "prompt_version",
    "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms",
    "estimated_cost_usd", "created_at",
]


def _copy_table(sqlite_conn, pg_conn, table: str, columns: list[str], json_columns: set[str]) -> int:
    rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

    with pg_conn.cursor() as cur:
        for row in rows:
            values = []
            for col, val in zip(columns, row):
                if col in json_columns:
                    values.append(Json(json.loads(val)) if val is not None else None)
                elif col == "fact_check_passed":
                    values.append(bool(val))
                else:
                    values.append(val)
            cur.execute(sql, values)
    pg_conn.commit()
    return len(rows)


def _reset_sequence(pg_conn, table: str) -> None:
    with pg_conn.cursor() as cur:
        cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
            f"(SELECT MAX(id) FROM {table}) IS NOT NULL)"
        )
    pg_conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    sqlite_conn = sqlite3.connect(args.sqlite_path)

    with get_db(args.database_url) as pg_conn:
        n = _copy_table(sqlite_conn, pg_conn, "inventory_items", INVENTORY_COLUMNS, set())
        print(f"inventory_items: {n} rows")

        n = _copy_table(sqlite_conn, pg_conn, "meesho_listings", LISTING_COLUMNS, set())
        print(f"meesho_listings: {n} rows")

        n = _copy_table(
            sqlite_conn, pg_conn, "listing_optimizations", OPTIMIZATION_COLUMNS,
            set(OPTIMIZATION_JSON_COLUMNS),
        )
        print(f"listing_optimizations: {n} rows")
        _reset_sequence(pg_conn, "listing_optimizations")

        n = _copy_table(sqlite_conn, pg_conn, "llm_call_log", LLM_CALL_LOG_COLUMNS, set())
        print(f"llm_call_log: {n} rows")
        _reset_sequence(pg_conn, "llm_call_log")

    sqlite_conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
