from datetime import date as Date
from typing import Literal

from pydantic import BaseModel


class ItineraryStop(BaseModel):
    poi_id: str
    arrive_min: int  # minutes from midnight
    depart_min: int
    travel_from_prev_minutes: int = 0
    travel_mode: str = "transit"
    travel_is_estimate: bool = False  # True when routes data was degraded
    meal: Literal["breakfast", "lunch", "dinner"] | None = None
    note: str | None = None  # e.g. "opening hours unknown — verify before visiting"


class DroppedPOI(BaseModel):
    poi_id: str
    reason: str


class ItineraryDay(BaseModel):
    date: Date
    weekday: int  # 0=Monday … 6=Sunday
    stops: list[ItineraryStop] = []


class SolverResult(BaseModel):
    days: list[ItineraryDay]
    dropped: list[DroppedPOI] = []
    total_travel_minutes: int = 0
