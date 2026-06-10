"""Extract all match prediction records (current and archived versions)."""


def extract() -> list[dict]:
    from backend.models import MatchPrediction

    qs = MatchPrediction.objects.select_related("item", "item__donation", "tuab").order_by("pair_id")

    rows = []
    for p in qs:
        rows.append({
            "pair_id":               p.pair_id,
            "item_id":               p.item_id,
            "donation_id":           p.item.donation_id,
            "tuab_id":               p.tuab_id,
            "is_match":              p.is_match,
            "match_prob":            float(p.match_prob),
            "pct_target_fiber":      float(p.pct_target_fiber)    if p.pct_target_fiber    is not None else None,
            "biodeg_target_fiber":   float(p.biodeg_target_fiber) if p.biodeg_target_fiber is not None else None,
            "distance_km":           float(p.distance_km)         if p.distance_km         is not None else None,
            "is_archived_version":   p.is_archived_version,
            "recommendation_status": p.recommendation_status,
            "tuab_rejection_reason": p.tuab_rejection_reason,
            "predicted_at":          p.predicted_at.isoformat(),
        })
    return rows
