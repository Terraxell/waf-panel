# waf-panel backend image.
# WHY: venv-based multi-stage. Reliable PATH/sys.path semantics, small final
#      image, no `--prefix` foot-gun that hides packages from sys.path.

# ── builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

# WHY: a venv at /opt/venv is the simplest way to ship a Python install
#      across stages. `pip install` into it; copy the directory; PATH does
#      the rest.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/

# WHY: "[dev]" pulls pytest/ruff so the same image can run the test suite
#      via `docker compose exec backend pytest`. Cost is small.
RUN pip install ".[dev]"

# ── runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src

# WHY: copy the populated venv from the builder. /opt/venv/bin/uvicorn etc.
#      are now first in PATH and import the matching site-packages.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# NOTE: health endpoint is /health, served by the FastAPI app from start.
CMD ["uvicorn", "waf_panel.main:app", "--host", "0.0.0.0", "--port", "8000"]
