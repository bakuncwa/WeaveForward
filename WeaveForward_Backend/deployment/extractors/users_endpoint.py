"""Extract all users via GET /api/users (admin auth required)."""
import os
import requests
from .base import paginate


def extract(session: requests.Session) -> list[dict]:
    base = os.environ["API_BASE_URL"].rstrip("/")
    raw  = paginate(session, f"{base}/users", params={"page_size": 100})

    rows = []
    for u in raw:
        rows.append({
            "user_id":            u.get("user_id"),
            "email":              u.get("email"),
            "role":               u.get("role"),
            "first_name":         u.get("first_name"),
            "last_name":          u.get("last_name"),
            "business_name":      u.get("business_name"),
            "description":        u.get("description"),
            "target_fibers":      u.get("target_fibers"),
            "min_biodeg_score":   u.get("min_biodeg_score"),
            "max_distance_km":    u.get("max_distance_km"),
            "max_active_claims":  u.get("max_active_claims"),
            "operational_status": u.get("operational_status"),
            "status":             u.get("status"),
            "city":               u.get("city"),
            "barangay":           u.get("barangay"),
            "latitude":           u.get("latitude"),
            "longitude":          u.get("longitude"),
            "is_2fa_enabled":     u.get("is_2fa_enabled"),
            "created_at":         u.get("created_at"),
            "updated_at":         u.get("updated_at"),
        })
    return rows
