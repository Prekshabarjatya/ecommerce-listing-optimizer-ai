from __future__ import annotations

import psycopg
from datetime import UTC, datetime
from psycopg.types.json import Json

from app.ingestion.product_master import InventoryRecord, MeeshoListingRecord

INVENTORY_FIELDS = [
    "product_id",
    "catalog_name",
    "catalog_id",
    "product_name",
    "style_id",
    "variation_id",
    "variation",
    "stock_status",
    "system_stock_count",
    "your_stock_count",
]

LISTING_FIELDS = [
    "seller_sku",
    "seo_title",
    "description",
    "keywords",
    "listing_id",
    "settlement_price",
    "pack_qty",
    "pack_unit_detail",
    "shipping_charge",
    "dimensions",
    "volumetric_weight_kg",
    "actual_weight_kg",
    "chargeable_weight_kg",
    "category_1",
    "category_2",
    "category_3",
]

# Optional provenance fields on listing_optimizations -- which prompt
# version and which model produced this run, so past runs stay comparable
# across a prompt/model ablation. All nullable: a record missing these
# keys (older callers, or tests) still inserts fine, just without
# provenance. See docs/evaluation.md.
OPTIMIZATION_PROVENANCE_FIELDS = [
    "audit_prompt_version",
    "content_prompt_version",
    "critic_prompt_version",
    "generation_model",
    "critic_model",
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _upsert(
    conn: psycopg.Connection,
    table: str,
    key_field: str,
    fields: list[str],
    record_dict: dict,
    now: str,
) -> None:
    columns = fields + ["first_seen_at", "last_updated_at"]
    placeholders = ", ".join(["%s"] * len(columns))
    update_clause = ", ".join(f"{f} = excluded.{f}" for f in fields if f != key_field)
    update_clause += ", last_updated_at = excluded.last_updated_at"
    values = [record_dict[f] for f in fields] + [now, now]

    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({key_field}) DO UPDATE SET {update_clause}"
    )
    conn.execute(sql, values)


def upsert_inventory_records(
    conn: psycopg.Connection, records: list[InventoryRecord]
) -> int:
    now = _now()
    for record in records:
        _upsert(
            conn,
            "inventory_items",
            "product_id",
            INVENTORY_FIELDS,
            record.model_dump(),
            now,
        )
    conn.commit()
    return len(records)


def upsert_listing_records(
    conn: psycopg.Connection, records: list[MeeshoListingRecord]
) -> int:
    now = _now()
    for record in records:
        _upsert(
            conn,
            "meesho_listings",
            "seller_sku",
            LISTING_FIELDS,
            record.model_dump(),
            now,
        )
    conn.commit()
    return len(records)


def get_inventory_item(conn: psycopg.Connection, product_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM inventory_items WHERE product_id = %s", (product_id,)
    ).fetchone()
    return dict(row) if row else None


def get_listing(conn: psycopg.Connection, seller_sku: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM meesho_listings WHERE seller_sku = %s", (seller_sku,)
    ).fetchone()
    return dict(row) if row else None


