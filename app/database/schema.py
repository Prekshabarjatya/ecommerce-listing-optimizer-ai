"""Product master schema.

Postgres (see docs/evaluation.md's Stage 9 note and README's Stage 9
section) -- this was SQLite through Stage 8, chosen because this machine
had no Postgres/Docker installed. Both are available now that the project
is containerized and deployed on Render, so it moved to the real thing:
native BOOLEAN and JSONB instead of SQLite's 0/1-integer and
manually-serialized-TEXT stand-ins, and `SERIAL` instead of
`INTEGER PRIMARY KEY AUTOINCREMENT`.

Two tables, not one `products` table: the inventory and listing sources use
unrelated identifier systems with no reliable join key (see Stage 1), so
each keeps its own natural key rather than forcing a merge.
"""

CREATE_INVENTORY_ITEMS = """
CREATE TABLE IF NOT EXISTS inventory_items (
    product_id          INTEGER PRIMARY KEY,
    catalog_name         TEXT,
    catalog_id           INTEGER,
    product_name         TEXT NOT NULL,
    style_id             TEXT,
    variation_id         INTEGER,
    variation            TEXT,
    stock_status         TEXT,
    system_stock_count   REAL,
    your_stock_count     REAL,
    first_seen_at        TEXT NOT NULL,
    last_updated_at       TEXT NOT NULL
);
"""

CREATE_MEESHO_LISTINGS = """
CREATE TABLE IF NOT EXISTS meesho_listings (
    seller_sku            TEXT PRIMARY KEY,
    seo_title              TEXT,
    description            TEXT,
    keywords               TEXT,
    listing_id             REAL,
    settlement_price       REAL,
    pack_qty               REAL,
    pack_unit_detail        TEXT,
    shipping_charge         REAL,
    dimensions              TEXT,
    volumetric_weight_kg     REAL,
    actual_weight_kg         REAL,
    chargeable_weight_kg     REAL,
    category_1              TEXT,
    category_2              TEXT,
    category_3              TEXT,
    first_seen_at           TEXT NOT NULL,
    last_updated_at          TEXT NOT NULL
);
"""

CREATE_LISTING_OPTIMIZATIONS = """
CREATE TABLE IF NOT EXISTS listing_optimizations (
    id                     SERIAL PRIMARY KEY,
    seller_sku             TEXT NOT NULL REFERENCES meesho_listings(seller_sku),
    audit_score             INTEGER,
    audit_issues             JSONB,
    generated_title          TEXT,
    generated_highlights     JSONB,
    generated_description    TEXT,
    generated_keywords       JSONB,
    fact_check_passed        BOOLEAN NOT NULL,
    blocked_claims            JSONB,
    critic_overall             INTEGER,
    critic_scores               JSONB,
    approval_status              TEXT NOT NULL,
    created_at                    TEXT NOT NULL,
    human_decision                 TEXT,
    human_reviewed_at               TEXT
);
"""

# One row per LLM call (audit / content / critic) made during a
# run_pipeline() call. Separate from listing_optimizations so a run that
# fails partway (e.g. audit succeeds, content generation times out) still
# leaves a spend/latency trail, and so usage can be reported per-agent and
# per-model without parsing JSON blobs out of the optimization row. See
# scripts/usage_report.py and docs/evaluation.md.
CREATE_LLM_CALL_LOG = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                     SERIAL PRIMARY KEY,
    run_id                 INTEGER REFERENCES listing_optimizations(id),
    seller_sku             TEXT NOT NULL,
    agent                  TEXT NOT NULL,
    model                  TEXT NOT NULL,
    prompt_version         TEXT NOT NULL,
    prompt_tokens          INTEGER,
    completion_tokens      INTEGER,
    total_tokens           INTEGER,
    latency_ms             REAL,
    estimated_cost_usd     REAL,
    created_at             TEXT NOT NULL
);
"""

ALL_SCHEMAS = [
    CREATE_INVENTORY_ITEMS,
    CREATE_MEESHO_LISTINGS,
    CREATE_LISTING_OPTIMIZATIONS,
    CREATE_LLM_CALL_LOG,
]

# Columns added after the table already shipped. Postgres (unlike SQLite)
# supports `ADD COLUMN IF NOT EXISTS` directly, so init_schema() doesn't
# need SQLite's PRAGMA table_info() guard-check dance -- each of these is
# just its own idempotent ALTER TABLE.
LISTING_OPTIMIZATIONS_MIGRATIONS: list[tuple[str, str]] = [
    ("human_decision", "TEXT"),
    ("human_reviewed_at", "TEXT"),
    # Which prompt version and which model produced this run's generated
    # copy / critic score -- lets an ablation (a prompt or model change)
    # be compared against past runs instead of only future ones. See
    # docs/evaluation.md.
    ("audit_prompt_version", "TEXT"),
    ("content_prompt_version", "TEXT"),
    ("critic_prompt_version", "TEXT"),
    ("generation_model", "TEXT"),
    ("critic_model", "TEXT"),
]
