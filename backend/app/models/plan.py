"""The final, fully-resolved trip plan returned to the frontend.

Every concrete fact here (prices, names, times, addresses, hours) is copied
by the output assembler from stored API responses — resolved via grounding
ids. LLM-authored text is confined to the explicitly-labelled *commentary*
fields and can never introduce new facts into the structured data.
"""

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel

from .places import POI
from .request import TripRequest
from .travel import FlightOption, HotelOption


class BudgetBreakdown(BaseModel):
    currency: str
    total: float
    flights_total: float | None = None
    hotel_total: float | None = None
    remaining_for_activities: float | None = None
    est_meal_cost: str | None = None


class DataQualityNote(BaseModel):
    source: Literal["flights", "hotels", "places", "routes", "llm"]
    level: Literal["ok", "degraded", "failed"]
    message: str


class ResolvedStop(BaseModel):
    """An itinerary stop with its POI facts inlined for rendering."""

    poi: POI
    arrive: str  # "09:30"
    depart: str
    travel_from_prev_minutes: int = 0
    travel_mode: str = "transit"
    travel_is_estimate: bool = False
    meal: Literal["breakfast", "lunch", "dinner"] | None = None
    note: str | None = None
    est_entry_cost: str | None = None  # AI-estimated, not grounded data


class PlanDay(BaseModel):
    date: Date
    weekday_name: str
    stops: list[ResolvedStop] = []
    # Real, unscheduled POIs near this day's route — "if you have time" ideas.
    extras: list[POI] = []
    commentary: str | None = None  # LLM prose — clearly scoped, no facts


class TripPlan(BaseModel):
    request: TripRequest
    outbound_flight: FlightOption | None = None
    return_flight: FlightOption | None = None
    hotel: HotelOption | None = None
    days: list[PlanDay] = []
    getting_around: str | None = None  # grounded transit summary
    budget: BudgetBreakdown
    data_quality: list[DataQualityNote] = []
    commentary: str | None = None  # LLM trip overview prose
    dropped_pois: list[str] = []  # human-readable reasons
