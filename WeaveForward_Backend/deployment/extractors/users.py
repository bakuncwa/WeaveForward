"""Extract all users via Django ORM — sensitive columns excluded."""
from django.db.models import Prefetch


def extract() -> list[dict]:
    from backend.models import User, Subscription

    qs = User.objects.prefetch_related(
        Prefetch("subscriptions", queryset=Subscription.objects.order_by("-created_at"), to_attr="_subs")
    ).order_by("user_id")

    rows = []
    for u in qs:
        active_sub = next((s for s in u._subs if s.status == "ACTIVE"), None)
        rows.append({
            "user_id":            u.user_id,
            "email":              u.email,
            "role":               u.role,
            "first_name":         u.first_name,
            "last_name":          u.last_name,
            "business_name":      u.business_name,
            "description":        u.description,
            "target_fibers":      u.target_fibers,
            "min_biodeg_score":   float(u.min_biodeg_score) if u.min_biodeg_score is not None else None,
            "max_distance_km":    float(u.max_distance_km)  if u.max_distance_km  is not None else None,
            "max_active_claims":  u.max_active_claims,
            "operational_status": u.operational_status,
            "status":             u.status,
            "city":               u.city,
            "barangay":           u.barangay,
            "latitude":           float(u.latitude)  if u.latitude  is not None else None,
            "longitude":          float(u.longitude) if u.longitude is not None else None,
            "is_2fa_enabled":     u.is_2fa_enabled,
            "has_active_sub":     active_sub is not None,
            "active_sub_tier":    active_sub.subscription_tier if active_sub else None,
            "created_at":         u.created_at.isoformat(),
            "updated_at":         u.updated_at.isoformat(),
        })
    return rows
