"""Extract brand-fiber catalog via GET /api/brandfiberlookups."""
import os
import requests
from .base import paginate


def extract(session: requests.Session) -> list[dict]:
    base = os.environ["API_BASE_URL"].rstrip("/")
    raw  = paginate(session, f"{base}/brandfiberlookups", params={"page_size": 500})

    rows = []
    for b in raw:
        fiber_json = b.get("fiber_json", "{}")
        import json
        if isinstance(fiber_json, dict):
            fiber_json = json.dumps(fiber_json)
        rows.append({
            "lookup_id":      b.get("lookup_id"),
            "category":       b.get("category"),
            "brand":          b.get("brand"),
            "clothing_type":  b.get("clothing_type"),
            "fiber_json":     fiber_json,
            "dominant_fiber": b.get("dominant_fiber"),
            "biodeg_score":   b.get("biodeg_score"),
            "biodeg_tier":    b.get("biodeg_tier"),
            "is_active":      b.get("is_active"),
            "scraped_at":     b.get("scraped_at"),
        })
    return rows
