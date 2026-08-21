"""Corpus tests: the chat sibling of the grounding audit.

Every fact card must be traceable back to the TripPlan it was rendered from —
Miles can only be grounded if the text it retrieves is.
"""

from app.chat import build_corpus


def test_every_flight_hotel_and_stop_becomes_a_chunk(fake_plan):
    chunks = build_corpus(fake_plan)
    by_type: dict[str, list] = {}
    for chunk in chunks:
        by_type.setdefault(chunk.type, []).append(chunk)

    assert len(by_type["flight_out"]) == 1
    assert len(by_type["flight_ret"]) == 1
    assert len(by_type["hotel"]) == 1
    assert len(by_type["day_summary"]) == len(fake_plan.days)
    assert len(by_type["stop"]) == sum(len(d.stops) for d in fake_plan.days)
    assert len(by_type["budget"]) == 1
    assert len(by_type["data_quality"]) == len(fake_plan.data_quality)
    assert len(by_type["getting_around"]) == 1


def test_dropped_pois_and_extras_become_chunks(short_plan):
    assert short_plan.dropped_pois, "fixture precondition: the short trip drops a POI"
    extras = [p for d in short_plan.days for p in d.extras]
    assert extras, "fixture precondition: the short trip surfaces extras"

    chunks = build_corpus(short_plan)
    dropped = [c for c in chunks if c.type == "dropped"]
    assert len(dropped) == len(short_plan.dropped_pois)
    # The reason is what powers "why isn't X in my plan?" — it must survive.
    for chunk, source in zip(dropped, short_plan.dropped_pois):
        name, _, reason = source.partition(": ")
        assert name in chunk.text and reason in chunk.text
        assert "NOT included" in chunk.text

    extra_chunks = [c for c in chunks if c.type == "extra"]
    assert {c.poi_id for c in extra_chunks} == {p.id for p in extras}


def test_every_stop_fact_traces_to_the_plan(fake_plan):
    """Provenance: names, times and travel minutes appear verbatim."""
    stops = {
        f"stop_{i}_{j}": (i, stop)
        for i, day in enumerate(fake_plan.days, start=1)
        for j, stop in enumerate(day.stops)
    }
    for chunk in build_corpus(fake_plan):
        if chunk.type != "stop":
            continue
        index, stop = stops[chunk.id]
        assert stop.poi.name in chunk.text
        assert stop.arrive in chunk.text and stop.depart in chunk.text
        assert str(stop.poi.est_visit_minutes) in chunk.text
        if stop.travel_from_prev_minutes > 0:
            assert str(stop.travel_from_prev_minutes) in chunk.text
        if stop.note:
            assert stop.note in chunk.text
        assert chunk.poi_id == stop.poi.id
        assert chunk.day == index


def test_flight_hotel_and_budget_facts_trace_to_the_plan(fake_plan):
    by_id = {c.id: c for c in build_corpus(fake_plan)}

    outbound, inbound = fake_plan.outbound_flight, fake_plan.return_flight
    assert outbound.segments[0].departure_time in by_id["flight_out"].text
    assert outbound.segments[0].airline in by_id["flight_out"].text
    assert inbound.segments[-1].arrival_time in by_id["flight_ret"].text
    # Only the return leg may state a total — it carries the round-trip fare.
    assert f"{inbound.price:,.0f}" in by_id["flight_ret"].text
    assert f"{inbound.price:,.0f}" not in by_id["flight_out"].text

    hotel = fake_plan.hotel
    assert hotel.name in by_id["hotel"].text
    assert f"{hotel.total_rate:,.0f}" in by_id["hotel"].text

    budget = by_id["budget"].text
    assert f"{fake_plan.budget.total:,.0f}" in budget
    assert f"{fake_plan.budget.flights_total:,.0f}" in budget
    assert str(fake_plan.request.travelers) in budget


def test_day_metadata_matches_the_itinerary(fake_plan):
    chunks = build_corpus(fake_plan)
    for index, day in enumerate(fake_plan.days, start=1):
        summary = next(c for c in chunks if c.id == f"day_{index}")
        assert summary.day == index
        assert day.weekday_name in summary.text
        assert str(day.date) in summary.text
        for stop in day.stops:
            assert stop.poi.name in summary.text
    # Chunks with no day of their own must say so, not default to day 1.
    assert all(c.day is None for c in chunks if c.type in ("hotel", "budget", "flight_out"))


def test_researched_price_carries_its_source_url(fake_plan):
    # FAKE_APIS runs without web research, so graft a researched price onto a
    # stop to prove the renderer carries the estimate *and* its provenance.
    plan = fake_plan.model_copy(deep=True)
    stop = next(s for d in plan.days for s in d.stops if s.meal is None)
    stop.est_entry_cost = "INR 2,000"
    stop.est_entry_cost_source = "https://example.com/tickets"

    chunk = next(c for c in build_corpus(plan) if c.poi_id == stop.poi.id and c.type == "stop")
    assert "INR 2,000" in chunk.text
    assert "researched estimate" in chunk.text  # never presented as a booked price
    assert chunk.source_url == "https://example.com/tickets"


def test_corpus_is_facts_only_with_unique_ids(fake_plan):
    chunks = build_corpus(fake_plan)
    assert len({c.id for c in chunks}) == len(chunks)
    assert all(c.label and c.text for c in chunks)
    # LLM commentary is prose, not a fact — it must never enter the corpus.
    assert fake_plan.commentary
    assert not any(fake_plan.commentary in c.text for c in chunks)
