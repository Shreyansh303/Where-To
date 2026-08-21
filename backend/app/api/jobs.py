"""In-memory trip-planning jobs.

The pipeline is synchronous (HTTP clients, solver), so each job runs on a
worker thread and appends progress events to a list the SSE endpoint tails.
In-memory storage is a documented MVP choice — one process, no persistence.

Each job also carries the chat state for its trip: the retrieval index (built
on the first question, never during planning, so trips nobody chats with cost
nothing) and a sliding window of recent questions for the rate cap.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field

from ..chat import Retriever, build_corpus
from ..chat.answer import ChatLLM, build_chat_llm
from ..chat.embedder import build_embedder
from ..config import Settings
from ..models import TripPlan, TripRequest
from ..orchestrator import run_pipeline

CHAT_RATE_LIMIT = 10  # questions...
CHAT_RATE_WINDOW = 60.0  # ...per this many seconds, per trip


@dataclass
class TripJob:
    id: str
    request: TripRequest
    status: str = "running"  # running | done | error
    events: list[dict] = field(default_factory=list)
    plan: TripPlan | None = None
    error: str | None = None
    retriever: Retriever | None = None  # memoized chat index
    chat_lock: threading.Lock = field(default_factory=threading.Lock)
    chat_times: list[float] = field(default_factory=list)

    def emit(self, stage: str, message: str) -> None:
        self.events.append({"stage": stage, "message": message, "ts": time.time()})


class JobStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jobs: dict[str, TripJob] = {}
        self._lock = threading.Lock()
        self._chat_llm: ChatLLM | None = None

    def create(self, request: TripRequest) -> TripJob:
        job = TripJob(id=uuid.uuid4().hex[:12], request=request)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> TripJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def chat_retriever(self, job: TripJob) -> Retriever:
        """Build (once) the hybrid index over this trip's fact cards. Loading
        the embedder can take seconds on a cold process, so it happens behind
        the job's own lock — concurrent first questions wait, not duplicate."""
        with job.chat_lock:
            if job.retriever is None:
                assert job.plan is not None  # callers check status first
                embedder, _ = build_embedder(self.settings)
                job.retriever = Retriever(build_corpus(job.plan), embedder)
            return job.retriever

    def chat_llm(self) -> ChatLLM:
        if self._chat_llm is None:
            self._chat_llm = build_chat_llm(self.settings)
        return self._chat_llm

    def allow_chat(self, job: TripJob) -> bool:
        """Sliding-window rate cap, per trip — cheap insurance for the free
        tier against a stuck client or an over-eager tab."""
        now = time.time()
        with job.chat_lock:
            job.chat_times = [t for t in job.chat_times if now - t < CHAT_RATE_WINDOW]
            if len(job.chat_times) >= CHAT_RATE_LIMIT:
                return False
            job.chat_times.append(now)
            return True

    def _run(self, job: TripJob) -> None:
        try:
            job.plan = run_pipeline(job.request, self.settings, emit=job.emit)
            job.status = "done"
        except Exception as exc:
            job.error = str(exc)
            job.status = "error"
            job.emit("error", f"Planning failed: {exc}")
