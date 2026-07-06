"""End-to-end trip-planning pipeline.

Phase 1 — agent loop: the LLM drives the toolbox (flights → returns → hotels
→ attractions → finalize) and its id selections are validated against the
grounding store. If the model errors out or never finalizes, the pipeline
degrades to the deterministic FakeLLM policy over the same tools and records
a data-quality note — a bad LLM day never sinks the trip.

Phase 2 — deterministic: restaurants, the real travel-time matrix, the
constraint solver, and plan assembly. No LLM involvement past this line.
"""

import json
from datetime import timedelta
from typing import Callable

from ..cache import Cache
from ..clients import ApiError, FlightsClient, HotelsClient, PlacesClient, RoutesClient
from ..config import Settings
from ..grounding import GroundingStore
from ..models import POI, DataQualityNote, LatLng, TripPlan, TripRequest
from ..output import assemble_plan
from ..solver import SolverInput, solve
from .fakes import build_fake_clients
from .llm import FakeLLM, GroqLLM
from .tools import TOOL_SCHEMAS, Toolbox

EmitFn = Callable[[str, str], None]

MAX_AGENT_ITERATIONS = 16

SYSTEM_PROMPT = """You are a travel-planning agent. Never invent data — only \
select options returned by tools, by their exact ids. Flow: search_flights -> \
get_return_flights(chosen outbound id) -> search_hotels -> search_attractions \
-> finalize_plan. Return prices are FINAL round-trip totals; flights + hotel \
must fit the budget with room for food. Prefer well-rated options matching \
the traveler's interests; rank poi_ids by priority, ~5 per day. commentary: \
2-3 warm sentences, no prices or times. If a tool errors, follow its advice."""


class OrchestrationError(Exception):
    pass


def _context_message(request: TripRequest, currency: str) -> str:
    interests = ", ".join(request.interests) or "general sightseeing"
    return (
        f"Trip: {request.origin}->{request.destination} ({request.destination_city}), "
        f"{request.departure_date} to {request.return_date}, {request.full_days} sightseeing day(s), "
        f"{request.travelers} traveler(s), budget {request.budget:.0f} {currency} "
        f"(~45% flights / ~35% hotel). Interests: {interests}. Start with search_flights."
    )


def _agent_loop(llm, toolbox: Toolbox, request: TripRequest, currency: str) -> None:
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _context_message(request, currency)},
    ]
    for _ in range(MAX_AGENT_ITERATIONS):
        reply = llm.chat(messages, TOOL_SCHEMAS)
        if not reply.tool_calls:
            if toolbox.selections is not None:
                return
            messages.append({"role": "assistant", "content": reply.content or ""})
            messages.append(
                {"role": "user", "content": "Keep going with the tools; you must end by calling finalize_plan with valid ids."}
            )
            continue
        messages.append(
            {
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in reply.tool_calls
                ],
            }
        )
        for tc in reply.tool_calls:
            result = toolbox.execute(tc.name, tc.arguments)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        if toolbox.selections is not None:
            return
    raise OrchestrationError("agent loop ended without a valid finalized plan")


