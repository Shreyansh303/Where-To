from typing import Literal

from pydantic import BaseModel

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
    interest_tags: list[str] = []  # which user interests surfaced this POI
    est_visit_minutes: int = 90

    @property
    def value_score(self) -> float:
        """Rating weighted by interest match; the solver drops lowest-value
        POIs first when a day overflows."""
        base = self.rating if self.rating is not None else 3.0
        return base * (1.0 + 0.3 * len(self.interest_tags))
