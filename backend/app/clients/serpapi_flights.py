"""SerpApi Google Flights client.

Round trips are a two-call flow:
1. `search_outbound` returns outbound itineraries; each carries a
   `departure_token`.
2. `search_return` replays the same search with that token and returns the
   matching return itineraries.

SerpApi caches results server-side for ~1h; our cache TTL mirrors that, and
`no_cache=True` is passed through for forced-fresh searches.
"""

from typing import Any

from ..models import FlightOption, FlightSegment
from .base import BaseClient

SERPAPI_URL = "https://serpapi.com/search.json"


def _parse_option(raw: dict[str, Any], direction: str, currency: str) -> FlightOption | None:
    price = raw.get("price")
    if price is None:
        # No price means nothing to ground a recommendation on — skip it.
        return None
    segments = [
        FlightSegment(
            departure_airport=f.get("departure_airport", {}).get("id", ""),
            departure_airport_name=f.get("departure_airport", {}).get("name", ""),
            departure_time=f.get("departure_airport", {}).get("time", ""),
            arrival_airport=f.get("arrival_airport", {}).get("id", ""),
            arrival_airport_name=f.get("arrival_airport", {}).get("name", ""),
            arrival_time=f.get("arrival_airport", {}).get("time", ""),
            airline=f.get("airline", ""),
            flight_number=f.get("flight_number", ""),
            duration_minutes=f.get("duration", 0),
            travel_class=f.get("travel_class"),
        )
        for f in raw.get("flights", [])
    ]
    if not segments:
        return None
    return FlightOption(
        id="",  # assigned by the grounding store on registration
        direction=direction,
        segments=segments,
        total_duration_minutes=raw.get("total_duration", sum(s.duration_minutes for s in segments)),
        layover_airports=[l.get("id", "") for l in raw.get("layovers", [])],
        price=float(price),
        currency=currency,
        airline_logo=raw.get("airline_logo"),
        carbon_grams=(raw.get("carbon_emissions") or {}).get("this_flight"),
        departure_token=raw.get("departure_token"),
    )


class FlightsClient(BaseClient):
    service = "flights"

    def __init__(self, api_key: str, currency: str = "INR", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.currency = currency

    def _base_params(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str,
        adults: int,
        max_price: int | None,
        deep_search: bool,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": departure_date,
            "return_date": return_date,
            "type": 1,  # round trip
            "adults": adults,
            "currency": self.currency,
            "hl": "en",
        }
        if max_price is not None:
            params["max_price"] = max_price
        if deep_search:
            params["deep_search"] = "true"
        return params

    def _search(self, cache_params: dict[str, Any], no_cache: bool) -> dict[str, Any]:
        def fetch() -> Any:
            request_params = dict(cache_params)
            request_params["api_key"] = self.api_key
            if no_cache:
                request_params["no_cache"] = "true"
            return self._request_json("GET", SERPAPI_URL, params=request_params)

        return self._cached_json(cache_params, fetch, no_cache=no_cache)

    def search_outbound(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str,
        adults: int = 1,
        max_price: int | None = None,
        deep_search: bool = False,
        no_cache: bool = False,
    ) -> list[FlightOption]:
        params = self._base_params(origin, destination, departure_date, return_date, adults, max_price, deep_search)
        raw = self._search(params, no_cache)
        options = raw.get("best_flights", []) + raw.get("other_flights", [])
        parsed = [_parse_option(o, "outbound", self.currency) for o in options]
        return [p for p in parsed if p is not None]

    def search_return(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str,
        departure_token: str,
        adults: int = 1,
        max_price: int | None = None,
        deep_search: bool = False,
        no_cache: bool = False,
    ) -> list[FlightOption]:
        """Second leg of the round-trip flow: same search + the chosen
        outbound's departure_token."""
        params = self._base_params(origin, destination, departure_date, return_date, adults, max_price, deep_search)
        params["departure_token"] = departure_token
        raw = self._search(params, no_cache)
        options = raw.get("best_flights", []) + raw.get("other_flights", [])
        parsed = [_parse_option(o, "return", self.currency) for o in options]
        return [p for p in parsed if p is not None]
