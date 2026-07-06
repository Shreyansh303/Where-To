"""SerpApi Google Hotels client. One search returns a `properties` array;
we filter to entries with a usable price so every recommendation stays
grounded in a real rate."""

from typing import Any

from ..models import HotelOption, LatLng
from .base import BaseClient
from .serpapi_flights import SERPAPI_URL


def _parse_property(raw: dict[str, Any], currency: str) -> HotelOption | None:
    rate = (raw.get("rate_per_night") or {}).get("extracted_lowest")
    total = (raw.get("total_rate") or {}).get("extracted_lowest")
    if rate is None and total is None:
        return None
    gps = raw.get("gps_coordinates") or {}
    location = None
    if "latitude" in gps and "longitude" in gps:
        location = LatLng(lat=gps["latitude"], lng=gps["longitude"])
    return HotelOption(
        id="",  # assigned by the grounding store
        name=raw.get("name", ""),
        description=raw.get("description"),
        rate_per_night=rate,
        total_rate=total,
        currency=currency,
        hotel_class=raw.get("extracted_hotel_class"),
        rating=raw.get("overall_rating"),
        review_count=raw.get("reviews"),
        location=location,
        amenities=raw.get("amenities", [])[:12],
        check_in_time=raw.get("check_in_time"),
        check_out_time=raw.get("check_out_time"),
        link=raw.get("link"),
        thumbnail=(raw.get("images") or [{}])[0].get("thumbnail"),
    )


class HotelsClient(BaseClient):
    service = "hotels"

    def __init__(self, api_key: str, currency: str = "INR", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.currency = currency

    def search(
        self,
        city: str,
        check_in_date: str,
        check_out_date: str,
        adults: int = 1,
        max_price: int | None = None,
        no_cache: bool = False,
    ) -> list[HotelOption]:
        cache_params: dict[str, Any] = {
            "engine": "google_hotels",
            "q": f"{city} hotels",
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": adults,
            "currency": self.currency,
            "hl": "en",
        }
        if max_price is not None:
            cache_params["max_price"] = max_price

        def fetch() -> Any:
            request_params = dict(cache_params)
            request_params["api_key"] = self.api_key
            if no_cache:
                request_params["no_cache"] = "true"
            return self._request_json("GET", SERPAPI_URL, params=request_params)

        raw = self._cached_json(cache_params, fetch, no_cache=no_cache)
        parsed = [_parse_property(p, self.currency) for p in raw.get("properties", [])]
        hotels = [h for h in parsed if h is not None]
        if max_price is not None:
            # Belt-and-braces: SerpApi's max_price is advisory, enforce locally.
            hotels = [h for h in hotels if (h.total_rate or h.rate_per_night or 0) <= max_price]
        return hotels
