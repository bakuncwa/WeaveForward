# NOTE: This is a draft and only accepts donation_id. 
# It can be changed to accept TUAB IDs instead to work with a future match-predictions endpoint.
import os, json, logging, math, pandas as pd
from django.db import transaction
from django.conf import settings
from backend.models import User, DonationItem, MatchPrediction, UserAccountStatus, SubscriptionStatus, SubscriptionTier

logger = logging.getLogger(__name__)

BIO_FIBERS = frozenset([
    "cotton", "linen", "hemp", "wool", "silk",
    "bamboo", "tencel", "lyocell", "modal",
    "cashmere", "viscose", "rayon", "denim",
    "alpaca",
])

class MatchPredictionService:
    _model, _metadata = None, None

    @classmethod
    def load_model(cls):
        if not cls._model:
            import catboost as cb
            m_dir = os.path.join(settings.BASE_DIR, 'backend', 'models')
            with open(os.path.join(m_dir, 'fiber_match_metadata.json')) as f: cls._metadata = json.load(f)
            cls._model = cb.CatBoostClassifier().load_model(os.path.join(m_dir, 'catboost_fiber_match.cbm'))

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

    @classmethod
    def _compute_biodeg_score(cls, fiber_json):
        total = sum(fiber_json.values())
        if total <= 0:
            return 30.0
        weighted = sum(cls._safe_float(cls._metadata["biodeg_scores"].get(fiber, 30.0), 30.0) * pct for fiber, pct in fiber_json.items())
        return round(weighted / total, 2)

    @staticmethod
    def _compute_biodeg_tier(score):
        if score >= 80:
            return "high"
        if score >= 50:
            return "medium"
        return "low"

    @classmethod
    def _compute_bio_share(cls, fiber_json):
        total = sum(fiber_json.values())
        if total <= 0:
            return 0.0
        bio_total = sum(pct for fiber, pct in fiber_json.items() if fiber in BIO_FIBERS)
        return round((bio_total / total) * 100, 2)

    @classmethod
    def _normalize_item_payload(cls, item):
        fiber_json = json.loads(item["lookup__fiber_json"]) if item["lookup__fiber_json"] else {}
        normalized_fibers = {
            cls._clean_text(k, "unknown"): min(cls._safe_float(v), 100.0)
            for k, v in fiber_json.items()
        }
        biodeg_score = cls._compute_biodeg_score(normalized_fibers)
        dominant_fiber_lookup = max(normalized_fibers, key=normalized_fibers.get) if normalized_fibers else "unknown"
        if dominant_fiber_lookup not in cls._metadata["fiber_vocab"]:
            dominant_fiber_lookup = "other"

        return {
            "item_id": item["item_id"],
            "weight_kg": cls._safe_float(item["weight_kg"]),
            "pickup_latitude": cls._safe_float(item["donation__pickup_latitude"]),
            "pickup_longitude": cls._safe_float(item["donation__pickup_longitude"]),
            "pickup_latitude_rad": math.radians(cls._safe_float(item["donation__pickup_latitude"])),
            "pickup_longitude_rad": math.radians(cls._safe_float(item["donation__pickup_longitude"])),
            "lookup_brand": cls._clean_text(item["lookup__brand"], "unknown"),
            "lookup_clothing_type": cls._clean_text(item["lookup__clothing_type"], "unknown"),
            "lookup_dominant_fiber": dominant_fiber_lookup,
            "pickup_city": cls._clean_text(item["donation__pickup_city"], "manila"),
            "pickup_barangay": cls._clean_text(item["donation__pickup_barangay"], "unknown"),
            "biodeg_score": biodeg_score,
            "biodeg_tier": cls._compute_biodeg_tier(biodeg_score),
            "fiber_json": normalized_fibers,
            "most_dominant_fiber": max(normalized_fibers, key=normalized_fibers.get) if normalized_fibers else "unknown",
            "fs_bio_share": cls._compute_bio_share(normalized_fibers),
        }

    @classmethod
    def _normalize_tuab_payload(cls, tuab):
        targets = [t.strip().lower() for t in (tuab["target_fibers"] or "").split(",") if t.strip()]
        return {
            "tuab_id": tuab["user_id"],
            "target_fibers": targets,
            "target_fibers_str": ",".join(targets) if targets else "unknown",
            "latitude": cls._safe_float(tuab["latitude"]),
            "longitude": cls._safe_float(tuab["longitude"]),
            "latitude_rad": math.radians(cls._safe_float(tuab["latitude"])),
            "longitude_rad": math.radians(cls._safe_float(tuab["longitude"])),
            "artisan_min_biodeg": cls._safe_float(tuab["min_biodeg_score"]),
            "artisan_max_dist_km": cls._safe_float(tuab["max_distance_km"]),
        }

    @classmethod
    def _build_pair_features(cls, item, tuab):
        meta = cls._metadata
        fiber_json = item["fiber_json"]
        targets = [fiber for fiber in tuab["target_fibers"] if fiber in meta["fiber_vocab"]]

        delta_lat = tuab["latitude_rad"] - item["pickup_latitude_rad"]
        delta_lon = tuab["longitude_rad"] - item["pickup_longitude_rad"]
        a = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(item["pickup_latitude_rad"]) * math.cos(tuab["latitude_rad"]) * math.sin(delta_lon / 2) ** 2
        )
        a = min(max(a, 0.0), 1.0)
        distance_km = round(6371 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))), 3)

        if targets:
            matched_fiber = max(targets, key=lambda fiber: fiber_json.get(fiber, 0.0))
            pct_target_fiber = max(fiber_json.get(fiber, 0.0) for fiber in targets)
        else:
            matched_fiber = "none"
            pct_target_fiber = 0.0

        pct_bio_lookup = min(
            sum(fiber_json.get(fiber, 0.0) for fiber in meta["fiber_vocab"] if fiber in BIO_FIBERS),
            100.0,
        )

        feats = {f"pct_{fiber}": fiber_json.get(fiber, 0.0) for fiber in meta["fiber_vocab"]}
        feats.update({
            # Highest single accepted-fiber percentage for this TUAB/item pair.
            "pct_target_fiber": pct_target_fiber,
            # Donor pickup-to-TUAB haversine distance in kilometers.
            "distance_km": distance_km,
            # Donor pickup coordinates.
            "latitude": item["pickup_latitude"],
            "longitude": item["pickup_longitude"],
            # Donated garment weight in kilograms.
            "weight_kg": item["weight_kg"],
            # TUAB acceptance thresholds.
            "artisan_min_biodeg": tuab["artisan_min_biodeg"],
            "artisan_max_dist_km": tuab["artisan_max_dist_km"],
            # Composition-derived biodegradability features for the garment.
            "biodeg_score": item["biodeg_score"],
            "biodeg_tier": item["biodeg_tier"],
            "pct_bio_lookup": round(pct_bio_lookup, 4),
            "fs_bio_share": item["fs_bio_share"],
            # Garment identity and composition categoricals.
            "brand": item["lookup_brand"],
            "clothing_type": item["lookup_clothing_type"],
            "dominant_fiber_lookup": item["lookup_dominant_fiber"],
            "most_dominant_fiber": item["most_dominant_fiber"],
            "matched_fiber": matched_fiber,
            "biodeg_target_fiber": cls._safe_float(meta["biodeg_scores"].get(matched_fiber, 30.0), 30.0),
            # Donor location and TUAB target-fiber context.
            "ncr_city": item["pickup_city"],
            "barangay": item["pickup_barangay"],
            "artisan_target_fibers_str": tuab["target_fibers_str"],
            # Present in the trained schema, but unavailable in the current backend data.
            "source": "unknown",
        })

        for column in meta["feature_cols"]:
            if column not in feats:
                feats[column] = "unknown" if column in meta["cat_features"] else 0.0
        return feats

    @classmethod
    def build_features(cls, item, tuab):
        cls.load_model()
        normalized_item = cls._normalize_item_payload({
            "item_id": item.item_id,
            "weight_kg": item.weight_kg,
            "lookup__fiber_json": item.lookup.fiber_json,
            "lookup__brand": item.lookup.brand,
            "lookup__clothing_type": item.lookup.clothing_type,
            "lookup__dominant_fiber": item.lookup.dominant_fiber,
            "donation__pickup_latitude": item.donation.pickup_latitude,
            "donation__pickup_longitude": item.donation.pickup_longitude,
            "donation__pickup_city": item.donation.pickup_city,
            "donation__pickup_barangay": item.donation.pickup_barangay,
        })
        normalized_tuab = cls._normalize_tuab_payload({
            "user_id": tuab.user_id,
            "target_fibers": tuab.target_fibers,
            "latitude": tuab.latitude,
            "longitude": tuab.longitude,
            "min_biodeg_score": tuab.min_biodeg_score,
            "max_distance_km": tuab.max_distance_km,
        })
        return cls._build_pair_features(normalized_item, normalized_tuab)

