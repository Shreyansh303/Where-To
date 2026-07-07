"""FastAPI surface: submit a trip request, stream progress via SSE, fetch
the finished plan."""

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ..config import Settings, get_settings
from ..models import TripRequest
from .jobs import JobStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Where To — AI Travel Agent", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    jobs = JobStore(settings)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "fake_apis": settings.fake_apis}

    @app.post("/api/trips")
    def create_trip(request: TripRequest) -> dict:
        job = jobs.create(request)
        return {"trip_id": job.id}

    @app.get("/api/trips/{trip_id}")
    def get_trip(trip_id: str) -> dict:
        job = jobs.get(trip_id)
        if job is None:
            raise HTTPException(404, "unknown trip id")
        return {
            "trip_id": job.id,
            "status": job.status,
            "error": job.error,
            "plan": job.plan.model_dump(mode="json") if job.plan else None,
        }

    @app.get("/api/trips/{trip_id}/events")
    async def trip_events(trip_id: str) -> StreamingResponse:
        job = jobs.get(trip_id)
        if job is None:
            raise HTTPException(404, "unknown trip id")

        async def stream():
            sent = 0
            while True:
                while sent < len(job.events):
                    yield f"data: {json.dumps(job.events[sent])}\n\n"
                    sent += 1
                if job.status in ("done", "error"):
                    yield f"data: {json.dumps({'stage': 'end', 'status': job.status})}\n\n"
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
