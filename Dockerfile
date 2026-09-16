# Single image, two run modes (see docker-compose.yml's `command:` override
# per service): FastAPI (app/api.py) and the Streamlit review UI
# (frontend/streamlit_app.py) share one dependency set, so one image avoids
# building/maintaining two. The frontend talks to the API only over HTTP
# (see frontend/streamlit_app.py's module docstring), never imports agents/
# or app/ directly -- it just happens to ship in the same image for
# simplicity.

FROM python:3.12-slim AS builder

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv

COPY agents/ agents/
COPY app/ app/
COPY frontend/ frontend/
COPY scripts/ scripts/
COPY knowledge_base/ knowledge_base/

# The SQLite DB lives under /app/data, bind-mounted by docker-compose.yml so
# it survives a container recreate -- create it here so the directory is
# owned by appuser even before the volume is mounted over it.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000 8501

# docker-compose.yml overrides this per service; this default is the API,
# so `docker build . && docker run` without compose still does something
# useful.
CMD ["python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
