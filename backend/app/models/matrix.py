"""Travel-time matrix passed from the routes client to the solver.

Lives in models (not clients) so the solver layer never depends on API code.
"""


class TravelMatrix:
    """Minutes matrix over N points. `estimated[i][j]` is True where the
    value is a haversine fallback rather than real routing data."""

    def __init__(self, minutes: list[list[int]], estimated: list[list[bool]]):
        self.minutes = minutes
        self.estimated = estimated

    @property
    def any_estimated(self) -> bool:
        return any(any(row) for row in self.estimated)
