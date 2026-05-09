# ml-service — online inference for waf-panel.
# WHY: multi-stage venv build keeps the runtime image lean.
#      The image bundles waf_ml.features (vendored from ../ml) so the
#      service uses the same featurizer the trainer used.

FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# WHY: a venv at /opt/venv survives the COPY into the runtime stage cleanly.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip wheel \
    && pip install -e ".[xgboost]"

# Vendored waf_ml package — one source of truth for features.
COPY waf_ml /opt/venv/lib/python3.11/site-packages/waf_ml

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1001 --home /app waf

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY src ./src

# Models are mounted in by docker-compose; image stays stateless.
RUN mkdir -p /app/models && chown -R waf:waf /app
USER waf

ENV ML_MODEL_DIR=/app/models
EXPOSE 8001

# WHY: a single uvicorn worker is fine for a course project; horizontal
#      scaling is the operator's call. Health-check hits /readyz.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request, sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/readyz').getcode() == 200 else 1)"

CMD ["uvicorn", "waf_ml_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
