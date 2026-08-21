"""Fact-card chunker — turns a finished TripPlan into a retrieval corpus.

Chunks are *rendered sentences*, not JSON fragments: the retriever matches a
traveller's phrasing ("when do I get home", "how much is the Louvre") against
prose, and the answering model is handed text it can quote directly. Every
chunk is derived from the resolved plan, so the grounding chain that produced
the plan also backs every word Miles can say. LLM-authored commentary is
deliberately excluded — Miles cites facts, not prose.

Typical corpus for a 4-day trip: ~60-120 chunks.
"""

from typing import Literal

from pydantic import BaseModel

from ..models import POI, PlanDay, ResolvedStop, TripPlan
from ..models.travel import FlightOption, HotelOption

ChunkType = Literal[
    "flight_out",
    "flight_ret",
    "hotel",
    "day_summary",
    "stop",
    "extra",
    "dropped",
    "budget",
    "data_quality",
    "getting_around",
]


class Chunk(BaseModel):
    id: str  # stable within a plan, e.g. "stop_2_3" — cited back to the client
    text: str
    type: ChunkType
    day: int | None = None  # 1-based itinerary day, when the fact belongs to one
    poi_id: str | None = None
    source_url: str | None = None
    label: str  # human-readable, shown as a citation chip


def build_corpus(plan: TripPlan) -> list[Chunk]:
    """Render the whole plan as fact cards, in reading order."""
    chunks: list[Chunk] = []
    if plan.outbound_flight is not None:
        chunks.append(_flight_chunk(plan, plan.outbound_flight, outbound=True))
    if plan.return_flight is not None:
        chunks.append(_flight_chunk(plan, plan.return_flight, outbound=False))
    if plan.hotel is not None:
        chunks.append(_hotel_chunk(plan, plan.hotel))

    for index, day in enumerate(plan.days, start=1):
        chunks.append(_day_summary_chunk(index, day))
        for position, stop in enumerate(day.stops):
            chunks.append(_stop_chunk(index, day, position, stop))
        for position, extra in enumerate(day.extras):
            chunks.append(_extra_chunk(index, day, position, extra))

    for position, dropped in enumerate(plan.dropped_pois):
        chunks.append(_dropped_chunk(position, dropped))

    chunks.append(_budget_chunk(plan))
    for position, note in enumerate(plan.data_quality):
        chunks.append(
            Chunk(
                id=f"dq_{position}",
                type="data_quality",
                label=f"Heads up · {note.source}",
                text=(
                    f"Data quality note about the {note.source} data in this plan "
                    f"(level: {note.level}): {note.message}."
                ),
            )
        )
    if plan.getting_around:
        chunks.append(
            Chunk(
                id="getting_around",
                type="getting_around",
                label="Getting around",
                text=(
                    f"Getting around {plan.request.destination_city} — local transport "
                    f"advice: {plan.getting_around}"
                ),
            )
        )
    return chunks


# ---------------------------------------------------------------- renderers


def _flight_chunk(plan: TripPlan, flight: FlightOption, *, outbound: bool) -> Chunk:
    first, last = flight.segments[0], flight.segments[-1]
    leg = "Outbound" if outbound else "Return"
    route = (
        f"{plan.request.origin} to {plan.request.destination}"
        if outbound
        else f"{plan.request.destination} back home to {plan.request.origin}"
    )
    airlines = " + ".join(dict.fromkeys(s.airline for s in flight.segments))
    numbers = ", ".join(s.flight_number for s in flight.segments)
    stops = (
        "non-stop"
        if not flight.layover_airports
        else f"with a layover in {', '.join(flight.layover_airports)}"
    )
    # The return-leg option carries the final round-trip fare (SerpApi prices the
    # pair on the return search), so only that card may state a total.
    price = (
        f"The round-trip fare for both flights together is "
        f"{_money(flight.price, flight.currency)}."
        if not outbound
        else "The fare is quoted as a round-trip total on the return flight."
    )
    text = (
        f"{leg} flight, {route}. Departs {first.departure_airport}"
        f"{_named(first.departure_airport_name)} at {_when(first.departure_time)} and "
        f"arrives {last.arrival_airport}{_named(last.arrival_airport_name)} at "
        f"{_when(last.arrival_time)}. Flown by {airlines}, flight {numbers}, "
        f"{_duration(flight.total_duration_minutes)} in the air, {stops}. {price}"
    )
    return Chunk(
        id="flight_out" if outbound else "flight_ret",
        type="flight_out" if outbound else "flight_ret",
        label=f"{leg} flight",
        text=text,
    )


