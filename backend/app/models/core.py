"""Shared primitives used across layers."""

from pydantic import BaseModel


class LatLng(BaseModel):
    lat: float
    lng: float


class OpeningHours(BaseModel):
    """Opening windows per weekday (0=Monday … 6=Sunday), as minutes from
    midnight. An entirely absent OpeningHours (None on the POI) means hours
    are unknown — the solver assumes open but flags the stop. If windows are
    known and a weekday has no entry, the place is closed that day."""

    windows: dict[int, list[tuple[int, int]]] = {}

    def is_open_during(self, weekday: int, start_min: int, end_min: int) -> bool:
        for open_min, close_min in self.windows.get(weekday, []):
            if open_min <= start_min and end_min <= close_min:
                return True
        return False

    def opens_at(self, weekday: int) -> int | None:
        day = self.windows.get(weekday)
        return min(w[0] for w in day) if day else None
