"""
Load all fixture files into the Cloud SQL instance with upsert + sequence reset.

Deduplication strategy
───────────────────────
1. Upsert via Django's deserialize() + obj.save()
   - If a record with the same PK already exists → UPDATE (no duplicate error)
   - If the PK is new → INSERT
   - Replaces raw loaddata which would crash on duplicate PKs

2. Auto-increment sequence reset after each table
   - After loading, sets AUTO_INCREMENT = MAX(pk) + 1
   - Prevents future inserts from colliding with fixture IDs if the
     target DB already had records beyond the fixture range

Load order: parents before children to satisfy FK constraints.
  uploads → users → brand_fiber_lookups → donations → donation_items
  → match_predictions → inventory_ledger → subscriptions
  → subscription_payments → orders → order_payments
  → audit_trail → api_tokens
"""
import json
from pathlib import Path
from django.apps import apps
from django.core import serializers
from django.db import connection, transaction

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_ORDER = [
    "uploads",
    "users",
    # brand_fiber_lookups handled by catalog.py via bulk_create — skipped here
    "donations",
    "donation_items",
    "match_predictions",
    "inventory_ledger",
    "subscriptions",
    "subscription_payments",
    "orders",
    "order_payments",
    "audit_trail",
    "api_tokens",
]


def _reset_auto_increment(model_class) -> None:
    """Set AUTO_INCREMENT to MAX(pk) + 1 so future inserts never collide."""
    table  = model_class._meta.db_table
    pk_col = model_class._meta.pk.column
    with connection.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX(`{pk_col}`), 0) FROM `{table}`")
        max_id = cur.fetchone()[0]
        # AUTO_INCREMENT value must be a literal in MySQL — safe here because
        # max_id is an integer fetched from the DB, not user-supplied input.
        cur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}")


def _upsert_fixture(fixture_path: Path) -> int:
    """
    Deserialize fixture and save each object (INSERT or UPDATE by PK).
    Returns number of records processed.
    """
    with open(fixture_path) as f:
        content = f.read()

    model_class = None
    count = 0

    with transaction.atomic():
        for deserialized in serializers.deserialize("json", content):
            deserialized.save()
            model_class = deserialized.object.__class__
            count += 1

    if model_class is not None:
        _reset_auto_increment(model_class)

    return count


def apply() -> dict:
    loaded:  list[str] = []
    skipped: list[str] = []

    for name in FIXTURE_ORDER:
        fixture_path = _FIXTURES_DIR / f"{name}.json"

        if not fixture_path.exists():
            skipped.append(name)
            continue

        with open(fixture_path) as f:
            data = json.load(f)
        if not data:
            skipped.append(f"{name} (empty)")
            continue

        count = _upsert_fixture(fixture_path)
        loaded.append(f"{name} ({count})")

    detail = f"Upserted: {', '.join(loaded) or 'none'}"
    if skipped:
        detail += f" | Skipped: {', '.join(skipped)}"

    return {"status": "OK", "detail": detail}
