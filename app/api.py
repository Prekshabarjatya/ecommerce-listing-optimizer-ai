"""Stage 9: HTTP API over Stages 1-8.

Every route here is a thin wrapper around functions that already existed as
CLI scripts (run_pipeline.py, review_queue.py, export_catalogue.py,
usage_report.py) -- this module adds no new business logic, just a way to
reach it over HTTP so a UI (frontend/streamlit_app.py) or another service
can drive the pipeline without a shell on the host.

Batch runs go through BackgroundTasks with an in-memory job table
(_JOBS) rather than a task queue like Celery/Redis: this is a single-process
deployment (see docker-compose.yml / render.yaml), and the existing project
already prefers the lightest tool that works (TF-IDF over a vector DB --
see app/rag/retriever.py). That means job state does not survive a process
restart and does not scale past one worker process -- both fine for the
catalogue sizes this project targets, and documented here rather than
silently assumed.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.database.repository import (
    get_optimization_by_id,
    get_usage_summary,
    list_all_seller_skus,
    list_latest_optimizations_with_listing,
    list_llm_calls,
    list_optimizations,
    list_seller_skus_with_optimization,
    record_human_decision,
)
from app.export.catalogue_export import export_catalogue
from app.export.meesho_upload_export import export_meesho_upload
from app.orchestration.listing_pipeline import run_pipeline
from app.orchestration.models import PipelineResult
from app.rag.retriever import KnowledgeBaseRetriever

# Overridable via DATABASE_URL env var -- Render injects this for its
# managed Postgres; docker-compose.yml points it at the `db` service.
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

app = FastAPI(
    title="AI E-Commerce Listing Optimizer",
    description=(
        "Multi-agent, knowledge-base-grounded e-commerce listing optimizer. "
        "RAG-grounded content generation, deterministic fact validation, "
        "critic scoring, and a human review workflow -- see README.md."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


@app.get("/skus")
def list_skus() -> list[dict]:
    """Every seller_sku in the product master DB, with its effective status
    (human decision if reviewed, else the pipeline's own verdict) from its
    most recent optimization run, or null if it hasn't been run yet."""
    with get_db(DATABASE_URL) as conn:
        all_skus = list_all_seller_skus(conn)
        latest_by_sku = {
            r["seller_sku"]: r for r in list_latest_optimizations_with_listing(conn)
        }
        return [
            {
                "seller_sku": sku,
                "has_run": sku in latest_by_sku,
                "effective_status": latest_by_sku.get(sku, {}).get("effective_status"),
                "critic_overall": latest_by_sku.get(sku, {}).get("critic_overall"),
                "run_id": latest_by_sku.get(sku, {}).get("id"),
            }
            for sku in all_skus
        ]


# ---------------------------------------------------------------------------
# Pipeline: single-SKU run (synchronous -- a handful of LLM calls, seconds
# not minutes) and batch run (backgrounded -- could be the whole catalogue).
# ---------------------------------------------------------------------------


@app.post("/pipeline/run/{seller_sku}", response_model=PipelineResult)
def run_one(seller_sku: str) -> PipelineResult:
    retriever = KnowledgeBaseRetriever()
    with get_db(DATABASE_URL) as conn:
        try:
            return run_pipeline(conn, seller_sku, retriever=retriever)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e


class BatchRunRequest(BaseModel):
    seller_skus: list[str] | None = None  # None means every SKU in the DB
    skip_existing: bool = False


class JobStatus(BaseModel):
    job_id: str
    status: Literal["running", "done"]
    total: int
    completed: int
    status_counts: dict[str, int]
    errors: list[dict[str, str]]


_JOBS: dict[str, JobStatus] = {}


def _run_batch(job_id: str, seller_skus: list[str]) -> None:
    job = _JOBS[job_id]
    retriever = KnowledgeBaseRetriever()
    with get_db(DATABASE_URL) as conn:
        for seller_sku in seller_skus:
            try:
                result = run_pipeline(conn, seller_sku, retriever=retriever)
                job.status_counts[result.approval_status] = (
                    job.status_counts.get(result.approval_status, 0) + 1
                )
            except Exception as e:  # one bad SKU shouldn't kill the batch -- same as run_pipeline.py --all
                job.errors.append({"seller_sku": seller_sku, "error": f"{type(e).__name__}: {e}"})
            job.completed += 1
    job.status = "done"


@app.post("/pipeline/run-batch", response_model=JobStatus)
def run_batch(req: BatchRunRequest, background_tasks: BackgroundTasks) -> JobStatus:
    with get_db(DATABASE_URL) as conn:
        seller_skus = req.seller_skus or list_all_seller_skus(conn)
        if req.skip_existing:
            already_done = list_seller_skus_with_optimization(conn)
            seller_skus = [s for s in seller_skus if s not in already_done]

    job_id = str(uuid.uuid4())
    job = JobStatus(
        job_id=job_id, status="running", total=len(seller_skus), completed=0,
        status_counts={}, errors=[],
    )
    _JOBS[job_id] = job
    background_tasks.add_task(_run_batch, job_id, seller_skus)
    return job


@app.get("/pipeline/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id={job_id}")
    return job


# ---------------------------------------------------------------------------
# Human review queue
# ---------------------------------------------------------------------------


@app.get("/review/queue")
def review_queue() -> list[dict]:
    with get_db(DATABASE_URL) as conn:
        return [
            r for r in list_optimizations(conn, approval_status="NEEDS_REVIEW")
            if r["human_decision"] is None
        ]


@app.get("/review/{run_id}")
def review_detail(run_id: int) -> dict:
    with get_db(DATABASE_URL) as conn:
        run = get_optimization_by_id(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id={run_id}")
    return run


class ReviewDecisionResponse(BaseModel):
    run_id: int
    human_decision: str


@app.post("/review/{run_id}/approve", response_model=ReviewDecisionResponse)
def approve_run(run_id: int) -> ReviewDecisionResponse:
    return _decide(run_id, "APPROVED")


@app.post("/review/{run_id}/reject", response_model=ReviewDecisionResponse)
def reject_run(run_id: int) -> ReviewDecisionResponse:
    return _decide(run_id, "REJECTED")


def _decide(run_id: int, decision: str) -> ReviewDecisionResponse:
    with get_db(DATABASE_URL) as conn:
        try:
            record_human_decision(conn, run_id, decision)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return ReviewDecisionResponse(run_id=run_id, human_decision=decision)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@app.get("/export")
def export(
    status: Literal["APPROVED", "NEEDS_REVIEW", "REJECTED"] | None = Query(default=None),
    fmt: Literal["xlsx", "csv"] = Query(default="xlsx"),
) -> FileResponse:
    suffix = ".csv" if fmt == "csv" else ".xlsx"
    tmp = Path(tempfile.gettempdir()) / f"santerra_export_{uuid.uuid4().hex}{suffix}"
    with get_db(DATABASE_URL) as conn:
        export_catalogue(conn, tmp, effective_status=status)
    media_type = (
        "text/csv" if fmt == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"santerra_optimized_catalogue{suffix}"
    return FileResponse(tmp, media_type=media_type, filename=filename)


@app.get("/export/meesho-upload")
def export_meesho_upload_route(
    fmt: Literal["xlsx", "csv"] = Query(default="xlsx"),
) -> FileResponse:
    """Same shape as the file this catalogue was originally downloaded as
    (see app/export/meesho_upload_export.py) -- for re-uploading to Meesho,
    not for human review (that's GET /export)."""
    suffix = ".csv" if fmt == "csv" else ".xlsx"
    tmp = Path(tempfile.gettempdir()) / f"santerra_meesho_upload_{uuid.uuid4().hex}{suffix}"
    with get_db(DATABASE_URL) as conn:
        export_meesho_upload(conn, tmp)
    media_type = (
        "text/csv" if fmt == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"santerra_meesho_upload{suffix}"
    return FileResponse(tmp, media_type=media_type, filename=filename)


# ---------------------------------------------------------------------------
# Usage / cost reporting
# ---------------------------------------------------------------------------


@app.get("/usage/summary")
def usage_summary() -> list[dict]:
    with get_db(DATABASE_URL) as conn:
        return get_usage_summary(conn)


@app.get("/usage/{seller_sku}")
def usage_for_sku(seller_sku: str) -> list[dict]:
    with get_db(DATABASE_URL) as conn:
        return list_llm_calls(conn, seller_sku=seller_sku)
