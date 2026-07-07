"""Orchestrator tests: the full agent loop + pipeline over fixture-backed
clients and the scripted FakeLLM — no keys, no network, fully deterministic."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.grounding import GroundingStore
from app.models import TripRequest
from app.orchestrator import run_pipeline
from app.orchestrator import pipeline as pipeline_module
from app.orchestrator.fakes import _handler as fixture_handler
from app.orchestrator.fakes import build_fake_clients
from app.orchestrator.llm import FakeLLM
from app.orchestrator.pipeline import _agent_loop
from app.orchestrator.tools import Toolbox

FIXTURES = Path(__file__).parent / "fixtures"


def make_request(**overrides) -> TripRequest:
    defaults = dict(
        origin="DEL",
        destination="CDG",
        destination_city="Paris",
        departure_date=date(2026, 8, 10),
        return_date=date(2026, 8, 15),
        budget=400000,
        travelers=2,
    )
    defaults.update(overrides)
    return TripRequest(**defaults)


def make_settings(tmp_path) -> Settings:
    return Settings(fake_apis=True, cache_path=str(tmp_path / "cache.sqlite3"))


def test_fake_pipeline_end_to_end(tmp_path):
    events: list[tuple[str, str]] = []
    plan = run_pipeline(make_request(), make_settings(tmp_path), emit=lambda s, m: events.append((s, m)))

    assert plan.outbound_flight is not None and plan.return_flight is not None
    assert plan.hotel is not None
    assert plan.days, "itinerary days must exist"
    assert any(s.meal for d in plan.days for s in d.stops), "meals should be scheduled"
    assert plan.commentary
    # budget math is derived from stored API objects only
    assert plan.budget.flights_total == plan.return_flight.price
    assert plan.budget.remaining_for_activities == pytest.approx(
        plan.budget.total - plan.budget.flights_total - plan.budget.hotel_total
    )
    stages = [s for s, _ in events]
    assert stages[-1] == "done"
    assert {"flights", "hotels", "attractions", "solving"} <= set(stages)


def test_every_fact_traces_to_fixture_data(tmp_path):
    """Grounding audit: all prices/names in the plan exist in the recorded
    API responses, byte-for-byte."""
    plan = run_pipeline(make_request(), make_settings(tmp_path))

    outbound_fixture = json.loads((FIXTURES / "serpapi_flights_outbound.json").read_text(encoding="utf-8"))
    return_fixture = json.loads((FIXTURES / "serpapi_flights_return.json").read_text(encoding="utf-8"))
    hotels_fixture = json.loads((FIXTURES / "serpapi_hotels.json").read_text(encoding="utf-8"))
    places_fixture = json.loads((FIXTURES / "places_searchtext.json").read_text(encoding="utf-8"))

    outbound_prices = {
        o["price"]
        for o in outbound_fixture["best_flights"] + outbound_fixture["other_flights"]
        if "price" in o
    }
    return_prices = {
        o["price"] for o in return_fixture["best_flights"] + return_fixture["other_flights"] if "price" in o
    }
    hotel_names = {p["name"] for p in hotels_fixture["properties"]}
    place_names = {p["displayName"]["text"] for p in places_fixture["places"]}

    assert plan.outbound_flight.price in outbound_prices
    assert plan.return_flight.price in return_prices
    assert plan.hotel.name in hotel_names
    for day in plan.days:
        for stop in day.stops:
            assert stop.poi.name in place_names


def test_invalid_selection_is_retried_and_recovers(tmp_path):
    settings = make_settings(tmp_path)
    flights, hotels, places, _ = build_fake_clients(None, settings.currency)
    toolbox = Toolbox(
        request=make_request(),
        store=GroundingStore(),
        flights=flights,
        hotels=hotels,
        places=places,
        emit=lambda s, m: None,
    )
    _agent_loop(FakeLLM(invalid_first=True), toolbox, make_request(), settings.currency)
    assert toolbox.selections is not None
    assert toolbox.selections.outbound_flight_id.startswith("flight_out_")


def test_budget_rejection_forces_note_when_unfixable(tmp_path):
    # Budget far below any flight+hotel combo: FakeLLM re-submits the same
    # picks, so after MAX_BUDGET_REJECTIONS the plan is accepted with a
    # degraded-quality note instead of failing.
    plan = run_pipeline(make_request(budget=50000), make_settings(tmp_path))
    assert plan.budget.remaining_for_activities < 0
    assert any(n.source == "llm" and "budget" in n.message for n in plan.data_quality)


def test_hotels_failure_degrades_not_crashes(tmp_path, monkeypatch):
    def failing_hotels_builder(cache, currency):
        flights, hotels, places, routes = build_fake_clients(cache, currency)

        def handler(request: httpx.Request) -> httpx.Response:
            if "google_hotels" in str(request.url):
                return httpx.Response(503)
            return fixture_handler(request)

        for client in (hotels,):
            client._http = httpx.Client(transport=httpx.MockTransport(handler))
            client.max_retries = 1
            client.backoff_base = 0.0
        return flights, hotels, places, routes

    monkeypatch.setattr(pipeline_module, "build_fake_clients", failing_hotels_builder)
    plan = run_pipeline(make_request(), make_settings(tmp_path))

    assert plan.hotel is None
    assert any(n.source == "hotels" and n.level == "failed" for n in plan.data_quality)
    # the rest of the plan is intact
    assert plan.outbound_flight is not None
    assert plan.days and any(s for d in plan.days for s in d.stops)


def test_routes_degradation_is_flagged(tmp_path):
    # The fixture matrix only covers 3x3, but hotel+POIs need more — the
    # missing elements must be flagged as estimates in data_quality.
    plan = run_pipeline(make_request(), make_settings(tmp_path))
    assert any(n.source == "routes" and n.level == "degraded" for n in plan.data_quality)


def _poi(name: str, reviews: int, rating: float = 4.5, full_day: bool = False):
    from app.models import LatLng, POI

    return POI(
        id="",
        place_id=f"g_{name}",
        name=name,
        kind="attraction",
        location=LatLng(lat=22.3, lng=114.1),
        rating=rating,
        review_count=reviews,
        is_full_day=full_day,
    )


def test_select_attractions_forces_in_all_must_sees():
    # Iconic must-sees have modest review counts; museums are hugely popular.
    # A single-day trip has only ~5 ordinary slots, yet every must-see must
    # still be a candidate — never crowded out by the popular museums.
    from app.models import CityBrief

    store = GroundingStore()
    icons = store.add_all("poi", [_poi(f"Icon {i}", reviews=200) for i in range(8)])
    museums = store.add_all("poi", [_poi(f"Museum {i}", reviews=90000) for i in range(3)])
    brief = CityBrief(city="Hong Kong", must_see=[p.name for p in icons])

    ids = pipeline_module._select_attractions(store, full_days=1, brief=brief)

    assert all(p.id in ids for p in icons), "every must-see must be selected"
    assert not any(m.id in ids for m in museums), "popular non-must-see museums don't crowd them out"


def test_select_attractions_falls_back_to_popularity_without_brief():
    # No brief (research failed): the most-reviewed sights win, not obscure ones.
    store = GroundingStore()
    famous = store.add_all("poi", [_poi("Big Buddha", reviews=80000)])[0]
    obscure = store.add_all("poi", [_poi(f"Tiny Spot {i}", reviews=30) for i in range(10)])

    ids = pipeline_module._select_attractions(store, full_days=1, brief=None)

    assert famous.id in ids
    assert sum(1 for o in obscure if o.id in ids) < len(obscure)


def test_city_brief_overrides_duration_and_price(tmp_path, monkeypatch):
    # A researched brief marks the Louvre a whole-day outing with a sourced
    # price; the plan must reflect the override — Louvre alone on its day,
    # carrying the researched cost + source link.
    from app.models import AttractionFacts, CityBrief

    brief = CityBrief(
        city="Paris",
        must_see=["Louvre Museum"],
        attractions={
            "Louvre Museum": AttractionFacts(
                duration_minutes=480,
                is_full_day=True,
                ticket_price="INR 2,000",
                source_url="https://example.com/louvre",
            )
        },
        meal_cost="INR 1,500",
    )
    monkeypatch.setattr(pipeline_module, "_build_city_brief", lambda *a, **k: brief)

    plan = run_pipeline(make_request(), make_settings(tmp_path))

    louvre_stops = [
        (d, s) for d in plan.days for s in d.stops if s.poi.name == "Louvre Museum"
    ]
    assert louvre_stops, "Louvre should be scheduled"
    day, stop = louvre_stops[0]
    assert stop.is_full_day is True
    assert stop.est_entry_cost == "INR 2,000"
    assert stop.est_entry_cost_source == "https://example.com/louvre"
    # A whole-day outing owns its day: no other attractions share it.
    others = [s for s in day.stops if s.meal is None and s.poi.name != "Louvre Museum"]
    assert others == []
    assert plan.budget.est_meal_cost == "INR 1,500"
