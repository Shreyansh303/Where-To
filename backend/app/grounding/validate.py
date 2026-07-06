"""Validation of LLM selections against the grounding store.

The orchestrator parses the model's final decision into `TripSelections`,
then `validate_selections` checks every id against the store. Failures raise
`SelectionError` whose message lists *all* problems — it is fed back to the
LLM verbatim so the retry can fix everything in one shot.
"""

from pydantic import BaseModel, Field, ValidationError

from .store import GroundingError, GroundingStore


class TripSelections(BaseModel):
    outbound_flight_id: str
    return_flight_id: str
    hotel_id: str | None = None  # None allowed when the hotels source failed
    # Emptiness is policed by the toolbox (allowed only when the places
    # source failed), so degradation can still produce a flights+hotel plan.
    poi_ids: list[str] = Field(default_factory=list, description="Attraction ids, ranked by priority")
    commentary: str = ""


class SelectionError(Exception):
    """Invalid LLM selection; message is designed to be sent back to the LLM."""


def validate_selections(store: GroundingStore, raw: dict) -> TripSelections:
    try:
        selections = TripSelections.model_validate(raw)
    except ValidationError as exc:
        raise SelectionError(f"selection JSON is malformed: {exc}") from exc

    problems: list[str] = []

    def check(fn, *args) -> None:
        try:
            fn(*args)
        except GroundingError as exc:
            problems.append(str(exc))

    check(store.get_flight, selections.outbound_flight_id, "outbound")
    check(store.get_flight, selections.return_flight_id, "return")
    if selections.hotel_id is not None:
        check(store.get_hotel, selections.hotel_id)

    seen: set[str] = set()
    for pid in selections.poi_ids:
        if pid in seen:
            problems.append(f"duplicate poi id '{pid}'")
        seen.add(pid)
        check(store.get_poi, pid, "attraction")

    if problems:
        raise SelectionError(
            "invalid selection — fix ALL of the following and answer again: " + "; ".join(problems)
        )
    return selections
