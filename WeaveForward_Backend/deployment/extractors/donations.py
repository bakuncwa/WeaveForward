"""Extract all donations via Django ORM (all statuses, all fields)."""


def extract() -> list[dict]:
    from backend.models import Donation

    rows = []
    for d in Donation.objects.select_related("donor", "claimed_by_tuab").order_by("donation_id"):
        rows.append({
            "donation_id":                   d.donation_id,
            "donor_id":                      d.donor_id,
            "claimed_by_tuab_id":            d.claimed_by_tuab_id,
            "status":                        d.status,
            "is_flagged":                    d.is_flagged,
            "flag_reason":                   d.flag_reason,
            "delivery_method":               d.delivery_method,
            "rejection_reason":              d.rejection_reason,
            "pickup_city":                   d.pickup_city,
            "pickup_barangay":               d.pickup_barangay,
            "pickup_display_address":        d.pickup_display_address,
            "pickup_latitude":               float(d.pickup_latitude),
            "pickup_longitude":              float(d.pickup_longitude),
            "preferred_pickup_date":         d.preferred_pickup_date.isoformat(),
            "preferred_pickup_window_start": str(d.preferred_pickup_window_start),
            "preferred_pickup_window_end":   str(d.preferred_pickup_window_end),
            "auto_archive_at":               d.auto_archive_at.isoformat() if d.auto_archive_at else None,
            "submitted_at":                  d.submitted_at.isoformat(),
            "updated_at":                    d.updated_at.isoformat(),
        })
    return rows
