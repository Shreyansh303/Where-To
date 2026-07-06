"""In-memory trip-planning jobs.

The pipeline is synchronous (HTTP clients, solver), so each job runs on a
worker thread and appends progress events to a list the SSE endpoint tails.
In-memory storage is a documented MVP choice — one process, no persistence."""

import threading
import time
import uuid
from dataclasses import dataclass, field

from ..config import Settings
from ..models import TripPlan, TripRequest
from ..orchestrator import run_pipeline


@dataclass
class TripJob:
    id: str
    request: TripRequest
    status: str = "running"  # running | done | error
    events: list[dict] = field(default_factory=list)
    plan: TripPlan | None = None
    error: str | None = None

    def emit(self, stage: str, message: str) -> None:
        self.events.append({"stage": stage, "message": message, "ts": time.time()})


class JobStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jobs: dict[str, TripJob] = {}
        self._lock = threading.Lock()

    def create(self, request: TripRequest) -> TripJob:
        job = TripJob(id=uuid.uuid4().hex[:12], request=request)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> TripJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job: TripJob) -> None:
        try:
            job.plan = run_pipeline(job.request, self.settings, emit=job.emit)
            job.status = "done"
        except Exception as exc:
            job.error = str(exc)
            job.status = "error"
            job.emit("error", f"Planning failed: {exc}")
