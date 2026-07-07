"""FAKE_APIS mode: clients wired to an httpx.MockTransport that serves the
recorded fixture responses. The entire pipeline — agent loop, grounding,
solver, assembly — runs unmodified with zero API spend. Used for demos,
CI, and local development without keys."""

import json
from pathlib import Path

import httpx

from ..cache import Cache
from ..clients import FlightsClient, HotelsClient, PlacesClient, RoutesClient

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _fixture(name: str) -> dict | list:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "serpapi.com" in url:
        if "google_hotels" in url:
            return httpx.Response(200, json=_fixture("serpapi_hotels.json"))
        # web search engine (engine=google), distinct from google_flights/hotels
        if "engine=google&" in url or url.endswith("engine=google"):
            return httpx.Response(200, json=_fixture("serpapi_search.json"))
        if "departure_token" in url:
            return httpx.Response(200, json=_fixture("serpapi_flights_return.json"))
        return httpx.Response(200, json=_fixture("serpapi_flights_outbound.json"))
    if "places.googleapis.com" in url:
        return httpx.Response(200, json=_fixture("places_searchtext.json"))
    if "routes.googleapis.com" in url:
        return httpx.Response(200, json=_fixture("routes_matrix.json"))
    return httpx.Response(404, json={"error": f"no fixture for {url}"})


def build_fake_clients(cache: Cache | None, currency: str):
    transport = httpx.MockTransport(_handler)
    kwargs = {"cache": cache, "transport": transport, "backoff_base": 0.0}
    return (
        FlightsClient(api_key="fake", currency=currency, **kwargs),
        HotelsClient(api_key="fake", currency=currency, **kwargs),
        PlacesClient(api_key="fake", **kwargs),
        RoutesClient(api_key="fake", **kwargs),
    )
