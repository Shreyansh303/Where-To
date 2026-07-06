"""Output assembly — the last grounding checkpoint.

Builds the final TripPlan exclusively by resolving grounding ids back to the
stored API entities. Prices, names, times and hours are *copied* from those
entities; the only LLM-authored content is the clearly-scoped `commentary`
string carried through from finalize_plan.
"""

from urllib.parse import quote

from ..grounding import GroundingStore, TripSelections
from ..models import (
    POI,
    BudgetBreakdown,
    DataQualityNote,
    LatLng,
    PlanDay,
    ResolvedStop,
    SolverResult,
    TripPlan,
    TripRequest,
)
from ..models.matrix import TravelMatrix
from ..util.geo import haversine_km

MAX_EXTRAS_PER_DAY = 3


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _unscheduled_attractions(store: GroundingStore, solver_result: SolverResult) -> list[POI]:
    """Every store-registered attraction that didn't make the schedule —
    real, grounded 'if you have time' material."""
    scheduled = {s.poi_id for day in solver_result.days for s in day.stops}
    return [
        p
        for p in store.all_of_prefix("poi")
        if isinstance(p, POI) and p.kind == "attraction" and p.id not in scheduled
    ]


def _pick_extras(pool: list[POI], stops: list[ResolvedStop]) -> list[POI]:
    """Up to MAX_EXTRAS_PER_DAY unscheduled POIs nearest this day's route,
    weighted by rating. Picked extras leave the pool so days don't repeat."""
    anchors = [s.poi.location for s in stops if s.meal is None] or [s.poi.location for s in stops]
    if not anchors or not pool:
        return []
    center = LatLng(
        lat=sum(a.lat for a in anchors) / len(anchors),
        lng=sum(a.lng for a in anchors) / len(anchors),
    )
    ranked = sorted(pool, key=lambda p: haversine_km(center, p.location) + (5.0 - (p.rating or 3.5)))
    picked = ranked[:MAX_EXTRAS_PER_DAY]
    for p in picked:
        pool.remove(p)
    return picked


def _getting_around(solver_result: SolverResult, matrix: TravelMatrix) -> str:
    legs = [s for day in solver_result.days for s in day.stops if s.travel_from_prev_minutes > 0]
    if not legs:
        return "All stops are within easy reach of each other."
    real = [s for s in legs if not s.travel_is_estimate]
    avg = round(sum(s.travel_from_prev_minutes for s in legs) / len(legs))
    parts = [
        f"Getting between stops takes about {avg} minutes on average, mostly by public transit.",
        f"{len(real)} of {len(legs)} legs use live Google transit times"
        + ("; the rest are distance-based estimates." if len(real) < len(legs) else "."),
    ]
    if matrix.any_estimated:
        parts.append("Some routing data was unavailable, so flagged legs deserve a quick check locally.")
    return " ".join(parts)


def assemble_plan(
    request: TripRequest,
    store: GroundingStore,
    selections: TripSelections,
    solver_result: SolverResult,
    matrix: TravelMatrix,
    data_quality: list[DataQualityNote],
) -> TripPlan:
    outbound = store.get_flight(selections.outbound_flight_id, "outbound")
    inbound = store.get_flight(selections.return_flight_id, "return")
    hotel = store.get_hotel(selections.hotel_id) if selections.hotel_id else None
    if hotel is not None and hotel.maps_url is None:
        hotel.maps_url = (
            "https://www.google.com/maps/search/?api=1&query="
            + quote(f"{hotel.name} {request.destination_city}")
        )

    extras_pool = _unscheduled_attractions(store, solver_result)
    days: list[PlanDay] = []
    for day in solver_result.days:
        stops = [
            ResolvedStop(
                poi=store.get_poi(s.poi_id),
                arrive=_fmt(s.arrive_min),
                depart=_fmt(s.depart_min),
                travel_from_prev_minutes=s.travel_from_prev_minutes,
                travel_mode=s.travel_mode,
                travel_is_estimate=s.travel_is_estimate,
                meal=s.meal,
                note=s.note,
            )
            for s in day.stops
        ]
        days.append(
            PlanDay(
                date=day.date,
                weekday_name=day.date.strftime("%A"),
                stops=stops,
                extras=_pick_extras(extras_pool, stops),
            )
        )

    # Round-trip totals: the return-leg option carries the final price.
    flights_total = inbound.price
    hotel_total = None
    if hotel is not None:
        hotel_total = hotel.total_rate or (hotel.rate_per_night or 0) * request.nights
    remaining = request.budget - flights_total - (hotel_total or 0)

    dropped = [
        f"{store.get_poi(d.poi_id).name}: {d.reason}" if store.has(d.poi_id) else d.reason
        for d in solver_result.dropped
    ]

    return TripPlan(
        request=request,
        outbound_flight=outbound,
        return_flight=inbound,
        hotel=hotel,
        days=days,
        getting_around=_getting_around(solver_result, matrix),
        budget=BudgetBreakdown(
            currency=outbound.currency,
            total=request.budget,
            flights_total=flights_total,
            hotel_total=hotel_total,
            remaining_for_activities=round(remaining, 2),
        ),
        data_quality=data_quality,
        commentary=selections.commentary or None,
        dropped_pois=dropped,
    )
