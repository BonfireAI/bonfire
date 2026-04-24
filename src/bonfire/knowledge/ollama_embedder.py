"""Local embedding via Ollama server.

Requires: pip install ollama, Ollama server running, model pulled.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OllamaEmbedder:
    """Local embedding via Ollama server (nomic-embed-text by default).

    Prepends a task prefix to each text before embedding (nomic-embed-text
    requires this for best quality). Default prefix: "search_document: ".

    Batches are chunked to max_batch_size (default 8) to avoid a known
    quality degradation bug in Ollama at batch sizes >= 16.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        dim: int = 768,
        prefix: str = "search_document: ",
        max_batch_size: int = 8,
        host: str | None = None,
        **_kwargs: Any,
    ) -> None:
        try:
            import ollama as _ollama
        except ImportError:
            raise ImportError(
                "ollama is required for OllamaEmbedder. Install it with: pip install ollama"
            ) from None
        if _ollama is None:
            raise ImportError(
                "ollama is required for OllamaEmbedder. Install it with: pip install ollama"
            )
        self._ollama = _ollama
        self._client = _ollama.Client(host=host) if host else _ollama.Client()
        self._model = model
        self._dim = dim
        self._prefix = prefix
        self._max_batch_size = max_batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via local Ollama server."""
        if not texts:
            return []
        prefixed = [f"{self._prefix}{t}" for t in texts]
        all_vectors: list[list[float]] = []
        for i in range(0, len(prefixed), self._max_batch_size):
            batch = prefixed[i : i + self._max_batch_size]
            vectors = self._embed_batch(batch)
            all_vectors.extend(vectors)
        return all_vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch via ollama Client.embed()."""
        try:
            response = self._client.embed(model=self._model, input=texts)
            embeddings = response["embeddings"]
        except Exception as exc:
            exc_name = type(exc).__name__.lower()
            if "connect" in exc_name or "connection" in exc_name:
                raise RuntimeError("Ollama server not running. Start with: ollama serve") from None
            status = getattr(exc, "status_code", None)
            if status == 404:
                raise RuntimeError(
                    f"Model '{self._model}' not found. Run: ollama pull {self._model}"
                ) from None
            raise
        if embeddings and len(embeddings[0]) != self._dim:
            raise ValueError(
                f"Dimension mismatch: expected {self._dim}, "
                f"got {len(embeddings[0])} from model '{self._model}'"
            )
        return embeddings

    @property
    def dim(self) -> int:
        return self._dim
