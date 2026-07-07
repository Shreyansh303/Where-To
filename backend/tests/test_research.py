"""Research client + city-brief extraction — no live API, no live LLM."""

import json

import respx

from app.clients.serpapi_search import SERPAPI_URL, SearchClient, _snippets
from app.research import build_city_brief

NO_BACKOFF = {"backoff_base": 0.0}

_EXTRACTION = {
    "must_see": ["Victoria Peak", "Tian Tan Buddha", "Hong Kong Disneyland"],
    "meal_cost": "INR 900",
    "attractions": {
        "Hong Kong Disneyland": {
            "duration_minutes": 480,
            "is_full_day": True,
            "ticket_price": "INR 6,800",
            "source_url": "https://example.com/hk-disneyland",
        },
        "Victoria Peak": {
            "duration_minutes": 120,
            "is_full_day": False,
            "ticket_price": "INR 1,600",
            "source_url": "https://example.com/victoria-peak",
        },
    },
}


def test_snippets_flatten_answer_kg_and_organic(fixture_json):
    raw = fixture_json("serpapi_search.json")
    lines = _snippets(raw)
    joined = " ".join(lines)
    assert "4 to 5 days" in joined  # answer box
    assert "Lantau Island" in joined  # knowledge graph / organic
    assert "Disneyland" in joined
    assert "source: https://example.com/hk-disneyland" in joined  # link retained


@respx.mock
def test_search_client_returns_text_snippets(fixture_json):
    respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_search.json"))
    client = SearchClient(api_key="k", **NO_BACKOFF)
    snippets = client.search_text("things to do in Hong Kong")
    assert any("Disneyland" in s for s in snippets)


@respx.mock
def test_build_city_brief_extracts_structured_facts(fixture_json):
    respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_search.json"))
    client = SearchClient(api_key="k", **NO_BACKOFF)

    captured = {}

    def stub_complete(system: str, user: str) -> str:
        captured["user"] = user
        return json.dumps(_EXTRACTION)

    brief = build_city_brief("Hong Kong", "INR", ["Hong Kong Disneyland"], client, stub_complete)
    assert brief is not None
    # The gathered research text is fed to the LLM prompt.
    assert "Lantau Island" in captured["user"]
    # Structured facts round-trip into the model.
    disney = brief.attractions["Hong Kong Disneyland"]
    assert disney.is_full_day is True
    assert disney.duration_minutes == 480
    assert disney.ticket_price == "INR 6,800"
    assert disney.source_url.endswith("hk-disneyland")
    assert brief.meal_cost == "INR 900"
    assert "Victoria Peak" in brief.must_see


@respx.mock
def test_build_city_brief_returns_none_on_unparseable_llm(fixture_json):
    respx.get(SERPAPI_URL).respond(json=fixture_json("serpapi_search.json"))
    client = SearchClient(api_key="k", **NO_BACKOFF)
    brief = build_city_brief("Hong Kong", "INR", [], client, lambda s, u: "sorry, no JSON here")
    assert brief is None


def test_build_city_brief_returns_none_when_no_research(monkeypatch):
    client = SearchClient(api_key="k", **NO_BACKOFF)
    monkeypatch.setattr(client, "search_text", lambda *a, **k: [])
    called = False

    def stub(system, user):
        nonlocal called
        called = True
        return "{}"

    brief = build_city_brief("Nowhere", "INR", [], client, stub)
    assert brief is None
    assert not called  # never bothers the LLM without research text
