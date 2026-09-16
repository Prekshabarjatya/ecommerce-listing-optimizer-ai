import os

import pytest

from app.database.db import connect, init_schema

# Agent modules construct an OpenAI-compatible client at import time and
# raise if no key is set. Tests never hit the network (LLM calls are
# mocked), so a dummy key is enough to make the import succeed.
os.environ.setdefault("GROQ_API_KEY", "test-key-for-unit-tests")

# A real Postgres, not SQLite ":memory:" -- see app/database/schema.py's
# Stage 9 note on why the project moved off SQLite. Point this at a
# throwaway database: every table gets TRUNCATEd before each test (see
# pg_conn below), so nothing here should hold data you care about.
# docker-compose.yml's `db` service and .github/workflows/ci.yml's postgres
# service both default to matching credentials.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/santerra_test"
)

_ALL_TABLES = "inventory_items, meesho_listings, listing_optimizations, llm_call_log"


@pytest.fixture(scope="session")
def _pg_schema():
    """Runs init_schema() once per test session rather than once per test --
    CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS are idempotent, so
    there's nothing to gain from repeating them for every one of ~60 tests."""
    conn = connect(TEST_DATABASE_URL)
    init_schema(conn)
    conn.close()


@pytest.fixture
def pg_conn(_pg_schema):
    """A connection to the test database, TRUNCATEd to empty first.

    Unlike SQLite ":memory:" (a fresh, isolated database per connection),
    this is one real shared Postgres database -- and the repository layer
    commits its own writes (see app/database/repository.py), so a
    rollback-at-teardown wouldn't undo anything. TRUNCATE before the test
    runs is what actually guarantees each test starts from empty."""
    conn = connect(TEST_DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE")
    conn.commit()
    yield conn
    conn.close()
