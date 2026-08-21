import json
from datetime import date
from pathlib import Path

import pytest

from app.config import Settings
from app.models import TripRequest
from app.orchestrator import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json():
    def load(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return load


def _plan(tmp_dir: Path, return_date: date):
    request = TripRequest(
        origin="DEL",
        destination="CDG",
        destination_city="Paris",
        departure_date=date(2026, 8, 10),
        return_date=return_date,
        budget=400000,
        travelers=2,
    )
    settings = Settings(fake_apis=True, cache_path=str(tmp_dir / "cache.sqlite3"))
    return run_pipeline(request, settings)


# Chat tests all read from a real pipeline plan rather than a hand-written one,
# so the corpus is exercised against the same shapes production produces.
# Session-scoped: building it is deterministic and costs a second.
@pytest.fixture(scope="session")
def fake_plan(tmp_path_factory):
    return _plan(tmp_path_factory.mktemp("plan"), date(2026, 8, 15))


@pytest.fixture(scope="session")
def short_plan(tmp_path_factory):
    """A two-night trip — too short for every attraction, so the solver drops
    one and surfaces extras. Covers the chunk types the long plan can't."""
    return _plan(tmp_path_factory.mktemp("short_plan"), date(2026, 8, 12))
