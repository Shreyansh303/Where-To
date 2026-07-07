"""API surface tests over the FAKE_APIS pipeline."""

import time

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings

TRIP_BODY = {
    "origin": "DEL",
    "destination": "CDG",
    "destination_city": "Paris",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-15",
    "budget": 400000,
    "travelers": 2,
}


def make_client(tmp_path) -> TestClient:
    settings = Settings(fake_apis=True, cache_path=str(tmp_path / "cache.sqlite3"))
    return TestClient(create_app(settings))


def wait_done(client: TestClient, trip_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/trips/{trip_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def test_health(tmp_path):
    resp = make_client(tmp_path).get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["fake_apis"] is True


def test_trip_lifecycle(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/api/trips", json=TRIP_BODY)
    assert resp.status_code == 200
    trip_id = resp.json()["trip_id"]

    body = wait_done(client, trip_id)
    assert body["status"] == "done"
    plan = body["plan"]
    assert plan["outbound_flight"]["price"] > 0
    assert plan["hotel"]["name"]
    assert plan["days"] and plan["days"][0]["stops"]
    assert plan["budget"]["currency"] == "INR"


def test_invalid_request_rejected(tmp_path):
    bad = dict(TRIP_BODY, return_date="2026-08-09")  # before departure
    resp = make_client(tmp_path).post("/api/trips", json=bad)
    assert resp.status_code == 422


def test_unknown_trip_id_404(tmp_path):
    assert make_client(tmp_path).get("/api/trips/nope").status_code == 404


def test_event_stream_replays_and_ends(tmp_path):
    client = make_client(tmp_path)
    trip_id = client.post("/api/trips", json=TRIP_BODY).json()["trip_id"]
    wait_done(client, trip_id)

    lines = []
    with client.stream("GET", f"/api/trips/{trip_id}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                lines.append(line)
            if '"stage": "end"' in line:
                break
    assert any('"stage": "solving"' in l for l in lines)
    assert '"status": "done"' in lines[-1]
