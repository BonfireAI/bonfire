"""Embedding provider protocol and factory.

Abstracts embedding generation behind a protocol. The vault backend
calls embedders internally -- callers never touch vectors.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding text into vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dim(self) -> int: ...


def get_embedder(
    provider: str = "mock",
    *,
    model: str = "nomic-embed-text",
    dim: int = 768,
    **kwargs: Any,
) -> EmbeddingProvider:
    """Return the configured embedding provider.

    Lazy imports to avoid loading heavy dependencies at module level.
    """
    if provider == "ollama":
        from bonfire.knowledge.ollama_embedder import OllamaEmbedder

        return OllamaEmbedder(model=model, dim=dim, **kwargs)
    if provider == "mock":
        from bonfire.knowledge.mock_embedder import MockEmbedder

        return MockEmbedder(dim=dim)
    raise ValueError(f"Unknown embedding provider: {provider!r}")
