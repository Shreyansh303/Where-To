"""The toolbox the LLM drives.

Each tool calls the corresponding API client (cache-first), registers every
returned entity in the grounding store, and hands the LLM a *compact summary
containing grounding ids* — never raw blobs, never anything unregistered.
Client failures become data-quality notes plus an "error" payload the model
can react to; they never crash the loop.

`finalize_plan` is the gate: selections are validated against the store and
the trip budget, and validation failures are returned as tool errors so the
model can retry with everything fixed.
"""

import json
from dataclasses import dataclass, field
from typing import Callable

from ..clients import ApiError, FlightsClient, HotelsClient, PlacesClient
from ..grounding import GroundingError, GroundingStore, SelectionError, TripSelections, validate_selections
from ..models import DataQualityNote, FlightOption, HotelOption, POI, TripRequest

# Token economy: every tool result is re-sent to the LLM on each subsequent
# turn, so summaries and schema descriptions are kept aggressively terse.
# Groq free tier is ~12K tokens/minute — the whole loop must fit well under.
MAX_OPTIONS_SHOWN = 6
MAX_BUDGET_REJECTIONS = 2

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Round-trip flight options (outbound leg), with ids and round-trip prices.",
            "parameters": {
                "type": "object",
                "properties": {"max_price": {"type": "integer"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_return_flights",
            "description": "Return legs matching a chosen outbound id. Prices are FINAL round-trip totals.",
            "parameters": {
                "type": "object",
                "properties": {"outbound_flight_id": {"type": "string"}},
                "required": ["outbound_flight_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Hotels for the whole stay, with ids and total stay prices.",
            "parameters": {
                "type": "object",
                "properties": {"max_price": {"type": "integer"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_attractions",
            "description": "Attractions matching the traveler's interests, with ids and ratings.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_plan",
            "description": "Submit final selections by id. Validated against real data; on error fix everything and retry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "outbound_flight_id": {"type": "string"},
                    "return_flight_id": {"type": "string"},
                    "hotel_id": {"type": ["string", "null"]},
                    "poi_ids": {"type": "array", "items": {"type": "string"}},
                    "commentary": {"type": "string"},
                },
                "required": ["outbound_flight_id", "return_flight_id", "poi_ids"],
            },
        },
    },
]


def _flight_summary(f: FlightOption) -> dict:
    return {
        "id": f.id,
        "price": f.price,
        "hrs": round(f.total_duration_minutes / 60, 1),
        "stops": len(f.layover_airports),
        "via": ",".join(f.layover_airports) or None,
        "air": "/".join(sorted({s.airline for s in f.segments})),
        "dep": f.segments[0].departure_time,
        "arr": f.segments[-1].arrival_time,
    }


def _hotel_summary(h: HotelOption) -> dict:
    return {
        "id": h.id,
        "name": h.name,
        "price": h.total_rate or h.rate_per_night,
        "rating": h.rating,
        "stars": h.hotel_class,
    }


def _poi_summary(p: POI) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "rating": p.rating,
        "tags": "|".join(p.interest_tags) or None,
        "mins": p.est_visit_minutes,
    }


@dataclass
class Toolbox:
    request: TripRequest
    store: GroundingStore
    flights: FlightsClient
    hotels: HotelsClient
    places: PlacesClient
    emit: Callable[[str, str], None]
    data_quality: list[DataQualityNote] = field(default_factory=list)

    selections: TripSelections | None = None
    _budget_rejections: int = 0
    _outbound_searched: bool = False
    _returns_searched: bool = False
    _hotels_failed: bool = False
    _places_failed: bool = False

    def execute(self, name: str, args: dict) -> str:
        handler = {
            "search_flights": self._search_flights,
            "get_return_flights": self._get_return_flights,
            "search_hotels": self._search_hotels,
            "search_attractions": self._search_attractions,
            "finalize_plan": self._finalize_plan,
        }.get(name)
        if handler is None:
            return json.dumps({"error": f"unknown tool '{name}'"})
        try:
            return json.dumps(handler(args), separators=(",", ":"))
        except ApiError as exc:
            self._note(exc.source, "failed", str(exc))
            return json.dumps(
                {"error": str(exc), "advice": "source unavailable; continue without it"},
                separators=(",", ":"),
            )

    def _note(self, source: str, level: str, message: str) -> None:
        self.data_quality.append(DataQualityNote(source=source, level=level, message=message))

    # ------------------------------------------------------------- tools
    def _search_flights(self, args: dict) -> dict:
        self.emit("flights", "Scanning live flight prices…")
        r = self.request
        options = self.flights.search_outbound(
            r.origin,
            r.destination,
            str(r.departure_date),
            str(r.return_date),
            adults=r.travelers,
            max_price=args.get("max_price"),
        )
        self.store.add_all("flight_out", options)
        self._outbound_searched = True
        shown = sorted(options, key=lambda f: f.price)[:MAX_OPTIONS_SHOWN]
        return {"options": [_flight_summary(f) for f in shown], "note": "round-trip totals, all travelers"}

    def _get_return_flights(self, args: dict) -> dict:
        self.emit("flights_return", "Matching return flights…")
        try:
            outbound = self.store.get_flight(str(args.get("outbound_flight_id", "")), "outbound")
        except GroundingError as exc:
            return {"error": str(exc)}
        if not outbound.departure_token:
            return {"error": f"'{outbound.id}' has no return-leg token; pick a different outbound"}
        r = self.request
        options = self.flights.search_return(
            r.origin,
            r.destination,
            str(r.departure_date),
            str(r.return_date),
            departure_token=outbound.departure_token,
            adults=r.travelers,
        )
        self.store.add_all("flight_ret", options)
        self._returns_searched = True
        shown = sorted(options, key=lambda f: f.price)[:MAX_OPTIONS_SHOWN]
        return {"options": [_flight_summary(f) for f in shown], "note": "FINAL round-trip totals"}

    def _search_hotels(self, args: dict) -> dict:
        self.emit("hotels", "Haggling with hotels…")
        r = self.request
        try:
            options = self.hotels.search(
                r.destination_city,
                str(r.departure_date),
                str(r.return_date),
                adults=r.travelers,
                max_price=args.get("max_price"),
            )
        except ApiError as exc:
            self._hotels_failed = True
            self._note("hotels", "failed", f"hotel search failed: {exc}")
            return {"error": str(exc), "advice": "set hotel_id to null in finalize_plan and continue"}
        self.store.add_all("hotel", options)
        ranked = sorted(options, key=lambda h: (-(h.rating or 0), h.total_rate or h.rate_per_night or 0))
        return {"options": [_hotel_summary(h) for h in ranked[:MAX_OPTIONS_SHOWN]]}

    def _search_attractions(self, args: dict) -> dict:
        self.emit("attractions", "Hunting down the good stuff…")
        r = self.request
        interests = r.interests or ["sightseeing"]
        seen_place_ids: set[str] = set()
        pois: list[POI] = []
        failures = 0
        for interest in interests[:5]:
            try:
                found = self.places.search_attractions(r.destination_city, interest)
            except ApiError as exc:
                failures += 1
                self._note("places", "degraded", f"attraction search '{interest}' failed: {exc}")
                continue
            for p in found:
                if p.place_id in seen_place_ids:
                    # merge the extra interest tag onto the already-known POI
                    known = next((k for k in pois if k.place_id == p.place_id), None)
                    if known is not None:
                        known.interest_tags = sorted(set(known.interest_tags) | set(p.interest_tags))
                    continue
                seen_place_ids.add(p.place_id)
                pois.append(p)
        if failures == len(interests[:5]):
            self._places_failed = True
            raise ApiError("places", "all attraction searches failed")
        self.store.add_all("poi", pois)
        per_day = 5
        cap = min(len(pois), min(per_day * self.request.full_days + 5, 24))
        shown = sorted(pois, key=lambda p: -p.value_score)[:cap]
        return {
            "options": [_poi_summary(p) for p in shown],
            "note": f"pick ~{per_day}/day for {self.request.full_days} day(s), ranked",
        }

    def _finalize_plan(self, args: dict) -> dict:
        self.emit("finalize", "Checking every fact against real data…")
        if not (self._outbound_searched and self._returns_searched):
            return {"error": "you must call search_flights and get_return_flights before finalizing"}
        try:
            selections = validate_selections(self.store, args)
        except SelectionError as exc:
            return {"error": str(exc)}
        if not selections.poi_ids and not self._places_failed:
            return {"error": "select at least one attraction id from search_attractions"}

        over = self._budget_overrun(selections)
        if over > 0 and self._budget_rejections < MAX_BUDGET_REJECTIONS:
            self._budget_rejections += 1
            return {
                "error": (
                    f"selection exceeds the {self.request.budget:.0f} {self._currency()} budget by {over:.0f}."
                    " Pick a cheaper flight and/or hotel and finalize again."
                )
            }
        if over > 0:
            self._note("llm", "degraded", f"plan exceeds budget by {over:.0f} {self._currency()} — best available option kept")
        self.selections = selections
        return {"status": "accepted", "message": "plan grounded and accepted"}

    def _budget_overrun(self, selections: TripSelections) -> float:
        flights_total = self.store.get_flight(selections.return_flight_id, "return").price
        hotel_total = 0.0
        if selections.hotel_id is not None:
            hotel = self.store.get_hotel(selections.hotel_id)
            hotel_total = hotel.total_rate or (hotel.rate_per_night or 0) * self.request.nights
        return flights_total + hotel_total - self.request.budget

    def _currency(self) -> str:
        return self.flights.currency
