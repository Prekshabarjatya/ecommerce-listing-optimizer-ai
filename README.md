# AI E-Commerce Listing Optimizer

A multi-agent platform that rewrites e-commerce product listings for search
and conversion, grounds every generated claim in a seller's real brand/product
facts via RAG, deterministically fact-checks its own output before anything
ships, and routes results through a human review queue. Ships as a FastAPI
backend, a Streamlit review UI, and Postgres, containerized and deployable
on Render.

The reference implementation in this repo targets Meesho's bulk-listing file
format and includes a real seller's catalogue and brand knowledge base as a
working example — see [How it works](#how-it-works) for the marketplace- and
brand-specific pieces you'd swap out for a different seller or platform.

## Quick start

```bash
git clone <this-repo>
cd ecommerce-listing-optimizer-ai
cp .env.example .env    # fill in GROQ_API_KEY
docker compose up -d    # starts Postgres, the API, and the review UI
```

- Review UI: http://localhost:8501
- API + interactive docs: http://localhost:8000/docs

See [Deployment](#deployment) for running this on Render instead of locally.

## How it works

1. **Ingestion** (`app/ingestion/`) turns a seller's raw Meesho Excel exports
   into cleaned, validated product records. Two source formats — an
   Inventory Update file and a Meesho Listing file — are recognized by
   column *name*, not position, so the pipeline keeps working if Meesho
   reorders or adds columns. They use unrelated identifier systems (numeric
   Meesho IDs vs. human-readable seller SKUs) with no reliable join key, so
   they're kept as two separate product masters rather than force-merged.

2. **RAG retrieval** (`app/rag/`) pulls relevant brand/product facts — real
   content from `knowledge_base/*.md` (company facts, product portfolio,
   approved vs. verification-required sustainability claims, brand voice,
   competitive landscape) — via TF-IDF + cosine similarity, no embeddings
   API or vector DB needed at this catalogue size.

3. **Agents** (`agents/`) do the actual work, each backed by an LLM call
   except one:
   - `audit_agent.py` scores the *current* listing and flags issues
   - `content_agent.py` generates a new title/highlights/description/keywords,
     grounded in the retrieved brand context and the audit's findings
   - `critic_agent.py` scores the *generated* listing (SEO, readability,
     completeness, brand consistency) — optionally on a different model
     than the generator, to avoid the same model grading its own homework
   - `fact_validator.py` is **not** an LLM call — a policy gate an LLM can
     talk its way around isn't a gate. It checks generated copy against a
     hard-coded list of approved/blocked claims sourced from
     `knowledge_base/sustainability_and_claims.md` (a test asserts the two
     stay in sync)

4. **Orchestration + policy** (`app/orchestration/`) chains the above into
   one pipeline per listing and applies a deterministic approval rule
   (`policy.py`): a blocked claim REJECTS regardless of critic score —
   fact-check failures aren't negotiable — otherwise critic score ≥ 90 is
   APPROVED, else NEEDS_REVIEW. Every run persists to Postgres
   (`listing_optimizations`) along with which prompt version and model
   produced it, so a prompt/model change stays comparable against past runs.

5. **Human review** — a NEEDS_REVIEW run sits in a queue (`GET
   /review/queue`, or the review UI's Review queue tab) until a person
   approves or rejects it. A REJECTED (fact-check-failed) run never appears
   here: that gate isn't something a review step should rubber-stamp past,
   it needs regenerated content instead. The human decision, once made, is
   the *effective status* everywhere downstream.

6. **Export** (`app/export/`) produces two different files:
   - a side-by-side review file (original vs. generated, scores, fact-check
     result) for a person to inspect
   - a re-upload file in the *exact* shape the catalogue was originally
     downloaded from Meesho (same columns, order, sheet name) — every SKU
     appears, but only effectively-APPROVED rows get the generated content
     swapped in, so it's safe to hand straight back to Meesho as an
     incremental update

7. **Evaluation & cost tracking** (`docs/evaluation.md`) — every LLM call is
   logged (tokens, latency, estimated cost) to `llm_call_log`
   (`scripts/usage_report.py` reports it), and `scripts/run_eval.py`
   analyzes accumulated runs (approval-status mix, weakest critic dimension,
   common blocked claims) with no human labels needed.

## Project structure

```
agents/                  audit / content-generation / critic agents, the deterministic
                          fact validator, the LLM client, and call-cost telemetry
app/
├── ingestion/            Excel parsing + cleaning + validation
├── database/             Postgres schema, connection, and query layer
├── rag/                  knowledge_base/*.md loader + TF-IDF retriever
├── orchestration/        the per-listing pipeline and its approval policy
├── export/               the review file and the Meesho re-upload file
└── api.py                FastAPI layer over all of the above
frontend/streamlit_app.py human review UI: catalogue browser, review queue, exports
scripts/                  CLI entry points for ingestion, batch runs, review, export, eval
knowledge_base/           real seller brand/product facts used for RAG grounding
tests/                    58 tests; every LLM call is mocked, fact_validator and the
                          DB-backed API routes are exercised directly against Postgres
```

## Setup

Needs a Groq API key ([console.groq.com/keys](https://console.groq.com/keys)):

```bash
cp .env.example .env   # fill in GROQ_API_KEY
```

Load a real catalogue in (writes to Postgres, not committed anywhere —
`data/raw/` and `data/processed/` are gitignored since real exports carry
proprietary pricing/product data):

```bash
python scripts/load_database.py path/to/Inventory-Update-File.xlsx path/to/Listing-File.xls
```

Run the pipeline:

```bash
python scripts/run_pipeline.py SELLER-SKU-HERE
python scripts/run_pipeline.py --all --skip-existing   # whole catalogue, skip already-run SKUs
```

Work the review queue and export:

```bash
python scripts/review_queue.py                  # list pending NEEDS_REVIEW runs
python scripts/review_queue.py --approve 12
python scripts/export_catalogue.py               # human-review file
python scripts/export_meesho_upload.py           # Meesho re-upload file
python scripts/usage_report.py                   # token/cost/latency by agent+model
```

## API

`app/api.py` is a thin FastAPI layer over the same functions the CLI scripts
call — no separate business logic. Full interactive schema at `/docs` once
running; the shape:

| Route | What it does |
|---|---|
| `GET /skus` | Every SKU with its effective approval status |
| `POST /pipeline/run/{seller_sku}` | Run the pipeline for one SKU |
| `POST /pipeline/run-batch` | Backgrounded batch run, polled via `GET /pipeline/jobs/{id}` |
| `GET /review/queue`, `POST /review/{id}/approve\|reject` | Human review workflow |
| `GET /export`, `GET /export/meesho-upload` | The two export formats |
| `GET /usage/summary` | Token/cost/latency rollup |

Batch runs track progress in an in-memory dict rather than a task queue like
Celery/Redis — a reasonable choice for a catalogue in the hundreds of SKUs,
not thousands of concurrent users, though it does mean job state doesn't
survive a process restart.

## Testing

```bash
pip install -r requirements.txt
pytest tests/
```

Needs a real Postgres reachable at `TEST_DATABASE_URL` (see
`tests/conftest.py`, default `localhost:5432/santerra_test`) — every table
gets truncated before each test for isolation. No `GROQ_API_KEY` or network
access needed otherwise; every LLM call is mocked.
`.github/workflows/ci.yml` runs the same suite against a Postgres service
container, plus a Docker build, on every push/PR.

## Deployment

### Docker Compose (local)

```bash
docker compose up -d
```

Three containers: `db` (Postgres), `api` (FastAPI), `frontend` (Streamlit),
started in healthcheck-gated dependency order. The API and the UI share one
image (`Dockerfile`) run with a different command — the UI talks to the API
only over HTTP, never touches Postgres or `GROQ_API_KEY` directly. The `db`
service's port is published to `localhost:5432` with credentials matching
`app/database/db.py`'s default, so scripts run from a local venv reach it
with no extra config.

Already have real data sitting in an old SQLite file? Bring the stack up
once, then:

```bash
python scripts/migrate_sqlite_to_postgres.py data/santerra.db
```

copies every row across (preserving ids and history) rather than
re-ingesting from the original Excel exports.

### Render (public deployment)

`render.yaml` is a [Render Blueprint](https://render.com/docs/blueprint-spec):
connect this repo in the Render dashboard ("New" → "Blueprint") and it
provisions a managed Postgres plus both services in one go, wired together
automatically.

**Read `render.yaml`'s top comment before deploying anything you intend to
keep** — it defaults the database to Render's free Postgres plan, which
**expires 30 days after creation and is deleted 14 days after that**
([render.com/docs/free](https://render.com/docs/free)). Change `plan: free`
to a paid plan (e.g. `basic-256mb`) for real use. The two web services
default to free too — Render spins them down after 15 minutes idle and
cold-starts the next request, a real tradeoff but not a data-loss one.

`GROQ_API_KEY` is deliberately left out of `render.yaml` (`sync: false`) —
Render prompts for it during Blueprint setup instead of it ever being
committed. Once deployed, load the catalogue in via
`scripts/migrate_sqlite_to_postgres.py` (against the database's *external*
connection string from the Render dashboard) or `scripts/load_database.py`
against fresh exports.

## Roadmap

Meesho API integration, if/when access exists — the re-upload export
already works standalone without it, a person can review the file and
upload it manually in the meantime.
