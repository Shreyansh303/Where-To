"""Deterministic itinerary solver.

Given LLM-*selected* (but never LLM-scheduled) POIs, a hotel, restaurants and
a real travel-time matrix, produce a day-by-day schedule:

1. `cluster_pois` groups attractions geographically, one cluster per day.
2. Clusters are assigned to concrete dates by scoring every permutation
   (k ≤ 7, so brute force is cheap) against opening weekdays.
3. Per day: nearest-neighbor route from the hotel, improved by 2-opt over the
   directed travel-time matrix.
4. A timeline walk enforces opening hours and the daily time budget. Days that
   overflow drop their lowest `value_score` POIs first. POIs closed on their
   day are swapped to a day where they're open when capacity allows,
   otherwise dropped with an explicit reason.
5. Breakfast / lunch / dinner are inserted from the restaurant pool, nearest
   to the route position at that hour (travel to meals uses flagged haversine
   estimates — restaurants are chosen *because* they're adjacent).

Known limits (by design, documented for reviewers): greedy + 2-opt is not
globally optimal; one open-hours window per visit is honored (no split
visits); meal travel is estimated rather than routed.
"""

import itertools
from dataclasses import dataclass, field
from datetime import date as Date

from ..models import POI, DroppedPOI, ItineraryDay, ItineraryStop, LatLng, SolverResult
from ..models.matrix import TravelMatrix
from ..util.geo import estimate_travel_minutes, haversine_km
from .clustering import cluster_pois

MEAL_ANCHORS = [("breakfast", 9 * 60, 40), ("lunch", 12 * 60 + 30, 70), ("dinner", 19 * 60, 90)]
LUNCH_TRIGGER = 12 * 60 + 30
DINNER_LATEST_END = 22 * 60


@dataclass
class SolverInput:
    attractions: list[POI]
    restaurants: list[POI]
    hotel_location: LatLng
    matrix: TravelMatrix  # over [hotel] + attractions, hotel at index 0
    matrix_index: dict[str, int]  # poi.id -> matrix row/col
    days: list[Date]
    day_start: int = 9 * 60
    day_end: int = 21 * 60


@dataclass
class _DayPlan:
    date: Date
    weekday: int
    pois: list[POI] = field(default_factory=list)


def solve(inp: SolverInput) -> SolverResult:
    dropped: list[DroppedPOI] = []
    open_pois, closed_everywhere = _filter_openable(inp.attractions, inp.days)
    dropped += [DroppedPOI(poi_id=p.id, reason="closed on every trip day") for p in closed_everywhere]

    k = len(inp.days)
    clusters = cluster_pois(open_pois, k) if open_pois else [[] for _ in range(k)]
    day_plans = _assign_clusters_to_days(clusters, inp.days)
    _swap_closed_pois(day_plans, dropped)

    result_days: list[ItineraryDay] = []
    total_travel = 0
    used_restaurants: set[str] = set()
    for plan in day_plans:
        ordered = _order_route(plan.pois, inp)
        day, day_dropped, travel = _schedule_day(plan, ordered, inp, used_restaurants)
        dropped += day_dropped
        total_travel += travel
        result_days.append(day)

    return SolverResult(days=result_days, dropped=dropped, total_travel_minutes=total_travel)


# ------------------------------------------------------------- opening hours
def _openable_on(poi: POI, weekday: int) -> bool:
    """Open (or hours unknown) at some point on this weekday."""
    if poi.opening_hours is None:
        return True
    return bool(poi.opening_hours.windows.get(weekday))


def _filter_openable(pois: list[POI], days: list[Date]) -> tuple[list[POI], list[POI]]:
    weekdays = {d.weekday() for d in days}
    open_pois = [p for p in pois if any(_openable_on(p, wd) for wd in weekdays)]
    closed = [p for p in pois if p not in open_pois]
    return open_pois, closed


def _assign_clusters_to_days(clusters: list[list[POI]], days: list[Date]) -> list[_DayPlan]:
    """Brute-force the cluster→date assignment maximizing open-day matches."""
    k = len(days)
    best_perm, best_score = tuple(range(k)), -1
    for perm in itertools.permutations(range(k)):
        score = sum(
            sum(1 for p in clusters[perm[d]] if _openable_on(p, days[d].weekday()))
            for d in range(k)
        )
        if score > best_score:
            best_perm, best_score = perm, score
    return [
        _DayPlan(date=days[d], weekday=days[d].weekday(), pois=list(clusters[best_perm[d]]))
        for d in range(k)
    ]


def _swap_closed_pois(day_plans: list[_DayPlan], dropped: list[DroppedPOI]) -> None:
    """POIs closed on their assigned day move to a day they're open on
    (lightest day first); if none exists they're dropped with a reason."""
    if not day_plans:
        return
    capacity = max(len(p.pois) for p in day_plans) + 1
    for plan in day_plans:
        for poi in [p for p in plan.pois if not _openable_on(p, plan.weekday)]:
            plan.pois.remove(poi)
            candidates = sorted(
                (o for o in day_plans if o is not plan and _openable_on(poi, o.weekday)),
                key=lambda o: len(o.pois),
            )
            if candidates and len(candidates[0].pois) < capacity:
                candidates[0].pois.append(poi)
            else:
                dropped.append(
                    DroppedPOI(poi_id=poi.id, reason=f"closed on {plan.date:%A} and no other day had room")
                )