def count_inventory_items(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()["count"]


def count_listings(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM meesho_listings").fetchone()["count"]


def list_low_stock_items(conn: psycopg.Connection, threshold: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM inventory_items "
        "WHERE system_stock_count IS NOT NULL AND system_stock_count <= %s "
        "ORDER BY system_stock_count ASC",
        (threshold,),
    ).fetchall()
    return [dict(r) for r in rows]


def insert_optimization_run(conn: psycopg.Connection, record: dict) -> int:
    """record keys: seller_sku, audit_score, audit_issues (list[str]),
    generated_title, generated_highlights (list[str]), generated_description,
    generated_keywords (list[str]), fact_check_passed (bool),
    blocked_claims (list[str]), critic_overall, critic_scores (dict),
    approval_status. Optionally also OPTIMIZATION_PROVENANCE_FIELDS
    (audit_prompt_version, content_prompt_version, critic_prompt_version,
    generation_model, critic_model) -- omitted keys are stored as NULL."""
    provenance = {field: record.get(field) for field in OPTIMIZATION_PROVENANCE_FIELDS}

    cursor = conn.execute(
        "INSERT INTO listing_optimizations ("
        "seller_sku, audit_score, audit_issues, generated_title, generated_highlights, "
        "generated_description, generated_keywords, fact_check_passed, blocked_claims, "
        "critic_overall, critic_scores, approval_status, created_at, "
        "audit_prompt_version, content_prompt_version, critic_prompt_version, "
        "generation_model, critic_model"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING id",
        (
            record["seller_sku"],
            record["audit_score"],
            Json(record["audit_issues"]),
            record["generated_title"],
            Json(record["generated_highlights"]),
            record["generated_description"],
            Json(record["generated_keywords"]),
            record["fact_check_passed"],
            Json(record["blocked_claims"]),
            record["critic_overall"],
            Json(record["critic_scores"]),
            record["approval_status"],
            _now(),
            provenance["audit_prompt_version"],
            provenance["content_prompt_version"],
            provenance["critic_prompt_version"],
            provenance["generation_model"],
            provenance["critic_model"],
        ),
    )
    run_id = cursor.fetchone()["id"]
    conn.commit()
    return run_id


def insert_llm_call_log(
    conn: psycopg.Connection,
    run_id: int | None,
    seller_sku: str,
    metrics: list,
) -> None:
    """Persists one row per agents.telemetry.CallMetrics -- the token/cost/
    latency trail for a single run_pipeline() call. run_id may be None if
    logged before a listing_optimizations row exists yet."""
    if not metrics:
        return
    now = _now()
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO llm_call_log ("
            "run_id, seller_sku, agent, model, prompt_version, prompt_tokens, "
            "completion_tokens, total_tokens, latency_ms, estimated_cost_usd, created_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    run_id,
                    seller_sku,
                    m.agent,
                    m.model,
                    m.prompt_version,
                    m.prompt_tokens,
                    m.completion_tokens,
                    m.total_tokens,
                    m.latency_ms,
                    m.estimated_cost_usd,
                    now,
                )
                for m in metrics
            ],
        )
    conn.commit()


def get_usage_summary(conn: psycopg.Connection) -> list[dict]:
    """Per agent/model/prompt-version rollup of every logged LLM call --
    backs `scripts/usage_report.py`."""
    rows = conn.execute(
        "SELECT agent, model, prompt_version, COUNT(*) AS calls, "
        "SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens, "
        "SUM(total_tokens) AS total_tokens, AVG(latency_ms) AS avg_latency_ms, "
        "SUM(estimated_cost_usd) AS estimated_cost_usd "
        "FROM llm_call_log GROUP BY agent, model, prompt_version "
        "ORDER BY agent, model, prompt_version"
    ).fetchall()
    return [dict(r) for r in rows]


