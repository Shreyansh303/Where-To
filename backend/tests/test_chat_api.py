"""Chat endpoint tests over the FAKE_APIS pipeline + the scripted chat model —
no keys, no network, no ONNX download."""

import time

import pytest
from fastapi.testclient import TestClient

from app.api import jobs as jobs_module
from app.api.jobs import CHAT_RATE_LIMIT
from app.api.main import create_app
from app.chat import build_corpus
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


@pytest.fixture
def planned(tmp_path):
    """A TestClient with one finished trip, ready to be asked about."""
    app = create_app(Settings(fake_apis=True, cache_path=str(tmp_path / "cache.sqlite3")))
    client = TestClient(app)
    trip_id = client.post("/api/trips", json=TRIP_BODY).json()["trip_id"]
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if client.get(f"/api/trips/{trip_id}").json()["status"] != "running":
            break
        time.sleep(0.1)
    else:
        raise AssertionError("job did not finish in time")
    return client, trip_id


def ask(client: TestClient, trip_id: str, message: str, history=None):
    return client.post(
        f"/api/trips/{trip_id}/chat",
        json={"message": message, "history": history or []},
    )


def test_chat_answers_with_citations_that_exist(planned):
    client, trip_id = planned
    resp = ask(client, trip_id, "Which hotel am I staying at?")
    assert resp.status_code == 200
    body = resp.json()

    assert body["answer"]
    assert body["degraded"] is False
    plan = client.app.state.jobs.get(trip_id).plan
    known = {c.id: c for c in build_corpus(plan)}
    assert body["citations"], "a grounded answer must cite its cards"
    for citation in body["citations"]:
        chunk = known[citation["chunk_id"]]  # KeyError = invented citation
        assert citation["label"] == chunk.label
        assert citation["type"] == chunk.type
        assert citation["day"] == chunk.day


def test_citation_markers_line_up_with_the_citation_list(planned):
    client, trip_id = planned
    body = ask(client, trip_id, "Which hotel am I staying at?").json()
    assert "[1]" in body["answer"]
    assert len(body["citations"]) >= 1


def test_full_width_citation_brackets_resolve():
    # gpt-oss sometimes emits 【n】 instead of [n]; those must still resolve to a
    # citation and be normalized to ASCII in the answer text.
    from app.chat import Chunk, Retrieved
    from app.chat.answer import _resolve_citations

    retrieved = [
        Retrieved(chunk=Chunk(id="a", type="hotel", label="Your stay", text="Hotel X"), score=1.0),
        Retrieved(chunk=Chunk(id="b", type="budget", label="Budget", text="Budget Y"), score=0.9),
    ]
    answer, cites = _resolve_citations("The round-trip fare is INR 43,168【2】.", retrieved)
    assert "[1]" in answer and "【2】" not in answer  # renumbered + normalized to ASCII
    assert [c.chunk_id for c in cites] == ["b"]


def test_keyword_only_mode_is_not_flagged_as_reduced():
    # Vectors off (BM25-only, e.g. CHAT_VECTORS=0 on a small host) still feeds a
    # real model-written answer — it must NOT trip the "reduced mode" banner,
    # which is only for the LLM-down extractive fallback.
    from app.chat import Chunk, Retriever
    from app.chat.answer import ScriptedChatLLM, answer_question

    chunks = [
        Chunk(id="hotel", type="hotel", label="Your stay",
              text="Your stay is the Palais Royal Grand, a 5-star hotel."),
    ]
    retriever = Retriever(chunks, embedder=None)  # keyword-only
    assert retriever.degraded_vectors is True
    reply = answer_question("Which hotel am I staying at?", [], retriever, ScriptedChatLLM())
    assert reply.answer
    assert reply.degraded is False


def test_index_is_built_once_and_reused(planned):
    client, trip_id = planned
    job = client.app.state.jobs.get(trip_id)
    assert job.retriever is None  # planning never pays for the chat index

    ask(client, trip_id, "Which hotel am I staying at?")
    first = job.retriever
    assert first is not None
    ask(client, trip_id, "What time is my return flight?")
    assert job.retriever is first


def test_out_of_corpus_question_gets_an_honest_answer(planned):
    client, trip_id = planned
    body = ask(client, trip_id, "Are vaccinations mandatory?").json()
    assert "isn't in your plan" in body["answer"]
    assert body["citations"] == []


def test_plan_edit_request_gets_a_scope_explanation(planned):
    client, trip_id = planned
    body = ask(client, trip_id, "Can you move the Louvre to Thursday?").json()
    assert "only answer questions" in body["answer"]
    assert body["citations"] == []


def test_history_is_capped_server_side(planned):
    client, trip_id = planned
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(40)
    ]
    resp = ask(client, trip_id, "Which hotel am I staying at?", history=history)
    assert resp.status_code == 200
    assert resp.json()["answer"]


def test_unknown_trip_404(planned):
    client, _ = planned
    assert ask(client, "nope", "Which hotel?").status_code == 404


def test_unfinished_plan_409(planned):
    client, trip_id = planned
    job = client.app.state.jobs.get(trip_id)
    job.status, job.plan = "running", None
    assert ask(client, trip_id, "Which hotel?").status_code == 409


def test_empty_message_rejected(planned):
    client, trip_id = planned
    assert ask(client, trip_id, "").status_code == 422


def test_llm_failure_falls_back_to_the_retrieved_cards(planned, monkeypatch):
    class _Down:
        def converse(self, messages, *, max_tokens, temperature):
            raise RuntimeError("groq is having a day")

    monkeypatch.setattr(jobs_module, "build_chat_llm", lambda settings: _Down())
    client, trip_id = planned

    body = ask(client, trip_id, "Which hotel am I staying at?").json()
    assert body["degraded"] is True
    assert body["citations"], "the extractive fallback still cites what it quoted"
    plan = client.app.state.jobs.get(trip_id).plan
    quoted = {c.id: c.text for c in build_corpus(plan)}
    # Verbatim, not paraphrased — there is no model left to paraphrase with.
    assert all(quoted[c["chunk_id"]] in body["answer"] for c in body["citations"])


def test_rate_cap_returns_429(planned):
    client, trip_id = planned
    for _ in range(CHAT_RATE_LIMIT):
        assert ask(client, trip_id, "Which hotel am I staying at?").status_code == 200
    assert ask(client, trip_id, "And the flight?").status_code == 429


def test_chat_can_be_switched_off(tmp_path):
    settings = Settings(
        fake_apis=True, chat_enabled=False, cache_path=str(tmp_path / "cache.sqlite3")
    )
    client = TestClient(create_app(settings))
    assert ask(client, "any", "hello?").status_code == 503
