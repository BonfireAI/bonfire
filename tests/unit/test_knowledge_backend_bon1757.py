# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""BON-1757 — narrow the broad-except in ``LanceDBBackend.exists``.

The existence check is a LanceDB filter-only query that can fail at the
storage layer. The graceful contract is unchanged: a query failure yields a
``False`` (the hash is treated as not present) rather than propagating. What
changed is the *type* caught — previously a blanket ``except Exception`` with
a ``# noqa: BLE001`` suppression, now the narrowed ``(RuntimeError, OSError,
ValueError)`` set that the LanceDB backend can realistically raise.

These tests pin the post-fix graceful-degradation behaviour deterministically
and offline. They never touch real LanceDB (an optional ``bonfire-ai[knowledge]``
dependency): a fake table is injected directly onto a ``LanceDBBackend``
instance, whose ``search()`` raises on the existence-check path. The
``_ensure_connected`` early-returns when ``_table is not None``, so no real
connect occurs.

Test authors and implementation authors are different hands (TDD law).
Implementation NEVER edits this file.
"""

from __future__ import annotations

from typing import Any

import pytest

from bonfire.knowledge.backend import LanceDBBackend


class _FakeEmbedder:
    """Minimal EmbeddingProvider stand-in."""

    dim = 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dim for _ in texts]


class _RaisingTable:
    """A fake LanceDB table whose existence-check query raises.

    ``search()`` returns a chain object whose terminal ``to_list()`` raises
    ``exc`` — modelling a storage-layer failure during the filter-only
    existence lookup.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def search(self, query_vector: Any = None) -> _RaisingSearch:
        return _RaisingSearch(self._exc)


class _RaisingSearch:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def where(self, expr: str) -> _RaisingSearch:
        return self

    def limit(self, n: int) -> _RaisingSearch:
        return self

    def to_list(self) -> list[dict[str, Any]]:
        raise self._exc


def _make_backend(exc: Exception) -> LanceDBBackend:
    """Build a backend with a table whose existence query raises ``exc``."""
    backend = LanceDBBackend(vault_path="<unused>", embedder=_FakeEmbedder())  # type: ignore[arg-type]
    backend._table = _RaisingTable(exc)  # _ensure_connected early-returns
    return backend


class TestExistsGracefulDegradation:
    """AC: ``exists`` degrades gracefully to ``False`` on query failure,
    catching the narrowed ``(RuntimeError, OSError, ValueError)`` set."""

    async def test_exists_returns_false_on_runtime_error(self) -> None:
        backend = _make_backend(RuntimeError("lance query exploded"))
        assert await backend.exists("any-hash") is False

    async def test_exists_returns_false_on_os_error(self) -> None:
        backend = _make_backend(OSError("vault file unreadable"))
        assert await backend.exists("any-hash") is False

    async def test_exists_returns_false_on_value_error(self) -> None:
        backend = _make_backend(ValueError("bad filter expression"))
        assert await backend.exists("any-hash") is False

    async def test_exists_does_not_swallow_unexpected_error(self) -> None:
        """An error outside the narrowed set must propagate, not be hidden —
        the broad-except previously masked everything (BON-1757)."""
        backend = _make_backend(KeyError("programmer bug, not a storage failure"))
        with pytest.raises(KeyError):
            await backend.exists("any-hash")
