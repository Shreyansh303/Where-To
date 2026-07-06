"""API client tests against recorded fixture responses (no live calls)."""

import httpx
import pytest
import respx

from app.cache import Cache
from app.clients import (
    ApiAuthError,
    ApiRateLimitError,
    FlightsClient,
    HotelsClient,
    PlacesClient,
    RoutesClient,
)
from app.clients.google_places import SEARCH_TEXT_URL
from app.clients.google_routes import MATRIX_URL
from app.clients.serpapi_flights import SERPAPI_URL
from app.models import LatLng

NO_BACKOFF = {"backoff_base": 0.0}


# ---------------------------------------------------------------- flights
@respx.mock
def test_flights_outbound_parsing(fixture_json):
    respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_flights_outbound.json"))
    client = FlightsClient(api_key="k", currency="INR", **NO_BACKOFF)
    options = client.search_outbound("DEL", "CDG", "2026-08-10", "2026-08-15", adults=2)

    # 4 raw options, 1 has no price and must be dropped (grounding rule)
    assert len(options) == 3
    direct = options[0]
    assert direct.price == 42350 and direct.currency == "INR"
    assert direct.departure_token == "TOKEN_OUT_AF225"
    assert direct.segments[0].flight_number == "AF 225"
    assert direct.layover_airports == []
    one_stop = options[1]
    assert one_stop.layover_airports == ["DXB"]
    assert len(one_stop.segments) == 2
    assert one_stop.total_duration_minutes == 800


@respx.mock
def test_flights_return_leg_sends_departure_token(fixture_json):
    route = respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_flights_return.json"))
    client = FlightsClient(api_key="k", currency="INR", **NO_BACKOFF)
    options = client.search_return(
        "DEL", "CDG", "2026-08-10", "2026-08-15", departure_token="TOKEN_OUT_AF225"
    )
    sent = route.calls.last.request
    assert "departure_token=TOKEN_OUT_AF225" in str(sent.url)
    assert "api_key=k" in str(sent.url)
    assert len(options) == 2
    assert options[0].direction == "return"
    assert options[0].segments[0].departure_airport == "CDG"


@respx.mock
def test_flights_cache_prevents_second_http_call(tmp_path, fixture_json):
    route = respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_flights_outbound.json"))
    cache = Cache(str(tmp_path / "c.sqlite3"))
    client = FlightsClient(api_key="k", cache=cache, **NO_BACKOFF)

    first = client.search_outbound("DEL", "CDG", "2026-08-10", "2026-08-15")
    second = client.search_outbound("DEL", "CDG", "2026-08-10", "2026-08-15")
    assert route.call_count == 1
    assert client.calls_made == 1
    assert [f.price for f in first] == [f.price for f in second]


# ---------------------------------------------------------------- hotels
@respx.mock
def test_hotels_parsing_drops_priceless(fixture_json):
    respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_hotels.json"))
    client = HotelsClient(api_key="k", currency="INR", **NO_BACKOFF)
    hotels = client.search("Paris", "2026-08-10", "2026-08-15", adults=2)

    names = [h.name for h in hotels]
    assert "Auberge Sans Prix" not in names  # no rate → not groundable
    assert len(hotels) == 3
    louvre = hotels[0]
    assert louvre.total_rate == 92500 and louvre.rate_per_night == 18500
    assert louvre.hotel_class == 5 and louvre.location.lat == pytest.approx(48.8629)


@respx.mock
def test_hotels_max_price_enforced_locally(fixture_json):
    respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_hotels.json"))
    client = HotelsClient(api_key="k", **NO_BACKOFF)
    hotels = client.search("Paris", "2026-08-10", "2026-08-15", max_price=100000)
    assert all((h.total_rate or h.rate_per_night) <= 100000 for h in hotels)
    assert "Palais Royal Grand" not in [h.name for h in hotels]


