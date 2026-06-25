import os, logging, requests
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from ..models import (
    User, Donation, DonationItem, MatchPrediction,
    MatchRecommendationStatus, UserAccountStatus,
    SubscriptionStatus, SubscriptionTier, DonationStatus,
)

logger = logging.getLogger(__name__)

BIO_FIBERS = frozenset([
    "cotton", "linen", "hemp", "wool", "silk",
    "bamboo", "tencel", "lyocell", "modal",
    "cashmere", "viscose", "rayon", "denim",
    "alpaca",
])

BIODEG_SCORES = {
    "cotton": 92, "linen": 95, "hemp": 96, "denim": 78,
    "tencel": 91, "lyocell": 91, "modal": 76, "bamboo": 73,
    "rayon": 72, "viscose": 72, "silk": 83, "wool": 74,
    "cashmere": 74, "alpaca": 73, "nylon": 12, "polyester": 8,
    "acrylic": 5, "elastane": 4, "spandex": 4, "lycra": 4,
}

class MatchPredictionService:
    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            return float(value if value is not None else default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_text(value, default):
        text = str(value).strip().lower() if value is not None else ""
        return text or default

    @staticmethod
    def _compute_biodeg_score(fiber_json):
        total = sum(fiber_json.values())
        if total <= 0:
            return 30.0
        weighted = sum(
            MatchPredictionService._safe_float(BIODEG_SCORES.get(fiber, 30.0), 30.0) * pct
            for fiber, pct in fiber_json.items()
        )
        return round(weighted / total, 2)

    @staticmethod
    def _compute_biodeg_tier(score):
        if score >= 80:
            return "high"
        if score >= 50:
            return "medium"
        return "low"


def _json_safe(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _call_fma(items, tuabs):
    clean_items = [
        {
            "item_id": i["item_id"],
            "weight_kg": i["weight_kg"],
            "fiber_json": i["lookup__fiber_json"],
            "brand": i["lookup__brand"],
            "clothing_type": i["lookup__clothing_type"],
            "pickup_latitude": i["donation__pickup_latitude"],
            "pickup_longitude": i["donation__pickup_longitude"],
            "pickup_city": i["donation__pickup_city"],
            "pickup_barangay": i["donation__pickup_barangay"],
        }
        for i in items
    ]
    clean_tuabs = [
        {
            "user_id": t["user_id"],
            "target_fibers": t["target_fibers"],
            "latitude": t["latitude"],
            "longitude": t["longitude"],
            "min_biodeg_score": t["min_biodeg_score"],
            "max_distance_km": t["max_distance_km"],
        }
        for t in tuabs
    ]

    try:
        from fiber_match_api.services import InferenceService
        return InferenceService.infer(clean_items, clean_tuabs)
    except Exception:
        logger.warning("Direct inference failed, falling back to HTTP", exc_info=True)

    port = os.environ.get("PORT", "8000")
    resp = requests.post(
        f"http://localhost:{port}/api/match-predict/",
        json=_json_safe({"items": clean_items, "tuabs": clean_tuabs}),
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["predictions"]


def run_predictions_for_donation(donation_id):
    donation = Donation.objects.get(pk=donation_id)

    if donation.status != DonationStatus.PENDING:
        item_ids = DonationItem.objects.filter(donation_id=donation_id).values_list("item_id", flat=True)
        if item_ids:
            with transaction.atomic():
                MatchPrediction.objects.filter(
                    item_id__in=item_ids, is_archived_version=False
                ).update(is_archived_version=True)
        return []

    items = list(
        DonationItem.objects.filter(donation_id=donation_id, is_archived=False).values(
            "item_id",
            "weight_kg",
            "lookup__fiber_json",
            "lookup__brand",
            "lookup__clothing_type",
            "lookup__dominant_fiber",
            "donation__pickup_latitude",
            "donation__pickup_longitude",
            "donation__pickup_city",
            "donation__pickup_barangay",
        )
    )
    tuabs = list(
        User.objects.filter(
            role="TUAB",
            status=UserAccountStatus.ACTIVE,
            subscriptions__status=SubscriptionStatus.ACTIVE,
            subscriptions__subscription_tier=SubscriptionTier.PRO,
        ).distinct().values(
            "user_id",
            "target_fibers",
            "latitude",
            "longitude",
            "min_biodeg_score",
            "max_distance_km",
        )
    )
    if not items or not tuabs:
        return []

    try:
        predictions = _call_fma(items, tuabs)
    except requests.RequestException as e:
        logger.exception("FiberMatchAPI call failed")
        raise ValueError("AI matching is temporarily unavailable.") from e

    run_timestamp = timezone.now()
    preds = [
        MatchPrediction(
            item_id=p["item_id"],
            tuab_id=p["tuab_id"],
            is_match=p["is_match"],
            match_prob=p["match_prob"],
            pct_target_fiber=p["pct_target_fiber"],
            biodeg_target_fiber=p["biodeg_target_fiber"],
            distance_km=p["distance_km"],
            is_archived_version=False,
            recommendation_status=MatchRecommendationStatus.PENDING,
            predicted_at=run_timestamp,
        )
        for p in predictions
    ]

    def _same_pred(a, b):
        return (
            round(float(a.match_prob or 0), 5) == round(float(b.match_prob or 0), 5)
            and a.is_match == b.is_match
            and round(float(a.pct_target_fiber or 0), 2) == round(float(b.pct_target_fiber or 0), 2)
            and round(float(a.biodeg_target_fiber or 0), 2) == round(float(b.biodeg_target_fiber or 0), 2)
            and round(float(a.distance_km or 0), 3) == round(float(b.distance_km or 0), 3)
        )

    item_ids = [i["item_id"] for i in items]
    existing = {
        (p.item_id, p.tuab_id): p
        for p in MatchPrediction.objects.filter(
            item_id__in=item_ids, is_archived_version=False
        )
    }
    to_archive = set()
    to_create = []
    for p in preds:
        key = (p.item_id, p.tuab_id)
        old = existing.get(key)
        if old and _same_pred(old, p):
            continue
        if old:
            to_archive.add(old.pk)
        to_create.append(p)

    with transaction.atomic():
        if to_archive:
            MatchPrediction.objects.filter(pk__in=to_archive).update(is_archived_version=True)
        if to_create:
            MatchPrediction.objects.bulk_create(to_create, batch_size=2000)

    return preds


def run_predictions_for_donation_for_one_tuab(tuab):
    items = list(
        DonationItem.objects.filter(
            donation__status=DonationStatus.PENDING,
            is_archived=False,
        ).values(
            "item_id",
            "weight_kg",
            "lookup__fiber_json",
            "lookup__brand",
            "lookup__clothing_type",
            "lookup__dominant_fiber",
            "donation__pickup_latitude",
            "donation__pickup_longitude",
            "donation__pickup_city",
            "donation__pickup_barangay",
        )
    )
    tuabs = [
        {
            "user_id": tuab.user_id,
            "target_fibers": tuab.target_fibers,
            "latitude": tuab.latitude,
            "longitude": tuab.longitude,
            "min_biodeg_score": tuab.min_biodeg_score,
            "max_distance_km": tuab.max_distance_km,
        }
    ]
    if not items or not tuabs:
        return []

    try:
        predictions = _call_fma(items, tuabs)
    except requests.RequestException as e:
        logger.exception("FiberMatchAPI call failed")
        raise ValueError("AI matching is temporarily unavailable.") from e

    run_timestamp = timezone.now()
    preds = [
        MatchPrediction(
            item_id=p["item_id"],
            tuab_id=p["tuab_id"],
            is_match=p["is_match"],
            match_prob=p["match_prob"],
            pct_target_fiber=p["pct_target_fiber"],
            biodeg_target_fiber=p["biodeg_target_fiber"],
            distance_km=p["distance_km"],
            is_archived_version=False,
            recommendation_status=MatchRecommendationStatus.PENDING,
            predicted_at=run_timestamp,
        )
        for p in predictions
    ]

    with transaction.atomic():
        MatchPrediction.objects.filter(
            tuab_id=tuab.user_id,
            is_archived_version=False,
        ).update(is_archived_version=True)
        MatchPrediction.objects.bulk_create(preds, batch_size=2000)

    return preds
