"""
WeaveForward ETL — entry point.

Flow per table
──────────────
  Endpoint-sourced  →  REST API  →  GCS (NDJSON)  →  BigQuery
  Model-sourced     →  Django ORM  →  GCS (NDJSON)  →  BigQuery

Run locally:
  cd WeaveForward_Backend
  DJANGO_SETTINGS_MODULE=WeaveForward_Backend.settings \
  API_BASE_URL=http://localhost:8000/api \
  ADMIN_EMAIL=admin@weaveforward.com \
  ADMIN_PASSWORD=SecureAdminPassword123 \
  GCP_PROJECT=weaveforward \
  BQ_DATASET=weaveforward_dw \
  GCS_BUCKET=weaveforward-etl \
  python deployment/main.py
"""

import os
import sys
import datetime
import traceback

# ── 1. Bootstrap Django (required for ORM-based extractors) ─────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.environ.get("DJANGO_SETTINGS_MODULE", "WeaveForward_Backend.settings"),
)
import django
django.setup()

# ── 2. Project imports ───────────────────────────────────────────────────────
from auth import get_admin_session  # noqa: E402
from loaders.gcs       import upload as gcs_upload  # noqa: E402
from loaders.bigquery  import load   as bq_load     # noqa: E402

# Endpoint-based extractors
from extractors.users_endpoint              import extract as extract_users
from extractors.donations_endpoint          import extract as extract_donations
from extractors.donation_items_endpoint     import extract as extract_donation_items
from extractors.inventory_endpoint          import extract as extract_inventory
from extractors.brand_fiber_lookups_endpoint import extract as extract_brand_fiber_lookups

# ORM-based extractors
from extractors.match_predictions import extract as extract_match_predictions
from extractors.subscriptions     import extract_subscriptions, extract_subscription_payments
from extractors.audit_trail       import extract as extract_audit_trail
from extractors.orders            import extract_orders, extract_order_payments


GCS_BUCKET = os.environ["GCS_BUCKET"]
GCS_PREFIX = os.environ.get("GCS_PREFIX", "raw")

# ── 3. Pipeline definition ───────────────────────────────────────────────────
# Each entry: (table_name, extractor_fn, uses_session)
PIPELINE = [
    # (table_name,              extractor_fn,                    needs_session)
    ("users",                   extract_users,                   True),
    ("donations",               extract_donations,               True),
    ("donation_items",          extract_donation_items,          True),
    ("inventory",               extract_inventory,               True),
    ("brand_fiber_lookups",     extract_brand_fiber_lookups,     True),
    ("match_predictions",       extract_match_predictions,       False),
    ("subscriptions",           extract_subscriptions,           False),
    ("subscription_payments",   extract_subscription_payments,   False),
    ("audit_trail",             extract_audit_trail,             False),
    ("orders",                  extract_orders,                  False),
    ("order_payments",          extract_order_payments,          False),
]


def run() -> None:
    start   = datetime.datetime.utcnow()
    session = get_admin_session()

    results: list[dict] = []
    errors:  list[str]  = []

    for table_name, extractor_fn, needs_session in PIPELINE:
        print(f"\n{'─'*60}")
        print(f"[ETL] {table_name}")
        try:
            records  = extractor_fn(session) if needs_session else extractor_fn()
            gcs_uri  = gcs_upload(records, table_name, GCS_BUCKET, GCS_PREFIX)
            bq_load(gcs_uri, table_name)
            results.append({"table": table_name, "rows": len(records), "status": "OK"})
        except Exception as exc:  # noqa: BLE001
            errors.append(table_name)
            results.append({"table": table_name, "rows": 0, "status": f"ERROR: {exc}"})
            traceback.print_exc()

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed = (datetime.datetime.utcnow() - start).total_seconds()
    print(f"\n{'═'*60}")
    print(f"  WeaveForward ETL — run complete ({elapsed:.1f}s)")
    print(f"{'─'*60}")
    for r in results:
        icon = "✓" if r["status"] == "OK" else "✗"
        print(f"  [{icon}] {r['table']:<28}  {str(r['rows']):>8} rows  {r['status']}")
    print(f"{'═'*60}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    run()
