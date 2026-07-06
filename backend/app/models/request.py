from datetime import date

from pydantic import BaseModel, Field, model_validator


class TripRequest(BaseModel):
    origin: str = Field(description="Origin airport IATA code, e.g. DEL")
    destination: str = Field(description="Destination airport IATA code, e.g. CDG")
    destination_city: str = Field(description="Destination city name, e.g. Paris")
    departure_date: date
    return_date: date
    budget: float = Field(gt=0, description="Total trip budget in the configured currency")
    travelers: int = Field(default=1, ge=1, le=9)
    interests: list[str] = Field(default_factory=list, description="e.g. ['art', 'history', 'food']")

    @model_validator(mode="after")
    def _dates_ordered(self) -> "TripRequest":
        if self.return_date <= self.departure_date:
            raise ValueError("return_date must be after departure_date")
        return self

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days

    @property
    def full_days(self) -> int:
        """Itinerary days: the days between arrival and departure day.
        MVP keeps travel days free of scheduled activities."""
        return max(self.nights - 1, 1)
