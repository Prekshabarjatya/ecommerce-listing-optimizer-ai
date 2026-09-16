from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.database.schema import ALL_SCHEMAS, LISTING_OPTIMIZATIONS_MIGRATIONS

# Render injects DATABASE_URL for its managed Postgres instance; docker-
# compose.yml points this at the `db` service for local/containerized runs.
# No file-based fallback -- see schema.py's module docstring for why this
# moved off SQLite.
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/santerra"


def connect(dsn: str = DEFAULT_DATABASE_URL) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)


def _apply_migrations(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for column, col_type in LISTING_OPTIMIZATIONS_MIGRATIONS:
            cur.execute(
                f"ALTER TABLE listing_optimizations ADD COLUMN IF NOT EXISTS {column} {col_type}"
            )


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for ddl in ALL_SCHEMAS:
            cur.execute(ddl)
    _apply_migrations(conn)
    conn.commit()


@contextmanager
def get_db(dsn: str = DEFAULT_DATABASE_URL) -> Iterator[psycopg.Connection]:
    conn = connect(dsn)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()
