"""Extract brand-fiber catalog via Django ORM (all entries, active and inactive)."""


def extract() -> list[dict]:
    from backend.models import BrandFiberLookup

    rows = []
    for b in BrandFiberLookup.objects.order_by("lookup_id"):
        rows.append({
            "lookup_id":      b.lookup_id,
            "category":       b.category,
            "brand":          b.brand,
            "clothing_type":  b.clothing_type,
            "fiber_json":     b.fiber_json,
            "dominant_fiber": b.dominant_fiber,
            "biodeg_score":   float(b.biodeg_score) if b.biodeg_score is not None else None,
            "biodeg_tier":    b.biodeg_tier,
            "is_active":      b.is_active,
            "scraped_at":     b.scraped_at.isoformat(),
        })
    return rows