def run_predictions_for_donation(donation_id):
    MatchPredictionService.load_model()
    items = [
        MatchPredictionService._normalize_item_payload(item)
        for item in DonationItem.objects.filter(donation_id=donation_id, is_archived=False).values(
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
    ]
    tuabs = [
        MatchPredictionService._normalize_tuab_payload(tuab)
        for tuab in User.objects.filter(
            role="TUAB", 
            status=UserAccountStatus.ACTIVE,
            subscriptions__status=SubscriptionStatus.ACTIVE,
            subscriptions__subscription_tier=SubscriptionTier.PRO
        ).distinct().values(
            "user_id",
            "target_fibers",
            "latitude",
            "longitude",
            "min_biodeg_score",
            "max_distance_km",
        )
    ]
    if not items or not tuabs:
        return []

    meta = MatchPredictionService._metadata
    feature_rows = []
    pair_data = []
    for item in items:
        for tuab in tuabs:
            feats = MatchPredictionService._build_pair_features(item, tuab)
            feature_rows.append(feats)
            pair_data.append((
                item["item_id"],
                tuab["tuab_id"],
                feats["pct_target_fiber"],
                feats["biodeg_target_fiber"],
                feats["distance_km"],
            ))

    df = pd.DataFrame.from_records(feature_rows, columns=meta["feature_cols"])
    for column in meta["cat_features"]:
        df[column] = df[column].fillna("unknown").astype(str)
    numeric_cols = [column for column in meta["feature_cols"] if column not in meta["cat_features"]]
    for column in numeric_cols:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

    probs = MatchPredictionService._model.predict_proba(df)[:, 1]
    thresh = meta.get("fiber_match_threshold", 85.0) / 100.0
    sorted_indexes = sorted(range(len(pair_data)), key=probs.__getitem__, reverse=True)
    preds = [
        MatchPrediction(
            item_id=pair_data[index][0],
            tuab_id=pair_data[index][1],
            is_match=probs[index] >= thresh,
            match_prob=float(probs[index]),
            pct_target_fiber=pair_data[index][2],
            biodeg_target_fiber=pair_data[index][3],
            distance_km=pair_data[index][4],
            is_archived_version=False,
        )
        for index in sorted_indexes
    ]

    item_ids = [item["item_id"] for item in items]
    with transaction.atomic():
        MatchPrediction.objects.filter(item_id__in=item_ids, is_archived_version=False).update(is_archived_version=True)
        MatchPrediction.objects.bulk_create(preds, batch_size=2000)

    return preds
