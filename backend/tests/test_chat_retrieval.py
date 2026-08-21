"""Retrieval tests: BM25, the vector half, RRF fusion and the day boost —
all offline (FakeEmbedder), no ONNX model download."""

import os

import pytest

from app.chat import Retriever, build_corpus
from app.chat.corpus import Chunk
from app.chat.embedder import FakeEmbedder
from app.chat.retriever import BM25, tokenize


def labels(retriever: Retriever, question: str) -> list[str]:
    return [r.chunk.label for r in retriever.search(question)]


def test_bm25_finds_an_exact_proper_noun(fake_plan):
    """Keywords are what nail the names travellers actually type."""
    keyword_only = Retriever(build_corpus(fake_plan), embedder=None)
    results = keyword_only.search("Louvre Museum")

    assert "Louvre" in results[0].chunk.text
    assert any(r.chunk.type == "stop" and "Louvre" in r.chunk.label for r in results[:3])


def test_bm25_scores_rise_with_term_frequency_and_rarity():
    bm25 = BM25([tokenize(t) for t in ["louvre louvre museum", "louvre museum", "hotel breakfast"]])
    scores = bm25.scores(tokenize("louvre"))
    assert scores[0] > scores[1] > 0
    assert scores[2] == 0  # a document without the term contributes nothing


def test_vectors_surface_a_paraphrase_keywords_miss(fake_plan):
    """"where I sleep" shares no rare vocabulary with the hotel card; the
    embedding half is what pulls it into the results."""
    chunks = build_corpus(fake_plan)
    question = "is breakfast included where I sleep"

    hybrid = labels(Retriever(chunks, FakeEmbedder()), question)
    keyword_only = labels(Retriever(chunks, embedder=None), question)

    assert any(l.startswith("Your stay") for l in hybrid)
    assert not any(l.startswith("Your stay") for l in keyword_only)


def test_rrf_rewards_agreement_between_the_two_rankings():
    # Keyword ranking: c0 > c1 (c2 scores nothing).
    # Vector ranking:  c1 > c2 (c0 is orthogonal to the query).
    # RRF should put c1 — the only card both halves like — on top.
    chunks = [
        Chunk(id="c0", type="stop", label="c0", text="louvre louvre museum"),
        Chunk(id="c1", type="stop", label="c1", text="louvre museum"),
        Chunk(id="c2", type="stop", label="c2", text="hotel breakfast"),
    ]

    class _Stub:
        def embed_passages(self, texts):
            return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

        def embed_query(self, text):
            return [0.0, 0.9, 0.5]

    ranked = [r.chunk.id for r in Retriever(chunks, _Stub()).search("louvre")]
    assert ranked == ["c1", "c0", "c2"]


def test_day_reference_pulls_that_days_chunks_up(fake_plan):
    retriever = Retriever(build_corpus(fake_plan), FakeEmbedder())
    results = retriever.search("what am I doing on day 3")
    assert results[0].chunk.day == 3
    assert sum(1 for r in results if r.chunk.day == 3) >= 3


def test_weekday_reference_resolves_to_the_right_day(fake_plan):
    retriever = Retriever(build_corpus(fake_plan), FakeEmbedder())
    day_two = next(c for c in build_corpus(fake_plan) if c.id == "day_2")
    weekday = fake_plan.days[1].weekday_name
    assert weekday.lower() in day_two.text.lower()

    results = retriever.search(f"what time do things start on {weekday}")
    assert results[0].chunk.day == 2


def test_day_reference_outside_the_trip_is_ignored(fake_plan):
    retriever = Retriever(build_corpus(fake_plan), FakeEmbedder())
    # Day 99 doesn't exist; the boost must not silently apply to day 9 or 1.
    assert retriever._day_reference("what happens on day 99") is None


def test_bm25_only_mode_still_answers(fake_plan):
    retriever = Retriever(build_corpus(fake_plan), embedder=None)
    assert retriever.degraded_vectors is True
    assert labels(retriever, "which hotel am I staying at")


def test_a_broken_embedder_degrades_instead_of_raising(fake_plan):
    class _Broken:
        def embed_passages(self, texts):
            raise RuntimeError("onnxruntime exploded")

        def embed_query(self, text):
            raise RuntimeError("onnxruntime exploded")

    retriever = Retriever(build_corpus(fake_plan), _Broken())
    assert retriever.degraded_vectors is True
    assert retriever.search("when is my return flight")


def test_empty_corpus_returns_nothing():
    assert Retriever([], FakeEmbedder()).search("anything") == []


@pytest.mark.skipif(
    os.environ.get("WHERE_TO_LIVE_EMBEDDER") != "1",
    reason="downloads the BGE ONNX model; run manually with WHERE_TO_LIVE_EMBEDDER=1",
)
def test_real_embedder_retrieves_a_paraphrase(fake_plan):
    from app.chat.embedder import FastEmbedder

    retriever = Retriever(build_corpus(fake_plan), FastEmbedder())
    assert any("Return flight" in l for l in labels(retriever, "when do I land back home"))
