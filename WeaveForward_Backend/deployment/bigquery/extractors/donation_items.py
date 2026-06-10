"""Extract all donation items via Django ORM (includes archived)."""
import json


def extract() -> list[dict]:
    from backend.models import DonationItem

    rows = []
    for i in DonationItem.objects.select_related("lookup").order_by("item_id"):
        fiber_json = {}
        if i.lookup and i.lookup.fiber_json:
            try:
                fiber_json = json.loads(i.lookup.fiber_json)
            except (ValueError, TypeError):
                pass

        rows.append({
            "item_id":          i.item_id,
            "donation_id":      i.donation_id,
            "lookup_id":        i.lookup_id,
            "brand":            i.lookup.brand          if i.lookup else None,
            "clothing_type":    i.lookup.clothing_type  if i.lookup else None,
            "dominant_fiber":   i.lookup.dominant_fiber if i.lookup else None,
            "fiber_json":       json.dumps(fiber_json),
            "biodeg_score":     float(i.lookup.biodeg_score) if i.lookup and i.lookup.biodeg_score is not None else None,
            "biodeg_tier":      i.lookup.biodeg_tier    if i.lookup else None,
            "condition_rating": i.condition_rating,
            "weight_kg":        float(i.weight_kg),
            "is_archived":      i.is_archived,
        })
    return rows
