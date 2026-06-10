"""
WeaveForward ETL — entry point.

All extractors use Django ORM directly.

Flow per table
──────────────
  Django ORM  →  GCS (NDJSON, {YYYYMMDDHHMM}_{table}.ndjson)  →  BigQuery (SCD2)

Run locally:
  cd WeaveForward_Backend
  DJANGO_SETTINGS_MODULE=WeaveForward_Backend.settings \
  GCP_PROJECT=weaveforward-system \
  BQ_DATASET=weaveforward_dw \
  GCS_BUCKET=weaveforward-etl \
  python deployment/main.py
"""

import os
import sys
import datetime
import traceback

# ── 1. Bootstrap Django ──────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.environ.get("DJANGO_SETTINGS_MODULE", "WeaveForward_Backend.settings"),
)
import django
django.setup()

# ── 2. Imports ───────────────────────────────────────────────────────────────
from loaders.gcs      import upload as gcs_upload
from loaders.bigquery import load   as bq_load

from extractors.users              import extract as extract_users
from extractors.donations          import extract as extract_donations
from extractors.donation_items     import extract as extract_donation_items
from extractors.inventory          import extract as extract_inventory
from extractors.brand_fiber_lookups import extract as extract_brand_fiber_lookups
from extractors.match_predictions  import extract as extract_match_predictions
from extractors.subscriptions      import extract_subscriptions, extract_subscription_payments
from extractors.audit_trail        import extract as extract_audit_trail
from extractors.orders             import extract_orders, extract_order_payments

GCS_BUCKET = os.environ["GCS_BUCKET"]
GCS_PREFIX = os.environ.get("GCS_PREFIX", "raw")

# ── 3. Pipeline ──────────────────────────────────────────────────────────────
PIPELINE = [
    ("users",                 extract_users),
    ("donations",             extract_donations),
    ("donation_items",        extract_donation_items),
    ("inventory",             extract_inventory),
    ("brand_fiber_lookups",   extract_brand_fiber_lookups),
    ("match_predictions",     extract_match_predictions),
    ("subscriptions",         extract_subscriptions),
    ("subscription_payments", extract_subscription_payments),
    ("audit_trail",           extract_audit_trail),
    ("orders",                extract_orders),
    ("order_payments",        extract_order_payments),
]


def run() -> None:
    start   = datetime.datetime.now(datetime.UTC)
    results: list[dict] = []

    for table_name, extractor_fn in PIPELINE:
        print(f"\n{'─'*60}")
        print(f"[ETL] {table_name}")
        try:
            records = extractor_fn()
            gcs_uri = gcs_upload(records, table_name, GCS_BUCKET, GCS_PREFIX)
            bq_load(gcs_uri, table_name)
            results.append({"table": table_name, "rows": len(records), "status": "OK"})
        except Exception as exc:
            results.append({"table": table_name, "rows": 0, "status": f"ERROR: {exc}"})
            traceback.print_exc()

    elapsed = (datetime.datetime.now(datetime.UTC) - start).total_seconds()
    print(f"\n{'═'*60}")
    print(f"  WeaveForward ETL — run complete ({elapsed:.1f}s)")
    print(f"{'─'*60}")
    for r in results:
        icon = "✓" if r["status"] == "OK" else "✗"
        print(f"  [{icon}] {r['table']:<28}  {str(r['rows']):>8} rows  {r['status']}")
    print(f"{'═'*60}")

    if any(r["status"] != "OK" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    run()