def _hotel_chunk(plan: TripPlan, hotel: HotelOption) -> Chunk:
    bits = [
        f"Your stay in {plan.request.destination_city} is {hotel.name}, booked for "
        f"{plan.request.nights} night(s) from {plan.request.departure_date} to "
        f"{plan.request.return_date} for {plan.request.travelers} traveler(s)."
    ]
    if hotel.hotel_class:
        bits.append(f"It is a {hotel.hotel_class}-star hotel.")
    if hotel.rating is not None:
        reviews = f" from {hotel.review_count:,} reviews" if hotel.review_count else ""
        bits.append(f"Guests rate it {hotel.rating}{reviews}.")
    if hotel.total_rate is not None:
        bits.append(f"The total stay costs {_money(hotel.total_rate, hotel.currency)}.")
    if hotel.rate_per_night is not None:
        bits.append(f"That is {_money(hotel.rate_per_night, hotel.currency)} per night.")
    if hotel.check_in_time or hotel.check_out_time:
        bits.append(
            f"Check-in {hotel.check_in_time or 'unspecified'}, "
            f"check-out {hotel.check_out_time or 'unspecified'}."
        )
    if hotel.amenities:
        bits.append(f"Amenities include {', '.join(hotel.amenities[:8])}.")
    if hotel.description:
        bits.append(hotel.description)
    return Chunk(
        id="hotel",
        type="hotel",
        label=f"Your stay · {hotel.name}",
        text=" ".join(bits),
        source_url=hotel.link,
    )


def _day_summary_chunk(index: int, day: PlanDay) -> Chunk:
    sights = [s for s in day.stops if s.meal is None]
    meals = [s for s in day.stops if s.meal is not None]
    bits = [
        f"Day {index} of the itinerary is {day.weekday_name}, {day.date}."
    ]
    if sights:
        listed = ", ".join(f"{s.poi.name} ({s.arrive}-{s.depart})" for s in sights)
        bits.append(f"The {len(sights)} scheduled stop(s) that day: {listed}.")
    else:
        bits.append("No attractions are scheduled that day — it is a free day.")
    if meals:
        bits.append(
            "Meals: "
            + ", ".join(f"{s.meal} at {s.poi.name} ({s.arrive})" for s in meals)
            + "."
        )
    if day.stops:
        bits.append(f"The day runs from {day.stops[0].arrive} to {day.stops[-1].depart}.")
    if day.extras:
        bits.append(
            "Optional nearby ideas if you have time: "
            + ", ".join(p.name for p in day.extras)
            + "."
        )
    return Chunk(
        id=f"day_{index}",
        type="day_summary",
        day=index,
        label=f"Day {index} · {day.weekday_name}",
        text=" ".join(bits),
    )


