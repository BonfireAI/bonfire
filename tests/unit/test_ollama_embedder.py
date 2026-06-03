# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Unit tests for ``OllamaEmbedder`` error paths and batch chunking.

The embedder talks to a local Ollama server, but every test here mocks
``self._client.embed`` so no server (and no ``ollama`` package) is required:
the constructor's ``import ollama`` is satisfied with a fake module injected
into ``sys.modules``, and the client method is patched per-test.

These tests pin the behavior of ``_embed_batch``:

- a connection-flavored exception is translated to ``NetworkError`` with a
  "server not running" hint,
- a ``status_code == 404`` exception is translated to ``RetrievalError`` with a
  "model not found" hint,
- a wrong-length embedding row raises ``ValueError`` (dimension mismatch),
- empty input short-circuits to ``[]`` without calling the client,
- inputs longer than ``max_batch_size`` are chunked into multiple
  ``_embed_batch`` calls.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest import mock

import pytest

from bonfire.errors import NetworkError, RetrievalError


def _install_fake_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake ``ollama`` module so ``OllamaEmbedder.__init__`` succeeds.

    The fake ``Client`` records nothing; tests patch ``embedder._client.embed``
    after construction. Any cached real/fake module and the embedder module are
    cleared first so the constructor's ``import ollama`` resolves to the fake.
    """
    for name in list(sys.modules):
        if name == "ollama" or name.startswith("ollama."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    fake = types.ModuleType("ollama")

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def embed(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("embed must be patched per-test")

    fake.Client = _FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ollama", fake)


def _make_embedder(monkeypatch: pytest.MonkeyPatch, **kwargs: Any):
    """Construct an ``OllamaEmbedder`` against the fake ``ollama`` module."""
    _install_fake_ollama(monkeypatch)
    from bonfire.knowledge.ollama_embedder import OllamaEmbedder

    return OllamaEmbedder(**kwargs)


class TestEmbedBatchErrorPaths:
    def test_connection_error_raises_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An exception whose class name contains 'connect' -> NetworkError + hint."""
        embedder = _make_embedder(monkeypatch)

        class ConnectError(Exception):
            pass

        with mock.patch.object(embedder._client, "embed", side_effect=ConnectError("refused")):
            with pytest.raises(NetworkError, match="server not running"):
                embedder.embed(["hello"])

    def test_404_raises_retrieval_error_with_pull_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exception with ``status_code == 404`` -> RetrievalError + model-not-found hint."""
        embedder = _make_embedder(monkeypatch, model="nomic-embed-text")

        class NotFound(Exception):
            status_code = 404

        with mock.patch.object(embedder._client, "embed", side_effect=NotFound("nope")):
            with pytest.raises(RetrievalError, match="not found"):
                embedder.embed(["hello"])

    def test_dimension_mismatch_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A response row of the wrong length -> ValueError naming both dims."""
        embedder = _make_embedder(monkeypatch, dim=768)
        bad_response = {"embeddings": [[0.0, 0.1, 0.2]]}  # len 3, expected 768

        with mock.patch.object(embedder._client, "embed", return_value=bad_response):
            with pytest.raises(ValueError, match="Dimension mismatch"):
                embedder.embed(["hello"])

    def test_unrecognized_exception_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An exception that is neither connection-flavored nor 404 re-raises as-is."""
        embedder = _make_embedder(monkeypatch)

        class WeirdError(Exception):
            pass

        with mock.patch.object(embedder._client, "embed", side_effect=WeirdError("boom")):
            with pytest.raises(WeirdError, match="boom"):
                embedder.embed(["hello"])


class TestEmbedHappyPaths:
    def test_empty_input_returns_empty_without_calling_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty input short-circuits to [] and never touches the client."""
        embedder = _make_embedder(monkeypatch)

        with mock.patch.object(embedder._client, "embed") as embed_mock:
            assert embedder.embed([]) == []
        embed_mock.assert_not_called()

    def test_batch_chunking_triggers_two_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """9 texts at max_batch_size=8 -> two _embed_batch calls (8 then 1)."""
        embedder = _make_embedder(monkeypatch, dim=2, max_batch_size=8)

        def fake_embed(*, model: str, input: list[str]) -> dict[str, Any]:
            # Return one 2-dim vector per input text in this batch.
            return {"embeddings": [[0.0, 1.0] for _ in input]}

        with mock.patch.object(embedder._client, "embed", side_effect=fake_embed) as embed_mock:
            out = embedder.embed([f"t{i}" for i in range(9)])

        assert embed_mock.call_count == 2
        first_batch = embed_mock.call_args_list[0].kwargs["input"]
        second_batch = embed_mock.call_args_list[1].kwargs["input"]
        assert len(first_batch) == 8
        assert len(second_batch) == 1
        assert len(out) == 9

    def test_prefix_is_prepended_to_each_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each text is sent to the client with the configured prefix prepended."""
        embedder = _make_embedder(monkeypatch, dim=2, prefix="search_document: ", max_batch_size=8)

        def fake_embed(*, model: str, input: list[str]) -> dict[str, Any]:
            return {"embeddings": [[0.0, 1.0] for _ in input]}

        with mock.patch.object(embedder._client, "embed", side_effect=fake_embed) as embed_mock:
            embedder.embed(["alpha", "beta"])

        sent = embed_mock.call_args_list[0].kwargs["input"]
        assert sent == ["search_document: alpha", "search_document: beta"]
