import math
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, computed_field

from .core import LatLng, OpeningHours


class POI(BaseModel):
    id: str  # grounding id, e.g. "poi_7" / "rest_3"
    place_id: str  # Google Places id — the provenance link back to the API
    name: str
    kind: Literal["attraction", "restaurant"]
    location: LatLng
    rating: float | None = None
    review_count: int | None = None
    types: list[str] = []
    price_level: int | None = None  # 0 (free) … 4
    address: str | None = None
    opening_hours: OpeningHours | None = None
    est_visit_minutes: int = 90

    @property
    def value_score(self) -> float:
        """Rating weighted by popularity (review volume), so world-famous,
        must-see landmarks outrank obscure high-rated spots. The solver drops
        lowest-value POIs first when a day overflows."""
        base = self.rating if self.rating is not None else 3.0
        popularity = math.log10((self.review_count or 0) + 10)  # ~1 … 6+
        return base * popularity

    @computed_field  # serialized into API responses for the frontend link chip
    @property
    def maps_url(self) -> str:
        base = f"https://www.google.com/maps/search/?api=1&query={quote(self.name)}"
        return f"{base}&query_place_id={self.place_id}" if self.place_id else base
