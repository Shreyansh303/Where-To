"""Geo helpers — the deterministic fallback when the Routes API degrades."""

import math

from ..models import LatLng

# Effective in-city speed (transit + walking to/from stops), used only for
# *flagged* estimates when real routing data is unavailable.
FALLBACK_CITY_SPEED_KMH = 15.0


def haversine_km(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def estimate_travel_minutes(a: LatLng, b: LatLng, speed_kmh: float = FALLBACK_CITY_SPEED_KMH) -> int:
    return max(1, round(haversine_km(a, b) / speed_kmh * 60))
