"""
Load all fixture files into the Cloud SQL instance via Django's loaddata.

Fixtures are loaded in dependency order so foreign-key constraints are satisfied:
  uploads → users → brand_fiber_lookups → donations → donation_items
  → match_predictions → inventory_ledger → subscriptions
  → subscription_payments → orders → order_payments
  → audit_trail → api_tokens
"""
import os
from pathlib import Path
from django.core.management import call_command

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Load order matters — parents must precede children
FIXTURE_ORDER = [
    "uploads",
    "users",
    "brand_fiber_lookups",
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


def apply() -> dict:
    loaded: list[str] = []
    skipped: list[str] = []

    for name in FIXTURE_ORDER:
        fixture_path = _FIXTURES_DIR / f"{name}.json"
        if not fixture_path.exists():
            skipped.append(name)
            continue

        import json
        with open(fixture_path) as f:
            data = json.load(f)
        if not data:
            skipped.append(f"{name} (empty)")
            continue

        call_command("loaddata", str(fixture_path), verbosity=0)
        loaded.append(name)

    detail = f"Loaded: {', '.join(loaded) or 'none'}"
    if skipped:
        detail += f" | Skipped (not found): {', '.join(skipped)}"

    return {"status": "OK", "detail": detail}
