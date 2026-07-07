"""One live end-to-end run against real APIs (keys from .env), then a second
run to prove the cache eliminates repeat API calls.

Usage:  python scripts/live_smoke.py [output_json_path]
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.cache import Cache
from app.clients import FlightsClient, HotelsClient, PlacesClient, RoutesClient
from app.config import Settings
from app.models import TripRequest
from app.orchestrator.llm import GroqLLM
from app.orchestrator.pipeline import run_pipeline

REQUEST = TripRequest(
    origin="DEL",
    destination="HKG",
    destination_city="Hong Kong",
    departure_date=date(2026, 8, 10),
    return_date=date(2026, 8, 16),  # 6 nights → 5 sightseeing days
    budget=350000,
    travelers=1,
)


def build(settings: Settings):
    cache = Cache(
        settings.cache_path,
        ttls={
            "flights": settings.cache_ttl_flights,
            "hotels": settings.cache_ttl_hotels,
            "places": settings.cache_ttl_places,
            "routes": settings.cache_ttl_routes,
        },
    )
    clients = (
        FlightsClient(settings.serpapi_api_key, currency=settings.currency, cache=cache),
        HotelsClient(settings.serpapi_api_key, currency=settings.currency, cache=cache),
        PlacesClient(settings.google_maps_api_key, cache=cache),
        RoutesClient(settings.google_maps_api_key, cache=cache),
    )
    return cache, clients


def one_run(label: str, settings: Settings):
    cache, clients = build(settings)
    llm = GroqLLM(settings.groq_api_key, settings.groq_model)
    plan = run_pipeline(REQUEST, settings, emit=lambda s, m: print(f"  [{s}] {m}"), clients=clients, llm=llm)
    names = ["flights", "hotels", "places", "routes"]
    calls = {n: c.calls_made for n, c in zip(names, clients)}
    print(f"\n{label}: real HTTP calls = {calls} (total {sum(calls.values())}), cache hits = {cache.hits}")
    print(f"{label}: Groq tokens used = {llm.total_tokens}")
    return plan


def summarize(plan):
    print("\n================ PLAN SUMMARY ================")
    ob, rt = plan.outbound_flight, plan.return_flight
    print(f"Outbound: {ob.segments[0].airline} {ob.segments[0].flight_number} "
          f"{ob.segments[0].departure_time} -> {ob.segments[-1].arrival_time} | stops={len(ob.layover_airports)}")
    print(f"Return:   {rt.segments[0].airline} {rt.segments[0].flight_number} "
          f"{rt.segments[0].departure_time} -> {rt.segments[-1].arrival_time} | round-trip {rt.price:,.0f} {rt.currency}")
    if plan.hotel:
        print(f"Hotel:    {plan.hotel.name} | rating {plan.hotel.rating} | total {plan.hotel.total_rate:,.0f} {plan.hotel.currency}")
    b = plan.budget
    print(f"Budget:   total {b.total:,.0f} | flights {b.flights_total:,.0f} | hotel {b.hotel_total or 0:,.0f} | left {b.remaining_for_activities:,.0f}")
    if b.est_meal_cost:
        print(f"Meal:     ~{b.est_meal_cost} per adult (researched estimate)")
    for day in plan.days:
        print(f"\n  {day.date} ({day.weekday_name})")
        for s in day.stops:
            tag = f" [{s.meal}]" if s.meal else ""
            full = " [FULL DAY]" if s.is_full_day else ""
            cost = f" — {s.est_entry_cost}" if s.est_entry_cost else ""
            src = f" (src: {s.est_entry_cost_source})" if s.est_entry_cost_source else ""
            est = "~" if s.travel_is_estimate else ""
            print(f"    {s.arrive}-{s.depart}{tag}{full} {s.poi.name}{cost}{src} "
                  f"(travel {est}{s.travel_from_prev_minutes}m)"
                  + (f"  // {s.note}" if s.note else ""))
    print(f"\nGetting around: {plan.getting_around}")
    print(f"Commentary: {plan.commentary}")
    if plan.dropped_pois:
        print(f"Dropped: {plan.dropped_pois}")
    print("Data quality:")
    for n in plan.data_quality:
        print(f"  - [{n.source}/{n.level}] {n.message}")


if __name__ == "__main__":
    settings = Settings()
    assert settings.serpapi_api_key and settings.groq_api_key, "keys missing from .env"
    print("=== RUN 1 (cold cache) ===")
    plan = one_run("RUN 1", settings)
    summarize(plan)

    print("\n=== RUN 2 (warm cache — expect zero flight/hotel/places/routes calls) ===")
    one_run("RUN 2", settings)

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("last_live_plan.json")
    out.write_text(json.dumps(plan.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull plan JSON written to {out}")