def _stop_chunk(index: int, day: PlanDay, position: int, stop: ResolvedStop) -> Chunk:
    what = (
        f"{stop.meal} at {stop.poi.name}"
        if stop.meal
        else f"a visit to {stop.poi.name}"
    )
    bits = [
        f"On day {index} ({day.weekday_name}, {day.date}) you have {what}, "
        f"from {stop.arrive} to {stop.depart}."
    ]
    if stop.is_full_day:
        bits.append("This is a whole-day outing that owns the entire day.")
    if stop.travel_from_prev_minutes > 0:
        approx = "roughly " if stop.travel_is_estimate else ""
        bits.append(
            f"Getting there takes {approx}{stop.travel_from_prev_minutes} minutes by "
            f"{stop.travel_mode} from the previous stop."
        )
    if stop.est_entry_cost:
        free = stop.est_entry_cost.strip().lower() == "free"
        bits.append(
            f"Entry to {stop.poi.name} is free."
            if free
            else f"Entry to {stop.poi.name} costs about {stop.est_entry_cost} per person "
            f"(a researched estimate, not a booked price)."
        )
    if stop.poi.rating is not None:
        reviews = f" from {stop.poi.review_count:,} reviews" if stop.poi.review_count else ""
        bits.append(f"It is rated {stop.poi.rating}{reviews}.")
    if stop.poi.address:
        bits.append(f"Address: {stop.poi.address}.")
    bits.append(f"The visit is budgeted at {stop.poi.est_visit_minutes} minutes.")
    if stop.note:
        bits.append(f"Note: {stop.note}")
    return Chunk(
        id=f"stop_{index}_{position}",
        type="stop",
        day=index,
        poi_id=stop.poi.id,
        source_url=stop.est_entry_cost_source,
        label=f"Day {index} · {stop.poi.name}",
        text=" ".join(bits),
    )


def _extra_chunk(index: int, day: PlanDay, position: int, poi: POI) -> Chunk:
    bits = [
        f"{poi.name} is an optional 'if you have time' idea for day {index} "
        f"({day.weekday_name}, {day.date}) — a real nearby place that is not on the "
        f"schedule, so nothing has been booked or timed for it."
    ]
    if poi.rating is not None:
        reviews = f" from {poi.review_count:,} reviews" if poi.review_count else ""
        bits.append(f"It is rated {poi.rating}{reviews}.")
    if poi.address:
        bits.append(f"Address: {poi.address}.")
    bits.append(f"A visit usually takes around {poi.est_visit_minutes} minutes.")
    return Chunk(
        id=f"extra_{index}_{position}",
        type="extra",
        day=index,
        poi_id=poi.id,
        label=f"If you have time · {poi.name}",
        text=" ".join(bits),
    )


def _dropped_chunk(position: int, dropped: str) -> Chunk:
    # assemble_plan renders these as "Name: reason" (or a bare reason when the
    # POI id could not be resolved).
    name, _, reason = dropped.partition(": ")
    subject = name if reason else dropped
    return Chunk(
        id=f"dropped_{position}",
        type="dropped",
        label=f"Not included · {subject}",
        text=(
            f"{subject} was considered for this trip but is NOT included in the "
            f"itinerary. Reason it was left out: {reason or dropped}."
        ),
    )


def _budget_chunk(plan: TripPlan) -> Chunk:
    b = plan.budget
    r = plan.request
    bits = [
        f"Trip and budget overview: {r.origin} to {r.destination_city} "
        f"({r.destination}), departing {r.departure_date} and returning "
        f"{r.return_date}, {r.nights} night(s) and {r.full_days} sightseeing day(s), "
        f"for {r.travelers} traveler(s).",
        f"The total budget is {_money(b.total, b.currency)}.",
    ]
    if b.flights_total is not None:
        bits.append(f"Round-trip flights cost {_money(b.flights_total, b.currency)}.")
    if b.hotel_total is not None:
        bits.append(f"The hotel costs {_money(b.hotel_total, b.currency)} in total.")
    if b.remaining_for_activities is not None:
        if b.remaining_for_activities < 0:
            bits.append(
                f"That puts the trip over budget by "
                f"{_money(abs(b.remaining_for_activities), b.currency)} before food and "
                f"activities."
            )
        else:
            bits.append(
                f"That leaves {_money(b.remaining_for_activities, b.currency)} for "
                f"activities, food and everything else."
            )
    if b.est_meal_cost:
        bits.append(f"One mid-range meal is estimated at {b.est_meal_cost} per person.")
    return Chunk(id="budget", type="budget", label="Budget", text=" ".join(bits))


# ---------------------------------------------------------------- formatting


def _money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.0f}"


def _duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if hours else f"{mins}m"


def _when(dt: str) -> str:
    """SerpApi returns "2026-08-10 06:15"; keep both halves, they answer
    different questions ("what day do I fly" / "what time")."""
    return dt


def _named(airport_name: str) -> str:
    return f" ({airport_name})" if airport_name else ""
