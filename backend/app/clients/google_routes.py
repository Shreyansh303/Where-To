"""Google Routes API client — builds the travel-time matrix the constraint
solver optimizes over.

`computeRouteMatrix` bills per *element* (origin × destination) and caps
elements per request (100 for TRANSIT), so the matrix is fetched in chunks of
origin rows. Any element the API can't route (or a failed chunk) is filled
with a haversine-based estimate and flagged, so a degraded Routes API never
sinks the whole plan.
"""

from typing import Any

from ..models import LatLng
from ..models.matrix import TravelMatrix
from ..util.geo import estimate_travel_minutes
from .base import ApiError, BaseClient

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
MAX_ELEMENTS_PER_REQUEST = 100


def _waypoint(p: LatLng) -> dict[str, Any]:
    return {"waypoint": {"location": {"latLng": {"latitude": p.lat, "longitude": p.lng}}}}


class RoutesClient(BaseClient):
    service = "routes"

    def __init__(self, api_key: str, travel_mode: str = "TRANSIT", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.travel_mode = travel_mode

    def _fetch_chunk(self, origins: list[LatLng], destinations: list[LatLng]) -> Any:
        cache_params = {
            "origins": [[round(p.lat, 5), round(p.lng, 5)] for p in origins],
            "destinations": [[round(p.lat, 5), round(p.lng, 5)] for p in destinations],
            "mode": self.travel_mode,
        }

        def fetch() -> Any:
            return self._request_json(
                "POST",
                MATRIX_URL,
                json_body={
                    "origins": [_waypoint(p) for p in origins],
                    "destinations": [_waypoint(p) for p in destinations],
                    "travelMode": self.travel_mode,
                },
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition",
                    "Content-Type": "application/json",
                },
            )

        return self._cached_json(cache_params, fetch)

    def travel_time_matrix(self, points: list[LatLng]) -> TravelMatrix:
        n = len(points)
        minutes = [[0] * n for _ in range(n)]
        estimated = [[False] * n for _ in range(n)]
        if n <= 1:
            return TravelMatrix(minutes, estimated)

        # Pre-fill everything with flagged estimates; real data overwrites.
        for i in range(n):
            for j in range(n):
                if i != j:
                    minutes[i][j] = estimate_travel_minutes(points[i], points[j])
                    estimated[i][j] = True

        rows_per_chunk = max(1, MAX_ELEMENTS_PER_REQUEST // max(n, 1))
        for start in range(0, n, rows_per_chunk):
            origin_idx = list(range(start, min(start + rows_per_chunk, n)))
            try:
                elements = self._fetch_chunk([points[i] for i in origin_idx], points)
            except ApiError:
                continue  # chunk stays on haversine estimates
            for el in elements or []:
                if "originIndex" not in el or "destinationIndex" not in el:
                    continue
                i = origin_idx[el["originIndex"]] if el["originIndex"] < len(origin_idx) else None
                j = el["destinationIndex"]
                duration = el.get("duration")
                if i is None or j >= n or i == j or not duration:
                    continue
                seconds = int(str(duration).rstrip("s") or 0)
                if seconds > 0:
                    minutes[i][j] = max(1, round(seconds / 60))
                    estimated[i][j] = False
        return TravelMatrix(minutes, estimated)
