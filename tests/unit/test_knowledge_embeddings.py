"""RED tests — BON-341 W5.2 — `bonfire.knowledge.embeddings` + `mock_embedder`.

Sage D8.2 type locks:
- ``EmbeddingProvider`` is @runtime_checkable Protocol with
  ``embed(texts: list[str]) -> list[list[float]]`` and property ``dim: int``.
- ``get_embedder(provider="mock", *, model="nomic-embed-text", dim=768, **kwargs)``.
  Branches: ``"ollama"``, ``"mock"``. Raises ValueError on unknown.
- ``MockEmbedder(dim=768)`` — deterministic SHA-256-derived vectors.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from bonfire.knowledge.embeddings import EmbeddingProvider, get_embedder
from bonfire.knowledge.mock_embedder import MockEmbedder


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestEmbeddingProviderProtocol:
    def test_embedding_provider_is_runtime_checkable(self) -> None:
        """MockEmbedder satisfies the protocol via structural conformance."""
        embedder = MockEmbedder()
        assert isinstance(embedder, EmbeddingProvider)

    # knight-a(innovative): explicit rejection of non-conforming duck-types.
    def test_embedding_provider_rejects_missing_methods(self) -> None:
        class Missing:
            """No embed() method, no dim property."""

        # runtime_checkable only checks presence, but this one should fail.
        assert not isinstance(Missing(), EmbeddingProvider)


# ---------------------------------------------------------------------------
# Factory branches
# ---------------------------------------------------------------------------


class TestGetEmbedderFactory:
    def test_get_embedder_mock_default(self) -> None:
        """Default provider is 'mock'."""
        embedder = get_embedder()
        assert isinstance(embedder, MockEmbedder)

    def test_get_embedder_mock_explicit(self) -> None:
        embedder = get_embedder(provider="mock")
        assert isinstance(embedder, MockEmbedder)

    def test_get_embedder_unknown_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            get_embedder(provider="not-a-real-provider")

    # knight-a(innovative): unknown-provider error message includes the name.
    def test_get_embedder_unknown_provider_message_cites_name(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            get_embedder(provider="does-not-exist")
        assert "does-not-exist" in str(excinfo.value)

    def test_get_embedder_ollama_requires_ollama_package(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ollama is unavailable, ollama branch raises ImportError."""
        # Remove any cached bonfire.knowledge.ollama_embedder + ollama from sys.modules.
        for mod in list(sys.modules):
            if mod == "ollama" or mod.startswith("ollama.") or mod.endswith(
                "ollama_embedder"
            ):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        # Simulate no ollama package at all.
        monkeypatch.setitem(sys.modules, "ollama", None)
        with pytest.raises(ImportError):
            get_embedder(provider="ollama")


# ---------------------------------------------------------------------------
# MockEmbedder — deterministic vector surface
# ---------------------------------------------------------------------------


class TestMockEmbedder:
    def test_mock_embedder_dim_matches_constructor(self) -> None:
        """dim property returns whatever was passed to __init__."""
        assert MockEmbedder(dim=128).dim == 128
        assert MockEmbedder(dim=768).dim == 768

    def test_mock_embedder_default_dim_is_768(self) -> None:
        assert MockEmbedder().dim == 768

    def test_mock_embedder_produces_deterministic_vectors(self) -> None:
        """Same input -> same vector across calls and instances."""
        v1 = MockEmbedder().embed(["hello"])
        v2 = MockEmbedder().embed(["hello"])
        assert v1 == v2

    def test_mock_embedder_batch_size_matches_input(self) -> None:
        """embed(N texts) returns N vectors."""
        out = MockEmbedder().embed(["a", "b", "c", "d"])
        assert len(out) == 4

    # knight-a(innovative): each vector has exactly `dim` floats.
    def test_mock_embedder_vector_length_matches_dim(self) -> None:
        embedder = MockEmbedder(dim=64)
        out = embedder.embed(["x"])
        assert len(out) == 1
        assert len(out[0]) == 64
        assert all(isinstance(f, float) for f in out[0])

    # knight-a(innovative): different inputs produce different vectors.
    def test_mock_embedder_distinct_inputs_produce_distinct_vectors(self) -> None:
        out = MockEmbedder().embed(["alpha", "beta"])
        assert out[0] != out[1]

    # knight-a(innovative): empty input list returns empty list.
    def test_mock_embedder_empty_input_returns_empty_output(self) -> None:
        assert MockEmbedder().embed([]) == []


# ---------------------------------------------------------------------------
# get_embedder pass-through
# ---------------------------------------------------------------------------


class TestGetEmbedderPassThrough:
    """Factory forwards dim/model to constructor (innovative check)."""

    def test_get_embedder_respects_dim(self) -> None:
        embedder: Any = get_embedder(provider="mock", dim=256)
        assert embedder.dim == 256
