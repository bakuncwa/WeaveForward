"""Extract donation items flattened from GET /api/donations detail responses."""
import os
import json
import requests
from .base import paginate


def extract(session: requests.Session) -> list[dict]:
    base      = os.environ["API_BASE_URL"].rstrip("/")
    donations = paginate(session, f"{base}/donations", params={"page_size": 100})

    rows = []
    for d in donations:
        donation_id = d.get("donation_id")
        for item in d.get("items", []):
            lookup = item.get("lookup_details") or {}
            fiber_json = lookup.get("fiber_json", "{}")
            if isinstance(fiber_json, dict):
                fiber_json = json.dumps(fiber_json)
            rows.append({
                "item_id":          item.get("item_id"),
                "donation_id":      donation_id,
                "lookup_id":        lookup.get("lookup_id"),
                "brand":            lookup.get("brand"),
                "clothing_type":    lookup.get("clothing_type"),
                "dominant_fiber":   lookup.get("dominant_fiber"),
                "fiber_json":       fiber_json,
                "biodeg_score":     lookup.get("biodeg_score"),
                "biodeg_tier":      lookup.get("biodeg_tier"),
                "condition_rating": item.get("condition_rating"),
                "weight_kg":        item.get("weight_kg"),
                "is_archived":      item.get("is_archived", False),
            })
    return rows
