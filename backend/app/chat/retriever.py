"""Hybrid retrieval over a trip's fact cards: BM25 + vectors, fused with RRF.

Hand-rolled on purpose. The corpus is ~60-200 short chunks, so an index
library (FAISS, a vector DB) would add hundreds of megabytes and a service
dependency to answer a question that brute force answers in microseconds —
the same trade the solver makes with pure-Python k-means and the cache makes
with SQLite.

Why hybrid: BM25 nails the exact proper nouns travellers type ("Louvre",
"AF225") but misses paraphrase; embeddings catch "when do I get home" ->
return flight but drift on rare names. Reciprocal Rank Fusion combines the
two rankings without having to normalize a keyword score against a cosine.
"""

import math
import re
from dataclasses import dataclass

from .corpus import Chunk
from .embedder import Embedder

K1 = 1.5  # BM25 term-frequency saturation
B = 0.75  # BM25 length normalization
RRF_K = 60  # standard RRF damping constant
DAY_BOOST = 0.05  # ~3x one RRF list's best contribution: decisive, not absolute
TOP_K = 6

_TOKEN = re.compile(r"[a-z0-9]+")
_DAY_REF = re.compile(r"\bday\s*(\d+)\b")
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Retrieved:
    chunk: Chunk
    score: float


class BM25:
    """Okapi BM25 over pre-tokenized documents."""

    def __init__(self, documents: list[list[str]]):
        self.docs = documents
        self.lengths = [len(d) for d in documents]
        self.avg_length = (sum(self.lengths) / len(documents)) if documents else 0.0
        self.frequencies: list[dict[str, int]] = []
        document_frequency: dict[str, int] = {}
        for doc in documents:
            counts: dict[str, int] = {}
            for token in doc:
                counts[token] = counts.get(token, 0) + 1
            self.frequencies.append(counts)
            for token in counts:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        total = len(documents)
        self.idf = {
            token: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for token, df in document_frequency.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * len(self.docs)
        for token in query_tokens:
            idf = self.idf.get(token)
            if idf is None:
                continue
            for i, counts in enumerate(self.frequencies):
                freq = counts.get(token, 0)
                if not freq:
                    continue
                norm = 1 - B + B * (self.lengths[i] / (self.avg_length or 1))
                out[i] += idf * (freq * (K1 + 1)) / (freq + K1 * norm)
        return out


class Retriever:
    """Builds both indexes once per trip and answers questions against them."""

    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None):
        self.chunks = chunks
        self._bm25 = BM25([tokenize(c.text) for c in chunks])
        self._vectors: list[list[float]] | None = None
        self._embedder: Embedder | None = None
        if embedder is not None and chunks:
            try:
                self._vectors = embedder.embed_passages([c.text for c in chunks])
                self._embedder = embedder
            except Exception:  # a broken embedder must not break retrieval
                self._vectors = None
        self._weekdays = _weekday_index(chunks)

    @property
    def degraded_vectors(self) -> bool:
        """True when only the keyword half of the hybrid is live."""
        return self._vectors is None

    def search(self, question: str, k: int = TOP_K) -> list[Retrieved]:
        if not self.chunks:
            return []
        keyword_ranks = _ranks(self._bm25.scores(tokenize(question)))
        vector_ranks = _ranks(self._cosines(question))

        day = self._day_reference(question)
        fused: list[tuple[int, float]] = []
        for i, chunk in enumerate(self.chunks):
            score = 0.0
            for ranks in (keyword_ranks, vector_ranks):
                rank = ranks.get(i)
                if rank is not None:
                    score += 1 / (RRF_K + rank)
            if day is not None and chunk.day == day:
                score += DAY_BOOST
            if score > 0:
                fused.append((i, score))

        fused.sort(key=lambda pair: (-pair[1], pair[0]))
        return [Retrieved(chunk=self.chunks[i], score=s) for i, s in fused[:k]]

    def _cosines(self, question: str) -> list[float]:
        """Cosine similarity against every chunk. Pure Python: 200 chunks x 384
        dims is microseconds, and it keeps numpy off the BM25-only path."""
        if self._vectors is None or self._embedder is None:
            return []
        try:
            query = self._embedder.embed_query(question)
        except Exception:
            return []
        out = []
        for vector in self._vectors:
            dot = sum(a * b for a, b in zip(query, vector))
            norm = math.sqrt(sum(a * a for a in query)) * math.sqrt(
                sum(b * b for b in vector)
            )
            out.append(dot / norm if norm else 0.0)
        return out

    def _day_reference(self, question: str) -> int | None:
        """"day 3" or a weekday name in the question pins the answer to one
        itinerary day — metadata the text alone matches only weakly."""
        lowered = question.lower()
        match = _DAY_REF.search(lowered)
        if match:
            day = int(match.group(1))
            return day if any(c.day == day for c in self.chunks) else None
        for weekday, day in self._weekdays.items():
            if re.search(rf"\b{weekday}\b", lowered):
                return day
        return None


def _ranks(scores: list[float]) -> dict[int, int]:
    """Map document index -> 1-based rank, dropping zero-scoring documents so
    they contribute nothing to the fusion."""
    ordered = sorted(
        (i for i, s in enumerate(scores) if s > 0),
        key=lambda i: (-scores[i], i),
    )
    return {i: rank for rank, i in enumerate(ordered, start=1)}


def _weekday_index(chunks: list[Chunk]) -> dict[str, int]:
    """Weekday name -> itinerary day number, read off the day-summary cards."""
    index: dict[str, int] = {}
    for chunk in chunks:
        if chunk.type != "day_summary" or chunk.day is None:
            continue
        for weekday in _WEEKDAYS:
            if re.search(rf"\b{weekday}\b", chunk.text.lower()):
                index.setdefault(weekday, chunk.day)
    return index
