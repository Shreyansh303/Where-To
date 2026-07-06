"""Grounding store + selection validation tests — the "can't invent facts" layer."""

import pytest

from app.grounding import (
    GroundingError,
    GroundingStore,
    SelectionError,
    validate_selections,
)
from app.models import POI, FlightOption, FlightSegment, HotelOption, LatLng


def make_flight(direction="outbound", price=42350.0) -> FlightOption:
    return FlightOption(
        id="",
        direction=direction,
        segments=[
            FlightSegment(
                departure_airport="DEL",
                departure_time="2026-08-10 03:05",
                arrival_airport="CDG",
                arrival_time="2026-08-10 08:25",
                airline="Air France",
                flight_number="AF 225",
                duration_minutes=530,
            )
        ],
        total_duration_minutes=530,
        price=price,
        currency="INR",
    )


def make_hotel() -> HotelOption:
    return HotelOption(id="", name="Hôtel du Louvre", currency="INR", total_rate=92500)


def make_poi(kind="attraction") -> POI:
    return POI(
        id="",
        place_id="gplace",
        name="Louvre Museum",
        kind=kind,
        location=LatLng(lat=48.86, lng=2.33),
    )


def populated_store() -> GroundingStore:
    store = GroundingStore()
    store.add_all("flight_out", [make_flight(), make_flight()])
    store.add("flight_ret", make_flight("return"))
    store.add("hotel", make_hotel())
    store.add_all("poi", [make_poi(), make_poi(), make_poi()])
    store.add("rest", make_poi("restaurant"))
    return store


def test_ids_are_sequential_and_written_back():
    store = GroundingStore()
    a = store.add("poi", make_poi())
    b = store.add("poi", make_poi())
    assert a.id == "poi_0" and b.id == "poi_1"
    assert store.get("poi_1") is b


def test_unknown_id_raises():
    with pytest.raises(GroundingError, match="unknown id 'poi_99'"):
        populated_store().get("poi_99")


def test_typed_getters_reject_wrong_type_and_direction():
    store = populated_store()
    with pytest.raises(GroundingError, match="not a hotel"):
        store.get_hotel("poi_0")
    with pytest.raises(GroundingError, match="expected outbound"):
        store.get_flight("flight_ret_0", "outbound")
    with pytest.raises(GroundingError, match="expected attraction"):
        store.get_poi("rest_0", "attraction")


def test_valid_selection_passes():
    store = populated_store()
    sel = validate_selections(
        store,
        {
            "outbound_flight_id": "flight_out_1",
            "return_flight_id": "flight_ret_0",
            "hotel_id": "hotel_0",
            "poi_ids": ["poi_0", "poi_2"],
            "commentary": "Museums first, tower at night.",
        },
    )
    assert sel.outbound_flight_id == "flight_out_1"


def test_invalid_selection_reports_all_problems_for_retry():
    store = populated_store()
    with pytest.raises(SelectionError) as exc:
        validate_selections(
            store,
            {
                "outbound_flight_id": "flight_ret_0",  # wrong direction
                "return_flight_id": "flight_ret_0",
                "hotel_id": "hotel_9",  # unknown
                "poi_ids": ["poi_0", "poi_0", "rest_0"],  # dup + wrong kind
            },
        )
    msg = str(exc.value)
    assert "expected outbound" in msg
    assert "hotel_9" in msg
    assert "duplicate poi id 'poi_0'" in msg
    assert "expected attraction" in msg


def test_malformed_json_selection_raises():
    with pytest.raises(SelectionError, match="malformed"):
        validate_selections(populated_store(), {"poi_ids": []})


def test_hotel_optional_when_source_failed():
    store = populated_store()
    sel = validate_selections(
        store,
        {
            "outbound_flight_id": "flight_out_0",
            "return_flight_id": "flight_ret_0",
            "hotel_id": None,
            "poi_ids": ["poi_1"],
        },
    )
    assert sel.hotel_id is None
