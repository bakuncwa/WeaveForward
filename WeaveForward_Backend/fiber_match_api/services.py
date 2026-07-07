import os, json, logging, math, pandas as pd

logger = logging.getLogger(__name__)

def expand_fibers(fiber_json, fiber_vocab):
    return {f"pct_{fiber}": fiber_json.get(fiber, 0.0) for fiber in fiber_vocab}

BIO_FIBERS = frozenset([
    "cotton", "linen", "hemp", "wool", "silk",
    "bamboo", "tencel", "lyocell", "modal",
    "cashmere", "viscose", "rayon", "denim",
    "alpaca",
])

class InferenceService:
    _model, _metadata = None, None

    @classmethod
    def load_model(cls):
        if not cls._model:
            try:
                import catboost as cb
                m_dir = os.environ["DJANGO_ML_DIR"]
                with open(os.path.join(m_dir, "fiber_match_metadata.json")) as f:
                    cls._metadata = json.load(f)
                cls._model = cb.CatBoostClassifier().load_model(
                    os.path.join(m_dir, "catboost_fiber_match.cbm")
                )
            except Exception as e:
                raise ValueError("Prediction model is unavailable.") from e

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
        cls.load_model()
        total = sum(fiber_json.values())
        if total <= 0:
            return 30.0
        weighted = sum(
            cls._safe_float(cls._metadata["biodeg_scores"].get(fiber, 30.0), 30.0) * pct
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

    @classmethod
    def _compute_bio_share(cls, fiber_json):
        total = sum(fiber_json.values())
        if total <= 0:
            return 0.0
        bio_total = sum(pct for fiber, pct in fiber_json.items() if fiber in BIO_FIBERS)
        return round((bio_total / total) * 100, 2)

    @classmethod
    def _normalize_item_payload(cls, item):
        cls.load_model()
        fiber_json = json.loads(item["fiber_json"]) if item.get("fiber_json") else {}
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
            "pickup_latitude": cls._safe_float(item.get("pickup_latitude")),
            "pickup_longitude": cls._safe_float(item.get("pickup_longitude")),
            "pickup_latitude_rad": math.radians(cls._safe_float(item.get("pickup_latitude"))),
            "pickup_longitude_rad": math.radians(cls._safe_float(item.get("pickup_longitude"))),
            "lookup_brand": cls._clean_text(item.get("brand"), "unknown"),
            "lookup_clothing_type": cls._clean_text(item.get("clothing_type"), "unknown"),
            "lookup_dominant_fiber": dominant_fiber_lookup,
            "pickup_city": cls._clean_text(item.get("pickup_city"), "manila"),
            "pickup_barangay": cls._clean_text(item.get("pickup_barangay"), "unknown"),
            "biodeg_score": biodeg_score,
            "biodeg_tier": cls._compute_biodeg_tier(biodeg_score),
            "fiber_json": normalized_fibers,
            "most_dominant_fiber": max(normalized_fibers, key=normalized_fibers.get) if normalized_fibers else "unknown",
            "fs_bio_share": cls._compute_bio_share(normalized_fibers),
        }

    @classmethod
    def _normalize_tuab_payload(cls, tuab):
        cls.load_model()
        targets = [t.strip().lower() for t in (tuab.get("target_fibers") or "").split(",") if t.strip()]
        sorted_targets = sorted(targets)
        return {
            "tuab_id": tuab["user_id"],
            "target_fibers": targets,
            "target_fibers_str": ",".join(sorted_targets) if sorted_targets else "unknown",
            "latitude": cls._safe_float(tuab.get("latitude")),
            "longitude": cls._safe_float(tuab.get("longitude")),
            "latitude_rad": math.radians(cls._safe_float(tuab.get("latitude"))),
            "longitude_rad": math.radians(cls._safe_float(tuab.get("longitude"))),
            "artisan_min_biodeg": cls._safe_float(tuab.get("min_biodeg_score")),
            "artisan_max_dist_km": cls._safe_float(tuab.get("max_distance_km")),
        }

    @classmethod
    def _build_pair_features(cls, item, tuab):
        cls.load_model()
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

        feats = expand_fibers(fiber_json, meta["fiber_vocab"])
        feats.update({
            "pct_target_fiber": pct_target_fiber,
            "distance_km": distance_km,
            "latitude": item["pickup_latitude"],
            "longitude": item["pickup_longitude"],
            "weight_kg": item["weight_kg"],
            "artisan_min_biodeg": tuab["artisan_min_biodeg"],
            "artisan_max_dist_km": tuab["artisan_max_dist_km"],
            "biodeg_score": item["biodeg_score"],
            "biodeg_tier": item["biodeg_tier"],
            "pct_bio_lookup": round(pct_bio_lookup, 4),
            "fs_bio_share": item["fs_bio_share"],
            "brand": item["lookup_brand"],
            "clothing_type": item["lookup_clothing_type"],
            "dominant_fiber_lookup": item["lookup_dominant_fiber"],
            "most_dominant_fiber": item["most_dominant_fiber"],
            "matched_fiber": matched_fiber,
            "biodeg_target_fiber": cls._safe_float(meta["biodeg_scores"].get(matched_fiber, 30.0), 30.0),
            "ncr_city": item["pickup_city"],
            "barangay": item["pickup_barangay"],
            "artisan_target_fibers_str": tuab["target_fibers_str"],
            "source": "unknown",
        })

        for column in meta["feature_cols"]:
            if column not in feats:
                feats[column] = "unknown" if column in meta["cat_features"] else 0.0
        return feats

    @classmethod
    def infer(cls, items, tuabs):
        cls.load_model()
        if not items or not tuabs:
            return []

        normalized_items = [cls._normalize_item_payload(item) for item in items]
        normalized_tuabs = [cls._normalize_tuab_payload(tuab) for tuab in tuabs]

        meta = cls._metadata
        feature_rows = []
        pair_data = []
        for item in normalized_items:
            for tuab in normalized_tuabs:
                feats = cls._build_pair_features(item, tuab)
                feature_rows.append(feats)
                pair_data.append({
                    "item_id": item["item_id"],
                    "tuab_id": tuab["tuab_id"],
                    "pct_target_fiber": feats["pct_target_fiber"],
                    "biodeg_target_fiber": feats["biodeg_target_fiber"],
                    "distance_km": feats["distance_km"],
                    "artisan_min_biodeg": feats["artisan_min_biodeg"],
                    "artisan_max_dist_km": feats["artisan_max_dist_km"],
                })

        df = pd.DataFrame.from_records(feature_rows, columns=meta["feature_cols"])
        for column in meta["cat_features"]:
            df[column] = df[column].fillna("unknown").astype(str)
        numeric_cols = [column for column in meta["feature_cols"] if column not in meta["cat_features"]]
        for column in numeric_cols:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

        probs = cls._model.predict_proba(df)[:, 1]

        sorted_indexes = sorted(range(len(pair_data)), key=probs.__getitem__, reverse=True)
        results = []
        for idx in sorted_indexes:
            pair = pair_data[idx]
            results.append({
                "item_id": pair["item_id"],
                "tuab_id": pair["tuab_id"],
                "is_match": bool(probs[idx] >= 0.5),
                "match_prob": float(round(probs[idx], 5)),
                "pct_target_fiber": float(pair["pct_target_fiber"]),
                "biodeg_target_fiber": float(pair["biodeg_target_fiber"]),
                "distance_km": float(pair["distance_km"]),
            })
        return results
