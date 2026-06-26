import json
from decimal import Decimal
from ..models import BrandFiberLookup
from .prediction_service import MatchPredictionService

def get_allowed_fibers():
    """Returns a set of lowercase unique fiber keys from the DB."""
    fibers_set = set()
    raw_jsons = BrandFiberLookup.objects.filter(is_active=True).values_list('fiber_json', flat=True)
    for fj in raw_jsons:
        try:
            data = json.loads(fj)
            if isinstance(data, dict):
                fibers_set.update(k.lower().strip() for k in data.keys())
        except:
            continue
    return fibers_set


def fiber_approximation(brand, clothing_type):
    """Infer fiber composition for unknown (brand, clothing_type) using tiered strategy."""
    if not brand or not clothing_type:
        raise ValueError("brand and clothing_type are required")

    # Tier 1: Exact brand + clothing_type
    exact = BrandFiberLookup.objects.filter(brand__iexact=brand, clothing_type__iexact=clothing_type).order_by('-scraped_at').first()
    if exact:
        return exact

    # Tier 2: Brand found, any type (scraped only)
    brand_match = BrandFiberLookup.objects.filter(brand__iexact=brand, is_active=True).order_by('-scraped_at').first()
    if brand_match:
        return _create_lookup(brand_match.brand, clothing_type.lower(), json.loads(brand_match.fiber_json))

    # Tier 3: Type found, any brand
    type_qs = BrandFiberLookup.objects.filter(clothing_type__iexact=clothing_type, is_active=True)
    first = type_qs.first()
    if first:
        return _create_lookup(brand, first.clothing_type, _compute_median(type_qs))

    # Tier 4: Global median (scraped records only)
    return _create_lookup(brand, clothing_type.lower(), _compute_median(BrandFiberLookup.objects.filter(is_active=True)))


def _compute_median(qs):
    """Compute median fiber percentage across a queryset, then normalize to 100%."""

    # ---- Prevalence Filter ----
    # A fiber must appear in at least 20% of records to be included.
    # This prevents rare/noisy fibers (e.g. 0.2% elastane in 1 of 50 shirts)
    # from polluting the auto-approximated profile.
    MIN_PREVALENCE = 0.20

    values = {}
    for obj in qs.iterator():
        try:
            data = json.loads(obj.fiber_json)
            if not isinstance(data, dict):
                continue
            for fiber, pct in data.items():
                fiber = fiber.lower().strip()
                values.setdefault(fiber, []).append(float(pct))
        except (json.JSONDecodeError, AttributeError, ValueError):
            continue

    total_records = qs.count()

    profile = {}
    for fiber, pcts in values.items():
        if len(pcts) / total_records < MIN_PREVALENCE:
            continue
        pcts.sort()
        n = len(pcts)
        median = pcts[n // 2] if n % 2 else (pcts[n // 2 - 1] + pcts[n // 2]) / 2
        if median > 2:
            profile[fiber] = round(median, 1)

    total = sum(profile.values())
    if total > 0:
        profile = {k: round(v / total * 100, 1) for k, v in profile.items()}
    return profile


def _create_lookup(brand, clothing_type, fiber_dict):
    """Create a new BrandFiberLookup with inferred fiber data."""
    fiber_json_str = json.dumps(fiber_dict)
    dominant = max(fiber_dict, key=fiber_dict.get) if fiber_dict else None
    score = MatchPredictionService._compute_biodeg_score(fiber_dict) if fiber_dict else 30.0
    tier = MatchPredictionService._compute_biodeg_tier(score).upper()

    return BrandFiberLookup.objects.create(
        product_name=f"{clothing_type} from {brand}"[:100],
        brand=brand[:200],
        clothing_type=clothing_type[:200],
        fiber_json=fiber_json_str,
        dominant_fiber=dominant[:200] if dominant else None,
        biodeg_score=Decimal(str(score)),
        biodeg_tier=tier,
        is_active=False,
    )