def run_pipeline(
    request: TripRequest,
    settings: Settings,
    emit: EmitFn | None = None,
    clients: tuple[FlightsClient, HotelsClient, PlacesClient, RoutesClient] | None = None,
    llm=None,
) -> TripPlan:
    emit = emit or (lambda stage, message: None)
    if clients is not None:
        flights, hotels, places, routes = clients
    else:
        # Fake mode gets its own cache file so demo runs stay hermetic and
        # never replay live-mode responses cached under the same signatures.
        cache_path = f"{settings.cache_path}.fake" if settings.fake_apis else settings.cache_path
        cache = Cache(
            cache_path,
            ttls={
                "flights": settings.cache_ttl_flights,
                "hotels": settings.cache_ttl_hotels,
                "places": settings.cache_ttl_places,
                "routes": settings.cache_ttl_routes,
            },
        )
        if settings.fake_apis:
            flights, hotels, places, routes = build_fake_clients(cache, settings.currency)
        else:
            flights = FlightsClient(settings.serpapi_api_key, currency=settings.currency, cache=cache)
            hotels = HotelsClient(settings.serpapi_api_key, currency=settings.currency, cache=cache)
            places = PlacesClient(settings.google_maps_api_key, cache=cache)
            routes = RoutesClient(settings.google_maps_api_key, cache=cache)
    if llm is None:
        llm = FakeLLM() if settings.fake_apis else GroqLLM(settings.groq_api_key, settings.groq_model)

    store = GroundingStore()
    data_quality: list[DataQualityNote] = []
    toolbox = Toolbox(
        request=request,
        store=store,
        flights=flights,
        hotels=hotels,
        places=places,
        emit=emit,
        data_quality=data_quality,
    )

    emit("llm", "Waking up your travel agent…")
    try:
        _agent_loop(llm, toolbox, request, settings.currency)
    except Exception as exc:  # LLM/provider failure — degrade, don't die
        if toolbox.selections is None:
            data_quality.append(
                DataQualityNote(source="llm", level="degraded", message=f"LLM orchestration failed ({exc}); deterministic fallback used")
            )
            emit("llm", "Agent hiccup — switching to autopilot…")
            _agent_loop(FakeLLM(), toolbox, request, settings.currency)
    if toolbox.selections is None:
        raise OrchestrationError("no valid plan could be produced")
    selections = toolbox.selections

    # ---------------- deterministic phase: no LLM beyond this point ----------------
    emit("restaurants", "Scouting places to eat…")
    restaurants: list[POI] = []
    try:
        restaurants = store.add_all("rest", places.search_restaurants(request.destination_city))
    except ApiError as exc:
        data_quality.append(DataQualityNote(source="places", level="degraded", message=f"restaurant search failed: {exc}"))

    # Deterministic top-up: if the LLM picked fewer than ~5 attractions per
    # day, fill from the remaining grounded pool by value so the solver has
    # enough material for dense days. Still 100% real, store-registered POIs.
    selected_ids = list(dict.fromkeys(selections.poi_ids))
    target = 5 * request.full_days
    if len(selected_ids) < target:
        chosen = set(selected_ids)
        pool = sorted(
            (p for p in store.all_of_prefix("poi") if isinstance(p, POI) and p.id not in chosen),
            key=lambda p: -p.value_score,
        )
        selected_ids += [p.id for p in pool[: target - len(selected_ids)]]

    selected_pois = [store.get_poi(pid, "attraction") for pid in selected_ids]
    hotel = store.get_hotel(selections.hotel_id) if selections.hotel_id else None
    fallback_points = [p.location for p in selected_pois] or [r.location for r in restaurants]
    hotel_location = (hotel.location if hotel else None) or (
        _centroid(fallback_points) if fallback_points else LatLng(lat=0.0, lng=0.0)
    )

    emit("matrix", "Timing the routes between stops…")
    points = [hotel_location] + [p.location for p in selected_pois]
    matrix = routes.travel_time_matrix(points)
    if matrix.any_estimated:
        data_quality.append(
            DataQualityNote(source="routes", level="degraded", message="some travel times are distance-based estimates")
        )

    emit("solving", "Cooking up your itinerary…")
    itinerary_dates = [request.departure_date + timedelta(days=i + 1) for i in range(request.full_days)]
    solver_result = solve(
        SolverInput(
            attractions=selected_pois,
            restaurants=restaurants,
            hotel_location=hotel_location,
            matrix=matrix,
            matrix_index={p.id: i + 1 for i, p in enumerate(selected_pois)},
            days=itinerary_dates,
        )
    )

    emit("assembling", "Packing it all together…")
    plan = assemble_plan(request, store, selections, solver_result, matrix, data_quality)
    emit("done", "Your trip is ready!")
    return plan


def _centroid(points: list[LatLng]) -> LatLng:
    return LatLng(
        lat=sum(p.lat for p in points) / len(points),
        lng=sum(p.lng for p in points) / len(points),
    )
