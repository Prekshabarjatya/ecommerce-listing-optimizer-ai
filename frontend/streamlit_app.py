"""Stage 9: human-facing UI over the API (app/api.py).

Deliberately talks to the API only over HTTP (via `requests`), never
imports agents/ or app/ directly -- that keeps this process independent of
the pipeline's Python environment (no GROQ_API_KEY, no DB file access) and
matches how `streamlit run` resolves imports (relative to this file's own
directory, not the repo root), which would otherwise break `from app...`
imports. See docker-compose.yml: this runs as its own container, talking
to the api container over the compose network. render.yaml sets this to
Render's `fromService`/`hostport` value instead (bare "host:port", no
scheme -- that's Render's private-network format, not a URL), hence the
scheme normalization below.
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
if not API_BASE_URL.startswith(("http://", "https://")):
    API_BASE_URL = f"http://{API_BASE_URL}"

st.set_page_config(page_title="AI E-Commerce Listing Optimizer", layout="wide")


def _get(path: str, **kwargs):
    resp = requests.get(f"{API_BASE_URL}{path}", timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, **kwargs):
    resp = requests.post(f"{API_BASE_URL}{path}", timeout=120, **kwargs)
    resp.raise_for_status()
    return resp.json()


st.title("AI E-Commerce Listing Optimizer")
st.caption(
    "Knowledge-base-grounded, multi-agent listing optimizer -- RAG retrieval, "
    "content generation, deterministic fact validation, critic scoring, "
    "and human review."
)

try:
    _get("/health")
except requests.exceptions.RequestException:
    st.error(
        f"Can't reach the API at {API_BASE_URL}. Is it running? "
        "(`docker compose up`, or `uvicorn app.api:app` locally.)"
    )
    st.stop()

tab_catalogue, tab_review, tab_usage, tab_export = st.tabs(
    ["Catalogue", "Review queue", "Usage & cost", "Export"]
)

# ---------------------------------------------------------------------------
# Catalogue: run the pipeline on one or more SKUs
# ---------------------------------------------------------------------------
with tab_catalogue:
    st.subheader("Product catalogue")
    skus = _get("/skus")
    if not skus:
        st.info("No listings loaded yet -- run `scripts/load_database.py` first.")
    else:
        st.dataframe(skus, use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Run one SKU**")
            sku_options = [s["seller_sku"] for s in skus]
            chosen = st.selectbox("seller_sku", sku_options)
            if st.button("Run pipeline", type="primary"):
                with st.spinner(f"Running audit -> generate -> validate -> critique for {chosen}..."):
                    try:
                        result = _post(f"/pipeline/run/{chosen}")
                    except requests.exceptions.HTTPError as e:
                        st.error(f"Run failed: {e.response.json().get('detail', e)}")
                    else:
                        st.success(f"Approval status: {result['approval_status']}")
                        st.json(result)

        with col2:
            st.markdown("**Batch run**")
            skip_existing = st.checkbox("Skip SKUs that already have a run", value=True)
            if st.button("Run entire catalogue"):
                job = _post(
                    "/pipeline/run-batch",
                    json={"seller_skus": None, "skip_existing": skip_existing},
                )
                st.session_state["job_id"] = job["job_id"]
                st.info(f"Started job {job['job_id']} ({job['total']} SKU(s)).")

            job_id = st.session_state.get("job_id")
            if job_id:
                if st.button("Refresh job status"):
                    st.rerun()
                job = _get(f"/pipeline/jobs/{job_id}")
                st.progress(
                    job["completed"] / job["total"] if job["total"] else 1.0,
                    text=f"{job['completed']}/{job['total']} -- {job['status']}",
                )
                if job["status_counts"]:
                    st.write(job["status_counts"])
                if job["errors"]:
                    st.warning(f"{len(job['errors'])} error(s)")
                    st.json(job["errors"])

# ---------------------------------------------------------------------------
# Review queue: the human-in-the-loop workflow
# ---------------------------------------------------------------------------
with tab_review:
    st.subheader("Human review queue")
    st.caption(
        "Runs the pipeline scored below the auto-approval threshold. "
        "A blocked-claim (REJECTED) run never appears here -- that gate "
        "needs regenerated content, not a human override."
    )
    queue = _get("/review/queue")
    if not queue:
        st.success("Review queue is empty.")
    for run in queue:
        with st.expander(
            f"[{run['id']}] {run['seller_sku']} -- critic {run['critic_overall']}, "
            f"audit {run['audit_score']}"
        ):
            st.markdown(f"**Generated title:** {run['generated_title']}")
            st.markdown("**Highlights:**")
            for h in run["generated_highlights"]:
                st.markdown(f"- {h}")
            st.markdown(f"**Description:** {run['generated_description']}")
            st.markdown(f"**Keywords:** {', '.join(run['generated_keywords'])}")
            if run["audit_issues"]:
                st.markdown(f"**Audit issues:** {'; '.join(run['audit_issues'])}")
            st.markdown(f"**Critic scores:** {run['critic_scores']}")

            col_a, col_b = st.columns(2)
            if col_a.button("Approve", key=f"approve-{run['id']}", type="primary"):
                _post(f"/review/{run['id']}/approve")
                st.rerun()
            if col_b.button("Reject", key=f"reject-{run['id']}"):
                _post(f"/review/{run['id']}/reject")
                st.rerun()

# ---------------------------------------------------------------------------
# Usage & cost
# ---------------------------------------------------------------------------
with tab_usage:
    st.subheader("LLM usage & estimated cost")
    st.caption(
        "Estimated from a hard-coded per-model rate table -- directional, not a bill."
    )
    summary = _get("/usage/summary")
    if not summary:
        st.info("No LLM calls logged yet -- run the pipeline on at least one SKU.")
    else:
        st.dataframe(summary, use_container_width=True, hide_index=True)
        total_cost = sum(r["estimated_cost_usd"] or 0 for r in summary)
        total_tokens = sum(r["total_tokens"] or 0 for r in summary)
        c1, c2 = st.columns(2)
        c1.metric("Total tokens", f"{total_tokens:,}")
        c2.metric("Estimated cost", f"${total_cost:.4f}")

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
with tab_export:
    st.subheader("Export")

    review_tab, upload_tab = st.tabs(["For human review", "For re-upload to Meesho"])

    with review_tab:
        st.caption(
            "Original vs. generated title/description side by side, scores, "
            "fact-check result, and effective approval status -- the file a "
            "person checks before anything goes to Meesho."
        )
        status_filter = st.selectbox(
            "Filter by effective status", ["(all)", "APPROVED", "NEEDS_REVIEW", "REJECTED"],
            key="review_status_filter",
        )
        fmt = st.radio("Format", ["xlsx", "csv"], horizontal=True, key="review_fmt")
        if st.button("Generate review export"):
            params = {"fmt": fmt}
            if status_filter != "(all)":
                params["status"] = status_filter
            resp = requests.get(f"{API_BASE_URL}/export", params=params, timeout=60)
            resp.raise_for_status()
            st.download_button(
                "Download",
                data=resp.content,
                file_name=f"santerra_optimized_catalogue.{fmt}",
                mime=resp.headers.get("content-type", "application/octet-stream"),
            )

    with upload_tab:
        st.caption(
            "Same columns, order, and sheet name as the file this catalogue "
            "was originally downloaded as -- every SKU appears, but only "
            "APPROVED listings get the generated title/description/keywords "
            "swapped in. Everything else stays exactly as Meesho gave it, "
            "so this is safe to re-upload as an incremental update."
        )
        fmt2 = st.radio("Format", ["xlsx", "csv"], horizontal=True, key="upload_fmt")
        if st.button("Generate re-upload file"):
            resp = requests.get(
                f"{API_BASE_URL}/export/meesho-upload", params={"fmt": fmt2}, timeout=60
            )
            resp.raise_for_status()
            st.download_button(
                "Download",
                data=resp.content,
                file_name=f"santerra_meesho_upload.{fmt2}",
                mime=resp.headers.get("content-type", "application/octet-stream"),
            )
