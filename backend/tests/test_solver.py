"""Constraint solver tests — synthetic geometry, no APIs, fully deterministic."""

from datetime import date

from app.models import POI, LatLng, OpeningHours
from app.models.matrix import TravelMatrix
from app.solver import SolverInput, solve
from app.solver.clustering import cluster_pois
from app.solver.itinerary import _order_route
from app.util.geo import estimate_travel_minutes

HOTEL = LatLng(lat=48.8600, lng=2.3500)
DAY1 = date(2026, 8, 11)  # Tuesday
DAY2 = date(2026, 8, 12)  # Wednesday


def make_poi(pid, lat, lng, rating=4.5, visit=60, hours=None, kind="attraction", interests=None):
    return POI(
        id=pid,
        place_id=f"g_{pid}",
        name=pid,
        kind=kind,
        location=LatLng(lat=lat, lng=lng),
        rating=rating,
        est_visit_minutes=visit,
        opening_hours=hours,
        interest_tags=interests or [],
    )


def build_input(attractions, restaurants=None, days=None, **kwargs) -> SolverInput:
    points = [HOTEL] + [p.location for p in attractions]
    n = len(points)
    minutes = [
        [0 if i == j else estimate_travel_minutes(points[i], points[j]) for j in range(n)]
        for i in range(n)
    ]
    estimated = [[False] * n for _ in range(n)]
    return SolverInput(
        attractions=attractions,
        restaurants=restaurants or [],
        hotel_location=HOTEL,
        matrix=TravelMatrix(minutes, estimated),
        matrix_index={p.id: i + 1 for i, p in enumerate(attractions)},
        days=days or [DAY1, DAY2],
        **kwargs,
    )


# --------------------------------------------------------------- clustering
def test_clustering_separates_obvious_geographic_groups():
    west = [make_poi(f"w{i}", 48.86 + i * 0.001, 2.29) for i in range(4)]
    east = [make_poi(f"e{i}", 48.86 + i * 0.001, 2.40) for i in range(4)]
    clusters = cluster_pois(west + east, 2)
    sides = [{p.id[0] for p in c} for c in clusters]
    assert {"w"} in sides and {"e"} in sides


def test_clustering_respects_capacity_balance():
    pois = [make_poi(f"p{i}", 48.85 + i * 0.002, 2.30 + (i % 3) * 0.01) for i in range(9)]
    clusters = cluster_pois(pois, 3)
    assert sorted(len(c) for c in clusters) == [3, 3, 3]


# ------------------------------------------------------------------ routing
def test_two_opt_reaches_brute_force_optimum_on_square():
    from itertools import permutations

    # POIs on a square; NN + 2-opt must match the brute-force optimal
    # open-path cost from the hotel (i.e. no crossing detours survive).
    a = make_poi("a", 48.860, 2.300)
    b = make_poi("b", 48.860, 2.340)
    c = make_poi("c", 48.900, 2.340)
    d = make_poi("d", 48.900, 2.300)
    pois = [a, c, b, d]  # scrambled input order
    inp = build_input(pois)
    m, idx = inp.matrix.minutes, inp.matrix_index

    def cost(order):
        total, cur = 0, 0
        for p in order:
            total += m[cur][idx[p.id]]
            cur = idx[p.id]
        return total

    best = min(cost(list(perm)) for perm in permutations(pois))
    assert cost(_order_route(pois, inp)) == best


def test_route_cost_never_worse_than_input_order():
    pois = [make_poi(f"p{i}", 48.85 + (i * 7 % 5) * 0.01, 2.30 + (i * 3 % 4) * 0.012) for i in range(6)]
    inp = build_input(pois, days=[DAY1])
    m, idx = inp.matrix.minutes, inp.matrix_index

    def cost(order):
        total, cur = 0, 0
        for p in order:
            total += m[cur][idx[p.id]]
            cur = idx[p.id]
        return total

    assert cost(_order_route(pois, inp)) <= cost(pois)


# -------------------------------------------------------------- scheduling
def test_full_solve_visits_everything_when_feasible():
    pois = [make_poi(f"p{i}", 48.855 + i * 0.004, 2.30 + i * 0.008, visit=90) for i in range(6)]
    result = solve(build_input(pois))
    scheduled = [s.poi_id for day in result.days for s in day.stops if s.meal is None]
    assert sorted(scheduled) == sorted(p.id for p in pois)
    assert result.dropped == []


def test_solver_is_deterministic():
    pois = [make_poi(f"p{i}", 48.85 + (i % 4) * 0.01, 2.30 + (i % 3) * 0.015) for i in range(8)]
    r1 = solve(build_input(pois))
    r2 = solve(build_input(pois))
    assert r1.model_dump() == r2.model_dump()


