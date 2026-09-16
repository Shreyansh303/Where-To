"""Google Places API (New) client — the grounded source for attractions and
restaurants. Uses `places:searchText` with a strict field mask so one call
returns everything the solver needs (location, rating, price level, opening
hours) with no follow-up detail calls."""

from typing import Any

from ..models import POI, LatLng, OpeningHours
from .base import BaseClient

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"

_FIELD_MASK = ",".join(
    f"places.{f}"
    for f in [
        "id",
        "displayName",
        "location",
        "rating",
        "userRatingCount",
        "types",
        "priceLevel",
        "formattedAddress",
        "regularOpeningHours",
    ]
)

_PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

# Rough visit durations by place type; the solver treats these as estimates.
# Tuned toward brisk sightseeing so days hold ~5 stops plus meals. Web-grounded
# durations from the city brief (Phase 2) override these when available.
_VISIT_MINUTES = {
    "museum": 120,
    "art_gallery": 90,
    "amusement_park": 480,  # theme parks realistically eat a whole day
    "theme_park": 480,
    "water_park": 420,
    "zoo": 150,
    "aquarium": 100,
    "park": 60,
    "church": 45,
    "hindu_temple": 45,
    "mosque": 45,
    "synagogue": 45,
    "tourist_attraction": 75,
    "shopping_mall": 90,
    "market": 60,
}

# Place types that *can* be whole-day outings — but only when their own hours
# corroborate it (see `_derive_full_day`); the type alone isn't enough.
_FULL_DAY_TYPES = {"amusement_park", "theme_park", "water_park"}

# A park-typed place whose hours don't span the day (an evening show mis-tagged
# `amusement_park`, or unknown hours) gets this bounded visit, not a whole day.
_BOUNDED_PARK_MINUTES = 180
# A genuine all-day park opens by late morning and stays open a wide span.
_FULL_DAY_OPENS_BY = 11 * 60
_FULL_DAY_WINDOW = 6 * 60


def _parse_opening_hours(raw: dict[str, Any] | None) -> OpeningHours | None:
    if not raw or "periods" not in raw:
        return None
    windows: dict[int, list[tuple[int, int]]] = {}
    for period in raw["periods"]:
        open_part = period.get("open")
        if not open_part:
            continue
        close_part = period.get("close")
        # Google: day 0=Sunday…6=Saturday → ours: 0=Monday…6=Sunday
        weekday = (open_part.get("day", 0) - 1) % 7
        open_min = open_part.get("hour", 0) * 60 + open_part.get("minute", 0)
        if close_part is None:
            close_min = 24 * 60  # open-ended (24h places)
        else:
            close_min = close_part.get("hour", 0) * 60 + close_part.get("minute", 0)
            if close_min <= open_min:
                close_min = 24 * 60  # closes past midnight; clamp to day end
        windows.setdefault(weekday, []).append((open_min, close_min))
    return OpeningHours(windows=windows) if windows else None


def _estimate_visit_minutes(types: list[str], kind: str) -> int:
    if kind == "restaurant":
        return 75
    for t in types:
        if t in _VISIT_MINUTES:
            return _VISIT_MINUTES[t]
    return 75


def _has_wide_daytime_window(hours: OpeningHours) -> bool:
    """True if some weekday opens by late morning and runs a wide span — the
    signature of an all-day park rather than an evening event."""
    return any(
        open_min <= _FULL_DAY_OPENS_BY and close_min - open_min >= _FULL_DAY_WINDOW
        for windows in hours.windows.values()
        for open_min, close_min in windows
    )


def _derive_full_day(types: list[str], hours: OpeningHours | None, minutes: int) -> tuple[bool, int]:
    """Corroborate a full-day place *type* against its real opening hours.
    Google tags ~3h evening shows (e.g. Siam Niramit) as `amusement_park`; only
    treat a park as a whole-day outing when its own hours span the day. Evening-
    only, short, or unknown hours → a bounded multi-hour visit, not a whole day."""
    if not (_FULL_DAY_TYPES & set(types)):
        return False, minutes
    if hours is not None and _has_wide_daytime_window(hours):
        return True, minutes
    return False, min(minutes, _BOUNDED_PARK_MINUTES)


def _parse_place(raw: dict[str, Any], kind: str) -> POI | None:
    loc = raw.get("location")
    if not loc or "latitude" not in loc or "longitude" not in loc:
        return None
    types = raw.get("types", [])
    hours = _parse_opening_hours(raw.get("regularOpeningHours"))
    minutes = _estimate_visit_minutes(types, kind)
    is_full_day = False
    if kind == "attraction":
        is_full_day, minutes = _derive_full_day(types, hours, minutes)
    return POI(
        id="",  # assigned by the grounding store
        place_id=raw.get("id", ""),
        name=(raw.get("displayName") or {}).get("text", ""),
        kind=kind,
        location=LatLng(lat=loc["latitude"], lng=loc["longitude"]),
        rating=raw.get("rating"),
        review_count=raw.get("userRatingCount"),
        types=types,
        price_level=_PRICE_LEVELS.get(raw.get("priceLevel", "")),
        address=raw.get("formattedAddress"),
        opening_hours=hours,
        est_visit_minutes=minutes,
        is_full_day=is_full_day,
    )


class PlacesClient(BaseClient):
    service = "places"

    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def search(
        self,
        query: str,
        kind: str = "attraction",
        max_results: int = 20,
        no_cache: bool = False,
    ) -> list[POI]:
        cache_params = {"textQuery": query, "maxResultCount": max_results}

        def fetch() -> Any:
            return self._request_json(
                "POST",
                SEARCH_TEXT_URL,
                json_body={"textQuery": query, "maxResultCount": max_results},
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": _FIELD_MASK,
                    "Content-Type": "application/json",
                },
            )

        raw = self._cached_json(cache_params, fetch, no_cache=no_cache)
        parsed = [_parse_place(p, kind) for p in raw.get("places", [])]
        return [p for p in parsed if p is not None and p.name]

    def search_attractions(self, city: str, query: str) -> list[POI]:
        """`query` is a full attraction-category phrase (e.g. "top tourist
        attractions") that gets scoped to the city."""
        return self.search(f"{query} in {city}", kind="attraction")

    def search_restaurants(self, city: str, area_hint: str | None = None) -> list[POI]:
        where = f"{area_hint}, {city}" if area_hint else city
        found = self.search(f"best restaurants in {where}", kind="restaurant")
        # Text search can surface non-food landmarks; keep the meal pool honest.
        food_types = {"restaurant", "food", "cafe", "bakery", "bar", "meal_takeaway"}
        return [p for p in found if food_types & set(p.types)]
