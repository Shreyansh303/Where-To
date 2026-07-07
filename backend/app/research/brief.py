"""Build a web-grounded city planning brief.

Runs a few Google web searches (via SerpApi) for a city, then a single LLM
pass distills the travel-guide text into structured, per-attraction facts:
typical visit duration, whether it's a whole-day outing, ticket price (in the
trip currency, with a source link), plus the city's canonical must-see list.

Everything here is best-effort: any failure returns `None` and the pipeline
falls back to its type-based duration heuristics and LLM price estimate. These
are *researched estimates*, clearly labelled — not API-grounded facts.
"""

import json
from typing import Callable

from ..clients import SearchClient
from ..models import AttractionFacts, CityBrief

_SYSTEM = (
    "You extract structured travel-planning facts from web research text. "
    "Return ONLY valid JSON, no markdown, no commentary."
)

MAX_SNIPPETS = 40


def _queries(city: str) -> list[str]:
    return [
        f"{city} top must-see attractions worth visiting",
        f"how many days to spend in {city} itinerary must-see landmarks",
        f"{city} attractions ticket prices and how long to visit",
    ]


def _gather(city: str, search: SearchClient) -> list[str]:
    seen: set[str] = set()
    snippets: list[str] = []
    for q in _queries(city):
        try:
            for s in search.search_text(q):
                if s not in seen:
                    seen.add(s)
                    snippets.append(s)
        except Exception:
            continue  # one bad query shouldn't sink the brief
    return snippets[:MAX_SNIPPETS]


def _prompt(city: str, currency: str, attraction_names: list[str], research: str) -> str:
    names = "\n".join(f"- {n}" for n in attraction_names) or "- (none provided)"
    return (
        f"Using the web research below about {city}, produce trip-planning facts.\n\n"
        f"Return a JSON object with these keys:\n"
        f"- \"must_see\": ordered list of the city's most iconic must-see attraction "
        f"names for a first-time visitor (best first; you may include famous places "
        f"beyond the provided list).\n"
        f"- \"meal_cost\": typical cost of one adult meal at a mid-range restaurant, "
        f"in {currency} (with symbol/code).\n"
        f"- \"attractions\": an object mapping attraction name -> {{ "
        f"\"duration_minutes\": typical visit length in minutes (integer), "
        f"\"is_full_day\": true if it realistically fills a whole day (theme parks, "
        f"large island/day excursions), "
        f"\"ticket_price\": standard adult entry price in {currency} with symbol "
        f"(or \"Free\"), "
        f"\"source_url\": a URL from the research supporting the price, or null }}.\n\n"
        f"Cover at least the attractions provided below (match their exact names), "
        f"plus any must-see you add. Convert every price to {currency} accurately. "
        f"Never mark a paid attraction as Free.\n\n"
        f"Attractions to cover:\n{names}\n\n"
        f"Web research:\n{research}"
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _coerce_facts(raw: object) -> AttractionFacts:
    if isinstance(raw, str):  # model returned just a price string
        return AttractionFacts(ticket_price=raw or None)
    if not isinstance(raw, dict):
        return AttractionFacts()
    dur = raw.get("duration_minutes")
    try:
        dur = int(dur) if dur is not None else None
    except (TypeError, ValueError):
        dur = None
    return AttractionFacts(
        duration_minutes=dur,
        is_full_day=bool(raw.get("is_full_day")),
        ticket_price=(raw.get("ticket_price") or None),
        source_url=(raw.get("source_url") or None),
    )


def build_city_brief(
    city: str,
    currency: str,
    attraction_names: list[str],
    search: SearchClient,
    chat_complete: Callable[[str, str], str],
) -> CityBrief | None:
    """Return a `CityBrief` for the city, or `None` if research/extraction fails.
    `chat_complete(system, user)` performs the LLM call (injected for testing)."""
    try:
        research = "\n".join(_gather(city, search))
        if not research:
            return None
        text = chat_complete(_SYSTEM, _prompt(city, currency, attraction_names, research))
        data = json.loads(_strip_fences(text))
        attractions = {
            name: _coerce_facts(facts)
            for name, facts in (data.get("attractions") or {}).items()
            if isinstance(name, str)
        }
        return CityBrief(
            city=city,
            must_see=[m for m in (data.get("must_see") or []) if isinstance(m, str)],
            attractions=attractions,
            meal_cost=(data.get("meal_cost") or None),
        )
    except Exception:
        return None
