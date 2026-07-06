"""
WeaveForward Cloud SQL Loader — entry point.

Bootstraps the Cloud SQL production instance in order:
  1. migrations - apply all pending Django DB migrations
  2. fixtures   - upsert demo/UAT seed data with stable primary keys
  3. admin      - seed / update the admin user account from env vars
  4. catalog    - sync brand-fiber lookup catalog from CSV

Admin runs after fixtures so ADMIN_PASSWORD from the environment always wins
over fixture data.

Run locally (dev):
  cd WeaveForward_Backend
  DJANGO_SETTINGS_MODULE=WeaveForward_Backend.settings \
  ADMIN_EMAIL=admin@weaveforward.com \
  ADMIN_PASSWORD=SecureAdminPassword123 \
  CATALOG_CSV_PATH=backend/data/webscraped_data/webscraped_catalog_archive.csv \
  python deployment/cloudsql/main.py

Run on Cloud SQL instance (production):
  DJANGO_SETTINGS_MODULE=WeaveForward_Backend.settings \
  CLOUD_SQL_CONNECTION_NAME=weaveforward-system:asia-southeast1:weaveforward-db \
  DB_NAME=weaveforward_db \
  DB_USER=root \
  DB_PASSWORD=... \
  ADMIN_EMAIL=admin@weaveforward.com \
  ADMIN_PASSWORD=... \
  python deployment/cloudsql/main.py
"""

import os
import sys
import datetime
import traceback

# ── Bootstrap Django ─────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.environ.get("DJANGO_SETTINGS_MODULE", "WeaveForward_Backend.settings"),
)
import django
django.setup()

# ── Loaders ──────────────────────────────────────────────────────────────────
from deployment.cloudsql.loaders import migrations, admin, catalog, fixtures

PIPELINE = [
    ("migrations", migrations.apply),
    ("fixtures",   fixtures.apply),
    ("admin",      admin.apply),
    ("catalog",    catalog.apply),
]


def run() -> None:
    start   = datetime.datetime.now(datetime.UTC)
    results: list[dict] = []

    for name, loader_fn in PIPELINE:
        print(f"\n{'-'*50}")
        print(f"[CLOUDSQL] {name}")
        try:
            result = loader_fn()
            results.append({"loader": name, **result})
            print(f"  [{result['status']}] {result['detail']}")
        except Exception as exc:
            results.append({"loader": name, "status": "ERROR", "detail": str(exc)})
            traceback.print_exc()

    elapsed = (datetime.datetime.now(datetime.UTC) - start).total_seconds()
    print(f"\n{'='*50}")
    print(f"  WeaveForward Cloud SQL Loader - complete ({elapsed:.1f}s)")
    print(f"{'-'*50}")
    for r in results:
        icon = "OK" if r["status"] in ("OK", "SKIP") else "ERR"
        print(f"  [{icon}] {r['loader']:<14}  {r['status']:<6}  {r['detail']}")
    print(f"{'='*50}")

    if any(r["status"] == "ERROR" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    run()
