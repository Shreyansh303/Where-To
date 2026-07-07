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


# Maps city names (lowercased) to practical transport advice.
# For cities not in this map, we fall back to generic advice.
_CITY_TRANSPORT: dict[str, str] = {
    "paris": "Paris is best explored via the Métro — fast, cheap, and covers every arrondissement. "
             "Grab a carnet (pack of 10 tickets) or a Navigo Easy card for seamless tap-and-go. "
             "The RER trains connect the city to airports and suburbs like Versailles.",
    "london": "The Tube (Underground) is the quickest way around London, with Oyster or contactless "
              "payment accepted everywhere. Double-decker buses and the Overground fill the gaps. "
              "The Elizabeth line links Heathrow to central London in ~35 minutes.",
    "tokyo": "Tokyo's rail network — JR lines, the Tokyo Metro, and Toei Subway — covers the entire city. "
             "Get a Suica or Pasmo IC card for tap-in/tap-out convenience on trains, buses, and even convenience stores.",
    "new york": "New York runs on the subway (24/7) and local buses. An OMNY contactless tap or a MetroCard "
                "gets you anywhere in all five boroughs. Yellow cabs and ride-shares fill in for late nights.",
    "rome": "Rome's two Metro lines (A and B) hit the major sights, while buses and trams cover the rest. "
            "Walking is often the best option in the historic center — most attractions are close together.",
    "barcelona": "Barcelona's Metro is clean and efficient, with 12 lines covering the city. "
                 "Pick up a T-Casual card for 10 trips across Metro, bus, and tram. "
                 "The Aerobus connects the airport to Plaça Catalunya in ~35 minutes.",
    "berlin": "Berlin's U-Bahn and S-Bahn rail networks blanket the city. "
              "Buy an AB zone day ticket for unlimited rides on trains, trams, and buses within central Berlin.",
    "amsterdam": "Trams, buses, and the Metro all accept the OV-chipkaart (or contactless payment). "
                 "Most of central Amsterdam is walkable, and cycling is the most local way to get around — "
                 "bike rentals are everywhere.",
    "istanbul": "Istanbul's Istanbulkart works on the Metro, trams, ferries, and buses. "
                "The Marmaray rail tunnel links the European and Asian sides, "
                "and the Bosphorus ferries are both practical and scenic.",
    "singapore": "Singapore's MRT is modern, air-conditioned, and covers the entire island. "
                 "Use an EZ-Link or SimplyGo contactless card on trains and buses. "
                 "Grab/ride-hailing is widely available and affordable for shorter trips.",
    "dubai": "The Dubai Metro (Red and Green lines) connects major attractions, malls, and airports. "
             "RTA buses and the Palm Monorail fill in the gaps. "
             "Taxis and ride-hailing (Careem/Uber) are affordable and air-conditioned.",
    "bangkok": "Bangkok's BTS Skytrain and MRT subway cover the main areas and beat the traffic. "
               "Grab a Rabbit card for tap-and-go. River boats on the Chao Phraya are cheap and scenic. "
               "Tuk-tuks and Grab ride-hailing work well for shorter hops.",
    "lisbon": "Lisbon's Metro is small but efficient for the main sights. "
              "The iconic Tram 28 winds through historic Alfama, and the Viva Viagem card works "
              "across Metro, buses, trams, and ferries.",
    "prague": "Prague's integrated transit system uses Metro, trams, and buses — all on one ticket. "
              "The historic center is compact and best explored on foot, "
              "with trams for getting between neighborhoods.",
    "seoul": "Seoul's subway system is one of the world's best — fast, clean, and incredibly well-signed in English. "
             "Get a T-money card for trains, buses, and even taxis.",
    "sydney": "Sydney's Opal card (or contactless payment) works on trains, buses, ferries, and light rail. "
              "The ferry to Manly is a must-do — it doubles as a scenic harbor cruise.",
    "delhi": "Delhi Metro is the fastest way to navigate the city, covering major areas from the airport to Old Delhi. "
             "Use a Delhi Metro card for tap-and-go. Auto-rickshaws and Uber/Ola fill the last-mile gaps.",
    "mumbai": "Mumbai's local trains are the city's lifeline — fast and frequent. "
              "The Mumbai Metro supplements coverage. "
              "Use auto-rickshaws and Uber/Ola for areas not covered by rail.",
    "kuala lumpur": "KL's rail network includes the LRT, MRT, KTM, and Monorail — all linked at major interchange stations. "
                   "Get a Touch 'n Go card for trains, buses, and toll roads. "
                   "Grab ride-hailing is cheap and widely used.",
}


def _getting_around(destination_city: str) -> str:
    """Return practical transport advice for the destination city."""
    key = destination_city.strip().lower()
    if key in _CITY_TRANSPORT:
        return _CITY_TRANSPORT[key]
    # Generic fallback for cities not in the curated map.
    return (
        f"Most of {destination_city} can be explored using local public transit — "
        f"look for metro or subway systems, city buses, and trams. "
        f"Ride-hailing apps (Uber, Bolt, or local equivalents) are usually available for shorter trips. "
        f"Consider picking up a day pass or transit card at the airport for unlimited rides."
    )


def assemble_plan(
    request: TripRequest,
    store: GroundingStore,
    selections: TripSelections,
    solver_result: SolverResult,
    matrix: TravelMatrix,
    data_quality: list[DataQualityNote],
    entry_costs: dict[str, str] | None = None,
    meal_cost: str | None = None,
) -> TripPlan:
    outbound = store.get_flight(selections.outbound_flight_id, "outbound")
    inbound = store.get_flight(selections.return_flight_id, "return")
    hotel = store.get_hotel(selections.hotel_id) if selections.hotel_id else None
    if hotel is not None and hotel.maps_url is None:
        hotel.maps_url = (
            "https://www.google.com/maps/search/?api=1&query="
            + quote(f"{hotel.name} {request.destination_city}")
        )

    _costs = entry_costs or {}
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
                est_entry_cost=_costs.get(s.poi_id),
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
        getting_around=_getting_around(request.destination_city),
        budget=BudgetBreakdown(
            currency=outbound.currency,
            total=request.budget,
            flights_total=flights_total,
            hotel_total=hotel_total,
            remaining_for_activities=round(remaining, 2),
            est_meal_cost=meal_cost,
        ),
        data_quality=data_quality,
        commentary=selections.commentary or None,
        dropped_pois=dropped,
    )
