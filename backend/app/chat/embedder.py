"""Text embedding for the vector half of hybrid retrieval.

Embeddings are computed locally — never through an API — so chatting costs
nothing beyond the single answering call. `fastembed` runs BGE-small through
ONNX Runtime (no torch: Render's free tier has 512MB to spend).

Everything here is optional by design. If vectors are switched off, or the
model can't be imported or loaded, `build_embedder` returns None and the
retriever falls back to BM25 alone. Miles degrades, it never dies — the same
philosophy the pipeline applies to a failing API.
"""

import hashlib
import math
import re
from typing import Protocol

from ..config import Settings

# BGE was trained with an asymmetric query prefix; passages get none.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """fastembed's BAAI/bge-small-en-v1.5 (384-dim, quantized ONNX)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding  # lazy: heavy, and optional

        self._model = TextEmbedding(model_name=model_name)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # query_embed applies the BGE query prefix itself; passing it again
        # would double it.
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


class FakeEmbedder:
    """Deterministic bag-of-hashed-words vectors: each token lands in a fixed
    bucket, so texts sharing vocabulary come out cosine-similar. Powers tests
    and FAKE_APIS demos without downloading an ONNX model."""

    def __init__(self, dim: int = 128):
        self.dim = dim

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _WORD.findall(text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=4).digest()
            vec[int.from_bytes(digest, "big") % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


def build_embedder(settings: Settings) -> tuple[Embedder | None, str | None]:
    """Return (embedder, reason_it_is_missing). A None embedder is a supported
    state, not an error — the retriever runs keyword-only."""
    if settings.fake_apis:
        return FakeEmbedder(), None
    if not settings.chat_vectors:
        return None, "vector search disabled by configuration"
    try:
        return FastEmbedder(), None
    except Exception as exc:  # missing wheel, no disk for the model, no network
        return None, f"embedding model unavailable ({exc})"
