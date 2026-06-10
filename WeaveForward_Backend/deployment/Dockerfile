# WeaveForward ETL — Cloud Run Job
# Extends the backend image: reuses Django settings + ORM for model-based extractors,
# adds google-cloud-* libs for GCS/BigQuery, and sets the ETL entry point.

FROM python:3.12-slim

WORKDIR /app

# ── System deps (MySQLClient build) ─────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
  && rm -rf /var/lib/apt/lists/*

# ── Python deps ──────────────────────────────────────────────────────────────
# Backend deps first (Django, DRF, etc.)
COPY ../requirements.txt /app/requirements_backend.txt
RUN pip install --no-cache-dir -r /app/requirements_backend.txt

# ETL-specific deps (GCS, BigQuery)
COPY deployment/requirements.txt /app/requirements_etl.txt
RUN pip install --no-cache-dir -r /app/requirements_etl.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY .. /app/

# ── Entry point ──────────────────────────────────────────────────────────────
WORKDIR /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "deployment/bigquery/main.py"]
