"""The web-researched city planning brief.

Everything here is an LLM extraction of public travel-guide text — clearly a
*researched estimate*, not API-grounded fact. Durations refine the solver's
type heuristics; prices carry a `source_url` so the UI can attribute them.
Consumed in `app/orchestrator/pipeline.py`; produced in `app/research/brief.py`.
"""

from pydantic import BaseModel


class AttractionFacts(BaseModel):
    duration_minutes: int | None = None
    is_full_day: bool = False
    ticket_price: str | None = None  # formatted in the trip currency, e.g. "₹1,200"
    source_url: str | None = None


class CityBrief(BaseModel):
    city: str
    must_see: list[str] = []  # canonical iconic attraction names, best first
    attractions: dict[str, AttractionFacts] = {}  # keyed by attraction name
    meal_cost: str | None = None
