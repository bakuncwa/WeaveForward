import json
from ..models import BrandFiberLookup

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