def test_stop_times_are_sequential_and_within_window():
    pois = [make_poi(f"p{i}", 48.855 + i * 0.003, 2.31 + i * 0.006) for i in range(5)]
    result = solve(build_input(pois))
    for day in result.days:
        last_depart = 0
        for stop in day.stops:
            assert stop.arrive_min >= last_depart
            assert stop.depart_min > stop.arrive_min
            last_depart = stop.depart_min


def test_overloaded_day_drops_lowest_value_first():
    # 1-day trip, way too much to see: 8 POIs x 3h > 12h window
    pois = [
        make_poi(f"p{i}", 48.855 + i * 0.002, 2.31, rating=3.0 + i * 0.2, visit=180)
        for i in range(8)
    ]
    result = solve(build_input(pois, days=[DAY1]))
    assert result.dropped, "some POIs must be dropped"
    dropped_ids = {d.poi_id for d in result.dropped}
    assert "p0" in dropped_ids  # lowest rating drops first
    assert "p7" not in dropped_ids  # highest rating survives


def test_poi_closed_on_all_days_is_dropped_with_reason():
    sunday_only = OpeningHours(windows={6: [(540, 1080)]})
    poi = make_poi("closed", 48.86, 2.31, hours=sunday_only)
    result = solve(build_input([poi, make_poi("open", 48.858, 2.32)], days=[DAY1, DAY2]))
    assert any(d.poi_id == "closed" and "closed on every trip day" in d.reason for d in result.dropped)


def test_poi_closed_one_day_moves_to_open_day():
    # Open Wednesday (weekday 2) only; trip covers Tue+Wed → must land on Wed.
    wed_only = OpeningHours(windows={2: [(540, 1200)]})
    pois = [
        make_poi("wed_poi", 48.858, 2.295, hours=wed_only),
        make_poi("free1", 48.859, 2.30),
        make_poi("free2", 48.90, 2.40),
        make_poi("free3", 48.901, 2.401),
    ]
    result = solve(build_input(pois, days=[DAY1, DAY2]))
    wed = next(d for d in result.days if d.date == DAY2)
    assert "wed_poi" in [s.poi_id for s in wed.stops]


def test_late_opening_waits_and_notes():
    opens_11 = OpeningHours(windows={1: [(11 * 60, 20 * 60)]})  # Tuesday 11:00–20:00
    poi = make_poi("late", 48.859, 2.351, hours=opens_11)
    result = solve(build_input([poi], days=[DAY1]))
    stop = next(s for d in result.days for s in d.stops if s.poi_id == "late")
    assert stop.arrive_min == 11 * 60
    assert "waits for opening" in (stop.note or "")


def test_unknown_hours_flagged_not_dropped():
    poi = make_poi("mystery", 48.86, 2.34, hours=None)
    result = solve(build_input([poi], days=[DAY1]))
    stop = next(s for d in result.days for s in d.stops if s.poi_id == "mystery")
    assert "verify" in (stop.note or "")
    assert not result.dropped


# -------------------------------------------------------------------- meals
def test_meals_inserted_at_sane_times():
    pois = [make_poi(f"p{i}", 48.855 + i * 0.003, 2.31 + i * 0.005, visit=100) for i in range(4)]
    restaurants = [
        make_poi(f"r{i}", 48.856 + i * 0.004, 2.312 + i * 0.006, kind="restaurant", rating=4.4)
        for i in range(8)
    ]
    result = solve(build_input(pois, restaurants=restaurants, days=[DAY1]))
    day = result.days[0]
    meals = {s.meal: s for s in day.stops if s.meal}
    assert {"breakfast", "lunch", "dinner"} <= set(meals)
    assert meals["breakfast"].arrive_min < 11 * 60
    assert meals["lunch"].arrive_min >= 12 * 60 + 30
    assert meals["dinner"].arrive_min >= 19 * 60
    # meal travel is an estimate by design and must be flagged
    assert all(m.travel_is_estimate for m in meals.values())


def test_restaurants_not_repeated_across_days():
    pois = [make_poi(f"p{i}", 48.855 + i * 0.004, 2.31 + i * 0.008, visit=100) for i in range(6)]
    restaurants = [
        make_poi(f"r{i}", 48.855 + i * 0.003, 2.31 + i * 0.004, kind="restaurant") for i in range(10)
    ]
    result = solve(build_input(pois, restaurants=restaurants, days=[DAY1, DAY2]))
    meal_ids = [s.poi_id for d in result.days for s in d.stops if s.meal]
    assert len(meal_ids) == len(set(meal_ids))
