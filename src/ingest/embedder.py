"""Embedding backend.

BAAI/bge-base-en-v1.5 (MIT, 768-dim) rather than nomic-embed-text-v1.5, for two
reasons that matter to this project specifically: nomic requires
``trust_remote_code=True`` -- arbitrary code execution at import time, which sits
badly in a repo whose SECURITY.md is largely about supply-chain integrity -- and
it needs ``search_document:`` / ``search_query:`` task prefixes that
BUILD_SEQUENCE.md never applies, silently costing retrieval quality.

BGE has its own asymmetry: queries take a short instruction prefix, passages take
none. Getting that backwards degrades retrieval quietly rather than loudly, so
the two directions are separate methods here instead of one flag.
"""
from __future__ import annotations

import threading
from collections.abc import Sequence

MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM = 768
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder:
    """Lazily-loaded sentence-transformers wrapper. Normalised output vectors."""

    def __init__(self, model_name: str = MODEL_NAME, device: str | None = None):
        self.model_name = model_name
        self._device = device
        self._model = None
        self._lock = threading.Lock()

    @property
    def model(self):
        """Load once, thread-safely.

        The unguarded version raced under concurrency: FastAPI runs sync handlers
        in a threadpool, so several first-requests passed the `is None` check
        together and all called SentenceTransformer at once. That surfaces as
        `NotImplementedError: Cannot copy out of meta tensor`, which reads like a
        device or memory problem and is neither. Double-checked locking, with the
        second check inside the lock so later callers do not reload.
        """
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(
                        self.model_name, device=self._device)
        return self._model

    def warm(self) -> None:
        """Force the load now rather than on someone's first query.

        A server should pay this at startup: it takes seconds, it makes a load
        failure visible immediately instead of as a 500 on a user's request, and
        it removes the window in which the race above could occur at all.
        """
        _ = self.model

    def _encode(self, texts: Sequence[str], batch_size: int, show: bool):
        # normalize_embeddings=True makes cosine distance equal to the dot
        # product, which is what vec0's distance_metric=cosine expects.
        return self.model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=show,
            convert_to_numpy=True,
        )

    def embed_passages(self, texts: Sequence[str], batch_size: int = 32,
                       show_progress: bool = False) -> list[list[float]]:
        """Embed corpus chunks. BGE passages take no prefix."""
        if not texts:
            return []
        return [v.tolist() for v in self._encode(texts, batch_size, show_progress)]

    def embed_query(self, text: str) -> list[float]:
        """Embed a user question. BGE queries take the retrieval instruction."""
        return self._encode([QUERY_INSTRUCTION + text], 1, False)[0].tolist()
