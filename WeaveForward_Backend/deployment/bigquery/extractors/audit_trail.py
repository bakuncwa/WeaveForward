"""Extract all audit trail events."""


def extract() -> list[dict]:
    from backend.models import AuditTrail

    rows = []
    for a in AuditTrail.objects.select_related("actor").order_by("audit_id"):
        rows.append({
            "audit_id":        a.audit_id,
            "actor_id":        a.actor_id,
            "actor_role":      a.actor.role,
            "entity_type":     a.entity_type,
            "action":          a.action,
            "fields_modified": a.fields_modified,
            "ip_address":      a.ip_address,
            "occurred_at":     a.occurred_at.isoformat(),
        })
    return rows
