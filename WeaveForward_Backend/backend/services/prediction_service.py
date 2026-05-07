import os, json, logging, math, pandas as pd
from django.conf import settings
from backend.models import User, DonationItem, MatchPrediction, UserAccountStatus

logger = logging.getLogger(__name__)

class MatchPredictionService:
    _model, _metadata = None, None

    @classmethod
    def load_model(cls):
        if not cls._model:
            import catboost as cb
            m_dir = os.path.join(settings.BASE_DIR, 'backend', 'models')
            with open(os.path.join(m_dir, 'fiber_match_metadata.json')) as f: cls._metadata = json.load(f)
            cls._model = cb.CatBoostClassifier().load_model(os.path.join(m_dir, 'catboost_fiber_match.cbm'))

    @classmethod
    def build_features(cls, item, tuab):
        cls.load_model()
        l, d = item.lookup, item.donation
        f_json = json.loads(l.fiber_json) if l.fiber_json else {}
        targets = [t.strip().lower() for t in (tuab.target_fibers or "").split(',') if t.strip()]
        
        feats = {f"pct_{f}": float(f_json.get(f, 0)) for f in cls._metadata['fiber_vocab']}
        feats.update({
            'pct_target_fiber': sum(float(f_json.get(t, 0)) for t in targets),
            'distance_km': 6371 * (2 * math.atan2(math.sqrt(a := math.sin(math.radians(float(tuab.latitude or 0) - float(d.pickup_latitude or 0))/2)**2 + math.cos(math.radians(float(d.pickup_latitude or 0))) * math.cos(math.radians(float(tuab.latitude or 0))) * math.sin(math.radians(float(tuab.longitude or 0) - float(d.pickup_longitude or 0))/2)**2), math.sqrt(1-a))),
            'latitude': float(d.pickup_latitude or 0), 'longitude': float(d.pickup_longitude or 0),
            'weight_kg': float(item.weight_kg or 0), 'artisan_min_biodeg': float(tuab.min_biodeg_score or 0),
            'artisan_max_dist_km': float(tuab.max_distance_km or 0), 'biodeg_score': float(l.biodeg_score or 0),
            'biodeg_tier': (l.biodeg_tier or 'low').lower(), 'brand': (l.brand or 'unknown').lower(),
            'clothing_type': (l.clothing_type or 'unknown').lower(), 'dominant_fiber_lookup': (l.dominant_fiber or 'unknown').lower(),
            'ncr_city': (d.pickup_city or 'unknown').lower(), 'barangay': (d.pickup_barangay or 'unknown').lower(),
            'artisan_target_fibers_str': (tuab.target_fibers or 'unknown').lower(), 'source': 'unknown'
        })
        
        most_dom = max(f_json.items(), key=lambda x: float(x[1]))[0].lower() if f_json else 'unknown'
        m_fibers = [f for f in targets if float(f_json.get(f, 0)) > 0]
        matched = max(m_fibers, key=lambda f: float(f_json.get(f, 0))).lower() if m_fibers else 'none'
        
        feats.update({
            'most_dominant_fiber': most_dom, 'matched_fiber': matched,
            'biodeg_target_fiber': float(cls._metadata['biodeg_scores'].get(matched, 30.0)),
            'pct_bio_lookup': float(l.biodeg_score or 0), 'fs_bio_share': float(l.biodeg_score or 0)
        })
        
        for c in cls._metadata['feature_cols']:
            if c not in feats: feats[c] = 'unknown' if c in cls._metadata['cat_features'] else 0.0
        return feats

def run_predictions_for_donation(donation_id):
    MatchPredictionService.load_model()
    items = list(DonationItem.objects.filter(donation_id=donation_id, is_archived=False))
    tuabs = list(User.objects.filter(role='TUAB', status=UserAccountStatus.ACTIVE))
    if not items or not tuabs: return []

    meta = MatchPredictionService._metadata
    pairs = [(i, t, MatchPredictionService.build_features(i, t)) for i in items for t in tuabs]
    
    df = pd.DataFrame([p[2] for p in pairs])[meta['feature_cols']]
    for c in meta['cat_features']: df[c] = df[c].fillna("unknown").astype(str)
    for c in [f for f in meta['feature_cols'] if f not in meta['cat_features']]:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

    probs = MatchPredictionService._model.predict_proba(df)[:, 1]
    MatchPrediction.objects.filter(item__in=items, is_archived_version=False).update(is_archived_version=True)
    
    thresh = meta.get('fiber_match_threshold', 85.0) / 100.0
    preds = [MatchPrediction(
        item=p[0], tuab=p[1], is_match=probs[i] >= thresh, match_prob=float(probs[i]),
        pct_target_fiber=p[2].get('pct_target_fiber'), biodeg_target_fiber=p[2].get('biodeg_target_fiber'),
        distance_km=p[2].get('distance_km'), is_archived_version=False
    ) for i, p in enumerate(pairs)]
    
    return sorted(MatchPrediction.objects.bulk_create(preds), key=lambda x: x.match_prob, reverse=True)
