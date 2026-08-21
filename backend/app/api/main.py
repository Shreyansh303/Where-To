"""FastAPI surface: submit a trip request, stream progress via SSE, fetch
the finished plan, and ask Miles about it."""

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..chat import ChatMessage, ChatReply, answer_question
from ..config import Settings, get_settings
from ..models import TripRequest
from .jobs import JobStore


class ChatRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list)


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
    app.state.jobs = jobs  # handle for tests and future admin surfaces

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

    @app.post("/api/trips/{trip_id}/chat")
    async def chat(trip_id: str, body: ChatRequestBody) -> ChatReply:
        if not settings.chat_enabled:
            raise HTTPException(503, "chat is disabled on this deployment")
        job = jobs.get(trip_id)
        if job is None:
            raise HTTPException(404, "unknown trip id")
        if job.status != "done" or job.plan is None:
            raise HTTPException(409, "this trip's plan isn't ready yet")
        if not jobs.allow_chat(job):
            raise HTTPException(429, "too many questions for this trip — give it a minute")

        # Retrieval and the Groq call are both blocking; keep the event loop
        # free so SSE streams for other trips don't stall behind a question.
        retriever = await run_in_threadpool(jobs.chat_retriever, job)
        return await run_in_threadpool(
            answer_question, body.message, body.history, retriever, jobs.chat_llm()
        )

    return app


app = create_app()
