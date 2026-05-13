import json
import os
from math import radians, cos, sin, asin, sqrt
from django.conf import settings

# Global cache for NCR features to avoid re-reading disk
_ncr_features_cache = None

def _ray_cast(lon, lat, ring):
    """Return True if (lon, lat) is inside a polygon ring."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def _in_polygon(lon, lat, rings):
    """Polygon: inside outer ring and outside all hole rings."""
    if not _ray_cast(lon, lat, rings[0]):
        return False
    for hole in rings[1:]:
        if _ray_cast(lon, lat, hole):
            return False
    return True

def _in_geometry(lon, lat, geometry):
    """Check point against a GeoJSON Polygon or MultiPolygon."""
    if geometry["type"] == "Polygon":
        return _in_polygon(lon, lat, geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return any(_in_polygon(lon, lat, rings) for rings in geometry["coordinates"])
    return False

def load_ncr_features():
    """
    Load the NCR GeoJSON file from the data folder.
    """
    global _ncr_features_cache
    if _ncr_features_cache is not None:
        return _ncr_features_cache

    path = os.path.join(settings.BASE_DIR, "backend", "data", "ncr_barangays_geojson.geojson")
    
    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as f:
        gj = json.load(f)

    _ncr_features_cache = [
        (feat["geometry"], feat["properties"].get("adm4_en"), feat["properties"].get("city"))
        for feat in gj["features"]
        if feat["properties"].get("adm4_en") is not None
    ]
    return _ncr_features_cache

def get_city_and_barangay(lat, lon):
    """
    Given lat/lon, return {'barangay': str, 'city': str} or None if outside NCR.
    """
    # Convert to float to avoid Decimal vs float math errors
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    features = load_ncr_features()
    for geometry, barangay, city in features:
        if _in_geometry(lon, lat, geometry):
            return {"barangay": barangay, "city": city}
    return None

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance in kilometers between two points 
    on the earth (specified in decimal degrees).
    """
    # Convert decimal degrees to radians 
    try:
        lon1, lat1, lon2, lat2 = map(radians, [float(lon1), float(lat1), float(lon2), float(lat2)])
    except (TypeError, ValueError):
        return None

    # Haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r
