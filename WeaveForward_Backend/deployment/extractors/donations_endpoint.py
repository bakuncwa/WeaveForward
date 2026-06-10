"""Extract all donations via GET /api/donations (admin sees all statuses)."""
import os
import requests
from .base import paginate


def extract(session: requests.Session) -> list[dict]:
    base = os.environ["API_BASE_URL"].rstrip("/")
    raw  = paginate(session, f"{base}/donations", params={"page_size": 100})

    rows = []
    for d in raw:
        donor        = d.get("donor") or {}
        claimed_tuab = d.get("claimed_by_tuab") or {}
        rows.append({
            "donation_id":                   d.get("donation_id"),
            "donor_id":                      donor.get("user_id"),
            "claimed_by_tuab_id":            claimed_tuab.get("user_id"),
            "status":                        d.get("status"),
            "is_flagged":                    d.get("is_flagged"),
            "flag_reason":                   d.get("flag_reason"),
            "delivery_method":               d.get("delivery_method"),
            "rejection_reason":              d.get("rejection_reason"),
            "pickup_city":                   d.get("pickup_city"),
            "pickup_barangay":               d.get("pickup_barangay"),
            "pickup_display_address":        d.get("pickup_display_address"),
            "pickup_latitude":               d.get("pickup_latitude"),
            "pickup_longitude":              d.get("pickup_longitude"),
            "preferred_pickup_date":         d.get("preferred_pickup_date"),
            "preferred_pickup_window_start": d.get("preferred_pickup_window_start"),
            "preferred_pickup_window_end":   d.get("preferred_pickup_window_end"),
            "auto_archive_at":               d.get("auto_archive_at"),
            "submitted_at":                  d.get("submitted_at"),
            "updated_at":                    d.get("updated_at"),
        })
    return rows
