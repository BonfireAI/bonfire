"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.embeddings.

Covers ``EmbeddingProvider`` Protocol, ``get_embedder`` factory, and
``MockEmbedder`` per Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

import sys

import pytest

from bonfire.knowledge.embeddings import EmbeddingProvider, get_embedder
from bonfire.knowledge.mock_embedder import MockEmbedder


class TestEmbeddingProvider:
    def test_embedding_provider_is_runtime_checkable(self):
        embedder = MockEmbedder(dim=32)
        assert isinstance(embedder, EmbeddingProvider)


class TestGetEmbedder:
    def test_get_embedder_mock_default(self):
        embedder = get_embedder(provider="mock")
        assert isinstance(embedder, EmbeddingProvider)

    def test_get_embedder_ollama_requires_ollama_package(self, monkeypatch):
        # Hide ollama from import machinery; factory should raise ImportError.
        monkeypatch.setitem(sys.modules, "ollama", None)
        with pytest.raises(ImportError):
            get_embedder(provider="ollama")

    def test_get_embedder_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError):
            get_embedder(provider="not-a-real-provider")


class TestMockEmbedder:
    def test_mock_embedder_dim_matches_constructor(self):
        embedder = MockEmbedder(dim=128)
        assert embedder.dim == 128

    def test_mock_embedder_produces_deterministic_vectors(self):
        embedder = MockEmbedder(dim=64)
        a = embedder.embed(["same text"])
        b = embedder.embed(["same text"])
        assert a == b

    def test_mock_embedder_batch_size_matches_input(self):
        embedder = MockEmbedder(dim=32)
        vectors = embedder.embed(["a", "b", "c"])
        assert len(vectors) == 3
        assert all(len(v) == 32 for v in vectors)