# ------------------------------------------------------------------ routing
def _order_route(pois: list[POI], inp: SolverInput) -> list[POI]:
    """Nearest-neighbor from the hotel, then 2-opt over the directed matrix."""
    if len(pois) <= 1:
        return list(pois)
    idx = inp.matrix_index
    m = inp.matrix.minutes

    remaining = list(pois)
    route: list[POI] = []
    current = 0  # hotel row
    while remaining:
        nxt = min(remaining, key=lambda p: m[current][idx[p.id]])
        route.append(nxt)
        remaining.remove(nxt)
        current = idx[nxt.id]

    def cost(order: list[POI]) -> int:
        total, cur = 0, 0
        for p in order:
            total += m[cur][idx[p.id]]
            cur = idx[p.id]
        return total

    improved = True
    while improved:
        improved = False
        for i in range(len(route) - 1):
            for j in range(i + 1, len(route)):
                candidate = route[:i] + route[i : j + 1][::-1] + route[j + 1 :]
                if cost(candidate) < cost(route):
                    route = candidate
                    improved = True
    return route


# --------------------------------------------------------------- scheduling
def _schedule_day(
    plan: _DayPlan,
    ordered: list[POI],
    inp: SolverInput,
    used_restaurants: set[str],
) -> tuple[ItineraryDay, list[DroppedPOI], int]:
    idx = inp.matrix_index
    m, est = inp.matrix.minutes, inp.matrix.estimated
    stops: list[ItineraryStop] = []
    dropped: list[DroppedPOI] = []

    def route_travel(seq: list[POI]) -> int:
        total, cur = 0, 0
        for p in seq:
            total += m[cur][idx[p.id]]
            cur = idx[p.id]
        return total

    # Pre-trim to the daily time budget (visits + route travel + meal time),
    # dropping lowest-value POIs first — the documented policy. Without the
    # travel term the timeline walk would overflow at the *end* of the route
    # and silently sacrifice whatever POI happened to be scheduled last.
    budget = inp.day_end - inp.day_start
    meal_overhead = 110 if inp.restaurants else 0  # breakfast 40 + lunch 70
    keep = list(ordered)
    while keep and sum(p.est_visit_minutes for p in keep) + route_travel(keep) + meal_overhead > budget:
        victim = min(keep, key=lambda p: p.value_score)
        keep.remove(victim)
        dropped.append(DroppedPOI(poi_id=victim.id, reason="day time budget exceeded (lowest value first)"))
    ordered = keep

    t = inp.day_start
    current_idx = 0  # hotel
    current_loc = inp.hotel_location
    total_travel = 0
    lunch_done = False

    breakfast = _pick_restaurant(inp.restaurants, inp.hotel_location, used_restaurants)
    if breakfast:
        t = _insert_meal(stops, breakfast, "breakfast", t, current_loc, 40)
        current_loc = breakfast.location

    for poi in ordered:
        if not lunch_done and t >= LUNCH_TRIGGER:
            lunch = _pick_restaurant(inp.restaurants, current_loc, used_restaurants)
            if lunch:
                t = _insert_meal(stops, lunch, "lunch", t, current_loc, 70)
                current_loc = lunch.location
            lunch_done = True

        travel = m[current_idx][idx[poi.id]]
        travel_estimated = est[current_idx][idx[poi.id]]
        arrive = t + travel
        note = None

        if poi.opening_hours is not None:
            opens = poi.opening_hours.opens_at(plan.weekday)
            if opens is not None and arrive < opens:
                note = f"waits for opening at {_fmt(opens)}"
                arrive = opens
            depart = arrive + poi.est_visit_minutes
            if not poi.opening_hours.is_open_during(plan.weekday, arrive, min(depart, arrive + 1)):
                dropped.append(DroppedPOI(poi_id=poi.id, reason=f"closed at reachable time on {plan.date:%A}"))
                continue
        else:
            note = "opening hours unknown — verify before visiting"
            depart = arrive + poi.est_visit_minutes

        depart = arrive + poi.est_visit_minutes
        if depart > inp.day_end:
            dropped.append(DroppedPOI(poi_id=poi.id, reason="does not fit in the daily time window"))
            continue

        stops.append(
            ItineraryStop(
                poi_id=poi.id,
                arrive_min=arrive,
                depart_min=depart,
                travel_from_prev_minutes=travel,
                travel_mode="transit",
                travel_is_estimate=travel_estimated,
                note=note,
            )
        )
        total_travel += travel
        t = depart
        current_idx = idx[poi.id]
        current_loc = poi.location

    if stops and t + 90 <= DINNER_LATEST_END:
        dinner = _pick_restaurant(inp.restaurants, current_loc, used_restaurants)
        if dinner:
            t = _insert_meal(stops, dinner, "dinner", max(t, 19 * 60), current_loc, 90)

    day = ItineraryDay(date=plan.date, weekday=plan.weekday, stops=stops)
    return day, dropped, total_travel


def _insert_meal(
    stops: list[ItineraryStop],
    restaurant: POI,
    meal: str,
    t: int,
    from_loc: LatLng,
    duration: int,
) -> int:
    travel = estimate_travel_minutes(from_loc, restaurant.location)
    arrive = t + travel
    stops.append(
        ItineraryStop(
            poi_id=restaurant.id,
            arrive_min=arrive,
            depart_min=arrive + duration,
            travel_from_prev_minutes=travel,
            travel_mode="walk/transit",
            travel_is_estimate=True,
            meal=meal,
        )
    )
    return arrive + duration


def _pick_restaurant(restaurants: list[POI], near: LatLng, used: set[str]) -> POI | None:
    """Nearest good restaurant not used yet this trip: score = distance km
    plus a penalty for weak ratings."""
    pool = [r for r in restaurants if r.id not in used] or list(restaurants)
    if not pool:
        return None
    best = min(pool, key=lambda r: haversine_km(near, r.location) + (5.0 - (r.rating or 3.5)))
    used.add(best.id)
    return best


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