def list_llm_calls(conn: psycopg.Connection, seller_sku: str | None = None) -> list[dict]:
    if seller_sku:
        rows = conn.execute(
            "SELECT * FROM llm_call_log WHERE seller_sku = %s ORDER BY id", (seller_sku,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM llm_call_log ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _deserialize_optimization_row(row: dict) -> dict:
    # JSONB columns already come back as native list/dict from psycopg --
    # no json.loads needed (unlike the SQLite/TEXT era of this schema).
    d = dict(row)
    d["audit_issues"] = d["audit_issues"] or []
    d["generated_highlights"] = d["generated_highlights"] or []
    d["generated_keywords"] = d["generated_keywords"] or []
    d["blocked_claims"] = d["blocked_claims"] or []
    d["critic_scores"] = d["critic_scores"] or {}
    # A human override (see record_human_decision) is the final word on a
    # NEEDS_REVIEW run; otherwise the pipeline's own verdict stands.
    d["effective_status"] = d.get("human_decision") or d["approval_status"]
    return d


def get_latest_optimization(conn: psycopg.Connection, seller_sku: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM listing_optimizations WHERE seller_sku = %s "
        "ORDER BY id DESC LIMIT 1",
        (seller_sku,),
    ).fetchone()
    return _deserialize_optimization_row(row) if row else None


def list_optimizations(
    conn: psycopg.Connection, approval_status: str | None = None
) -> list[dict]:
    if approval_status:
        rows = conn.execute(
            "SELECT * FROM listing_optimizations WHERE approval_status = %s "
            "ORDER BY id DESC",
            (approval_status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM listing_optimizations ORDER BY id DESC"
        ).fetchall()
    return [_deserialize_optimization_row(r) for r in rows]


def list_latest_optimizations_with_listing(
    conn: psycopg.Connection, effective_status: str | None = None
) -> list[dict]:
    """One row per seller_sku: its original listing fields joined with its
    most recent optimization run. Backs the human-reviewable export.

    Filters on effective_status (human_decision if a human has reviewed it,
    else the pipeline's own approval_status) rather than the raw pipeline
    verdict, since that's what actually determines whether a listing is
    ready to upload."""
    query = (
        "SELECT m.seller_sku AS seller_sku, "
        "m.seo_title AS original_title, m.description AS original_description, "
        "m.category_1 AS category, "
        "o.* "
        "FROM meesho_listings m "
        "JOIN listing_optimizations o ON o.seller_sku = m.seller_sku "
        "JOIN (SELECT seller_sku, MAX(id) AS max_id FROM listing_optimizations "
        "      GROUP BY seller_sku) latest "
        "  ON latest.seller_sku = o.seller_sku AND latest.max_id = o.id "
        "ORDER BY m.seller_sku"
    )
    records = [_deserialize_optimization_row(r) for r in conn.execute(query).fetchall()]
    if effective_status:
        records = [r for r in records if r["effective_status"] == effective_status]
    return records


def list_all_listings_with_latest_optimization(conn: psycopg.Connection) -> list[dict]:
    """Every seller_sku in meesho_listings (LEFT JOIN, unlike
    list_latest_optimizations_with_listing's INNER JOIN) -- a SKU that has
    never been run still appears, with every optimization field as None.
    Backs the Meesho re-upload export (app/export/meesho_upload_export.py),
    which needs the original value for any SKU that isn't APPROVED yet."""
    query = (
        "SELECT m.seller_sku AS seller_sku, "
        "m.seo_title, m.description, m.keywords, m.listing_id, m.settlement_price, "
        "m.pack_qty, m.pack_unit_detail, m.shipping_charge, m.dimensions, "
        "m.volumetric_weight_kg, m.actual_weight_kg, m.chargeable_weight_kg, "
        "m.category_1, m.category_2, m.category_3, "
        "o.generated_title, o.generated_description, o.generated_keywords, "
        "o.approval_status, o.human_decision "
        "FROM meesho_listings m "
        "LEFT JOIN (SELECT seller_sku, MAX(id) AS max_id FROM listing_optimizations "
        "           GROUP BY seller_sku) latest ON latest.seller_sku = m.seller_sku "
        "LEFT JOIN listing_optimizations o ON o.id = latest.max_id "
        "ORDER BY m.seller_sku"
    )
    rows = []
    for r in conn.execute(query).fetchall():
        d = dict(r)
        d["generated_keywords"] = d["generated_keywords"] or []
        d["effective_status"] = d["human_decision"] or d["approval_status"]
        rows.append(d)
    return rows


def list_all_seller_skus(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute("SELECT seller_sku FROM meesho_listings ORDER BY seller_sku").fetchall()
    return [r["seller_sku"] for r in rows]


def list_seller_skus_with_optimization(conn: psycopg.Connection) -> set[str]:
    """SKUs that already have at least one optimization run -- used to skip
    already-completed SKUs when resuming a batch run after a partial
    failure (e.g. an API timeout partway through)."""
    rows = conn.execute("SELECT DISTINCT seller_sku FROM listing_optimizations").fetchall()
    return {r["seller_sku"] for r in rows}


def get_optimization_by_id(conn: psycopg.Connection, run_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM listing_optimizations WHERE id = %s", (run_id,)
    ).fetchone()
    return _deserialize_optimization_row(row) if row else None


def record_human_decision(
    conn: psycopg.Connection, run_id: int, decision: str
) -> None:
    """decision must be APPROVED or REJECTED. Only valid for a run whose
    pipeline verdict was NEEDS_REVIEW -- a REJECTED (fact-check failed) run
    isn't something a human review should be able to rubber-stamp past;
    that requires regenerating the content instead."""
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError(f"decision must be APPROVED or REJECTED, got {decision!r}")

    run = get_optimization_by_id(conn, run_id)
    if run is None:
        raise ValueError(f"No optimization run with id={run_id}")
    if run["approval_status"] != "NEEDS_REVIEW":
        raise ValueError(
            f"run {run_id} has approval_status={run['approval_status']!r}, "
            "only NEEDS_REVIEW runs can be human-reviewed"
        )

    conn.execute(
        "UPDATE listing_optimizations SET human_decision = %s, human_reviewed_at = %s "
        "WHERE id = %s",
        (decision, _now(), run_id),
    )
    conn.commit()
