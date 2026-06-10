"""Extract inventory ledger via Django ORM (bypasses TUAB-only REST endpoint)."""


def extract() -> list[dict]:
    from backend.models import InventoryLedger

    rows = []
    for inv in InventoryLedger.objects.select_related("source_donation").order_by("inventory_id"):
        rows.append({
            "inventory_id":        inv.inventory_id,
            "source_donation_id":  inv.source_donation_id,
            "usage_amount_kg":     float(inv.usage_amount_kg),
            "weight_before_kg":    float(inv.weight_before_kg),
            "current_weight_kg":   float(inv.current_weight_kg),
            "lifecycle_status":    inv.lifecycle_status,
            "exit_state":          inv.exit_state,
            "is_upcyclable":       inv.is_upcyclable,
            "low_stock_threshold": float(inv.low_stock_threshold),
            "was_forced_archived": inv.was_forced_archived,
            "ingested_at":         inv.ingested_at.isoformat(),
            "updated_at":          inv.updated_at.isoformat(),
            "archived_at":         inv.archived_at.isoformat() if inv.archived_at else None,
            "notes":               inv.notes,
        })
    return rows
