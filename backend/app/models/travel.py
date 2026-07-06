from typing import Literal

from pydantic import BaseModel

from .core import LatLng


class FlightSegment(BaseModel):
    departure_airport: str
    departure_airport_name: str = ""
    departure_time: str  # "2026-08-10 06:15" as returned by SerpApi
    arrival_airport: str
    arrival_airport_name: str = ""
    arrival_time: str
    airline: str
    flight_number: str
    duration_minutes: int
    travel_class: str | None = None


class FlightOption(BaseModel):
    id: str  # grounding id, e.g. "flight_out_2"
    direction: Literal["outbound", "return"]
    segments: list[FlightSegment]
    total_duration_minutes: int
    layover_airports: list[str] = []
    price: float
    currency: str
    airline_logo: str | None = None
    carbon_grams: int | None = None
    # SerpApi token used to fetch matching return flights. Server-side only;
    # never included in LLM-facing summaries or API responses.
    departure_token: str | None = None


class HotelOption(BaseModel):
    id: str  # grounding id, e.g. "hotel_4"
    name: str
    description: str | None = None
    rate_per_night: float | None = None
    total_rate: float | None = None
    currency: str
    hotel_class: int | None = None
    rating: float | None = None
    review_count: int | None = None
    location: LatLng | None = None
    amenities: list[str] = []
    check_in_time: str | None = None
    check_out_time: str | None = None
    link: str | None = None
    thumbnail: str | None = None
