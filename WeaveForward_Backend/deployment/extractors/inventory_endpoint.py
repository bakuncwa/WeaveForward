"""Extract full inventory via GET /api/inventory/export (unpaginated)."""
import os
import requests


def extract(session: requests.Session) -> list[dict]:
    base = os.environ["API_BASE_URL"].rstrip("/")
    resp = session.get(f"{base}/inventory/export", timeout=120)
    resp.raise_for_status()
    raw = resp.json()

    items = raw if isinstance(raw, list) else raw.get("results", raw.get("inventory", []))

    rows = []
    for inv in items:
        src = inv.get("source_donation") or {}
        rows.append({
            "inventory_id":        inv.get("inventory_id"),
            "source_donation_id":  src.get("donation_id"),
            "usage_amount_kg":     inv.get("usage_amount_kg"),
            "weight_before_kg":    inv.get("weight_before_kg"),
            "current_weight_kg":   inv.get("current_weight_kg"),
            "lifecycle_status":    inv.get("lifecycle_status"),
            "exit_state":          inv.get("exit_state"),
            "is_upcyclable":       inv.get("is_upcyclable"),
            "low_stock_threshold": inv.get("low_stock_threshold"),
            "was_forced_archived": inv.get("was_forced_archived"),
            "material_category":   inv.get("material_category"),
            "audit_required":      inv.get("audit_required"),
            "days_since_audit":    inv.get("days_since_audit"),
            "ingested_at":         inv.get("ingested_at"),
            "updated_at":          inv.get("updated_at"),
            "archived_at":         inv.get("archived_at"),
            "notes":               inv.get("notes"),
        })
    return rows
