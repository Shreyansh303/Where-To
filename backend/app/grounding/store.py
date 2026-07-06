"""Grounding store — the structural enforcement of "never invent a fact".

Every entity parsed from an external API response is registered here and
assigned a stable id (flight_out_0, hotel_2, poi_7 …). The LLM only ever
receives summaries containing these ids and can only *select* ids; the final
plan is assembled exclusively by resolving ids back through this store. An
entity that was never returned by an API has no id, so it cannot appear in
the output — there is no code path for LLM-authored facts to enter the plan.
"""

from typing import TypeVar

from pydantic import BaseModel

from ..models import POI, FlightOption, HotelOption

T = TypeVar("T", bound=BaseModel)


class GroundingError(Exception):
    """An id was requested that no API response ever produced."""


class GroundingStore:
    def __init__(self) -> None:
        self._entities: dict[str, BaseModel] = {}
        self._counters: dict[str, int] = {}

    def add(self, prefix: str, entity: T) -> T:
        n = self._counters.get(prefix, 0)
        self._counters[prefix] = n + 1
        gid = f"{prefix}_{n}"
        entity.id = gid  # models carry id="" until registered
        self._entities[gid] = entity
        return entity

    def add_all(self, prefix: str, entities: list[T]) -> list[T]:
        return [self.add(prefix, e) for e in entities]

    def has(self, gid: str) -> bool:
        return gid in self._entities

    def get(self, gid: str) -> BaseModel:
        if gid not in self._entities:
            raise GroundingError(f"unknown id '{gid}' — not returned by any API response")
        return self._entities[gid]

    def _get_typed(self, gid: str, cls: type[T], label: str) -> T:
        entity = self.get(gid)
        if not isinstance(entity, cls):
            raise GroundingError(f"id '{gid}' is not a {label}")
        return entity

    def get_flight(self, gid: str, direction: str | None = None) -> FlightOption:
        flight = self._get_typed(gid, FlightOption, "flight")
        if direction is not None and flight.direction != direction:
            raise GroundingError(f"id '{gid}' is a {flight.direction} flight, expected {direction}")
        return flight

    def get_hotel(self, gid: str) -> HotelOption:
        return self._get_typed(gid, HotelOption, "hotel")

    def get_poi(self, gid: str, kind: str | None = None) -> POI:
        poi = self._get_typed(gid, POI, "place")
        if kind is not None and poi.kind != kind:
            raise GroundingError(f"id '{gid}' is a {poi.kind}, expected {kind}")
        return poi

    def all_of_prefix(self, prefix: str) -> list[BaseModel]:
        return [e for gid, e in self._entities.items() if gid.rsplit("_", 1)[0] == prefix]
