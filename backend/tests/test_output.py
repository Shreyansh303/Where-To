"""Output-assembly unit tests — the 'Getting around' transport advice."""

from app.output.assemble import _CITY_TRANSPORT, _getting_around


def test_getting_around_generic_fallback_makes_no_rail_claim():
    # Phuket isn't in the curated map and has no metro/subway/tram — the generic
    # fallback must not assert infrastructure that may not exist.
    advice = _getting_around("Phuket")
    lowered = advice.lower()
    assert "metro" not in lowered
    assert "subway" not in lowered
    assert "tram" not in lowered
    # still genuinely useful, friendly, and about the city
    assert "Phuket" in advice
    assert len(advice) > 40
    assert "taxi" in lowered or "ride-hailing" in lowered


def test_getting_around_curated_city_unchanged():
    # Curated hits (and their case/whitespace-insensitive lookup) are untouched.
    assert _getting_around("Paris") == _CITY_TRANSPORT["paris"]
    assert _getting_around("  paris ") == _CITY_TRANSPORT["paris"]
    assert "Métro" in _getting_around("Paris")