# ---------------------------------------------------------------- places
@respx.mock
def test_places_parsing_and_hours_mapping(fixture_json):
    respx.post(SEARCH_TEXT_URL).respond(json=fixture_json("places_searchtext.json"))
    client = PlacesClient(api_key="k", **NO_BACKOFF)
    pois = client.search_attractions("Paris", "art")

    louvre = next(p for p in pois if p.name == "Louvre Museum")
    assert louvre.interest_tags == ["art"]
    assert louvre.est_visit_minutes == 120  # museum heuristic
    # Google day 0 = Sunday → our weekday 6; day 1 (Monday) absent → closed
    assert louvre.opening_hours.is_open_during(6, 600, 800)
    assert not louvre.opening_hours.is_open_during(0, 600, 800)
    # Wednesday late opening (google day 3 → our 2) until 21:45
    assert louvre.opening_hours.is_open_during(2, 1200, 1305)

    pere = next(p for p in pois if "Lachaise" in p.name)
    assert pere.opening_hours is None  # unknown hours preserved as unknown

    resto = next(p for p in pois if p.name == "Chez Janou")
    assert resto.price_level == 2


@respx.mock
def test_places_sends_field_mask(fixture_json):
    route = respx.post(SEARCH_TEXT_URL).respond(json=fixture_json("places_searchtext.json"))
    PlacesClient(api_key="k", **NO_BACKOFF).search("q")
    headers = route.calls.last.request.headers
    assert "places.regularOpeningHours" in headers["X-Goog-FieldMask"]
    assert headers["X-Goog-Api-Key"] == "k"


# ---------------------------------------------------------------- routes
POINTS = [
    LatLng(lat=48.8606, lng=2.3376),
    LatLng(lat=48.8584, lng=2.2945),
    LatLng(lat=48.8613, lng=2.3934),
]


@respx.mock
def test_routes_matrix_with_fallback_for_missing_element(fixture_json):
    respx.post(MATRIX_URL).respond(json=fixture_json("routes_matrix.json"))
    client = RoutesClient(api_key="k", **NO_BACKOFF)
    matrix = client.travel_time_matrix(POINTS)

    assert matrix.minutes[0][1] == 22  # 1320s
    assert not matrix.estimated[0][1]
    # element (1,2) had ROUTE_NOT_FOUND → haversine estimate, flagged
    assert matrix.estimated[1][2]
    assert matrix.minutes[1][2] >= 1
    assert matrix.any_estimated


@respx.mock
def test_routes_total_failure_degrades_to_estimates():
    respx.post(MATRIX_URL).respond(status_code=500)
    client = RoutesClient(api_key="k", max_retries=1, **NO_BACKOFF)
    matrix = client.travel_time_matrix(POINTS)
    assert matrix.any_estimated
    assert all(matrix.estimated[i][j] for i in range(3) for j in range(3) if i != j)
    # Louvre → Eiffel is ~3.2 km; estimate should be plausible, not zero
    assert 5 <= matrix.minutes[0][1] <= 60


# ---------------------------------------------------------------- base behavior
@respx.mock
def test_retry_on_429_then_success(fixture_json):
    route = respx.get(SERPAPI_URL)
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json=fixture_json("serpapi_flights_outbound.json")),
    ]
    client = FlightsClient(api_key="k", **NO_BACKOFF)
    options = client.search_outbound("DEL", "CDG", "2026-08-10", "2026-08-15")
    assert len(options) == 3
    assert route.call_count == 2


@respx.mock
def test_rate_limit_error_after_retries_exhausted():
    respx.get(SERPAPI_URL).respond(status_code=429)
    client = FlightsClient(api_key="k", max_retries=2, **NO_BACKOFF)
    with pytest.raises(ApiRateLimitError):
        client.search_outbound("DEL", "CDG", "2026-08-10", "2026-08-15")


@respx.mock
def test_auth_error_not_retried():
    route = respx.get(SERPAPI_URL).respond(status_code=401)
    client = FlightsClient(api_key="bad", **NO_BACKOFF)
    with pytest.raises(ApiAuthError):
        client.search_outbound("DEL", "CDG", "2026-08-10", "2026-08-15")
    assert route.call_count == 1
