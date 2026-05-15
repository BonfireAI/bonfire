# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests — BON-915 — `LanceDBBackend.exists` routes hash lookups through
a zero-vector ANN search.

Surfaced by the Mirror Path B production-1 performance Scout. Hash-based
existence checks are an index-only operation. The current ``exists`` does:

    self._table.search([0.0] * self._embedder.dim)
        .where(f"content_hash = '{hash}'")
        .limit(1).to_list()

That is a *vector search* with a zero vector plus a SQL-style filter —
LanceDB still scores the zero vector against the index even though the
answer is fully determined by the ``content_hash`` filter. ``count_rows()``
is also called first, doubling the work. Every ``KnowledgeIngestConsumer``
store and every ``scan_and_store`` into a LanceDB-backed vault hits this.

These tests pin the *intended post-fix* behaviour, deterministically and
offline. They never touch real LanceDB: a fake table is injected directly
onto a ``LanceDBBackend`` instance (``_ensure_connected`` early-returns when
``_table is not None``), so the tests record exactly how ``exists`` drives
the table API:

* ``exists`` uses LanceDB's filter-only search path — ``search()`` is
  called with **no query vector** (or LanceDB's no-arg/None filter-only
  form), never a zero vector of embedder dimension.
* the ``count_rows`` call is removed from the ``exists`` hot path.
* existence semantics are preserved — ``True`` when the hash is present,
  ``False`` when absent, ``False`` on an empty table, exceptions swallowed.

This file deliberately does NOT require the optional ``lancedb`` dependency
(``bonfire-ai[knowledge]``) — it stubs the table. The one test that asserts
the real package wiring is skipped when ``lancedb`` is absent.

Test authors and implementation authors are different hands (TDD law).
Implementation NEVER edits this file.
"""

from __future__ import annotations

from typing import Any

import pytest

from bonfire.knowledge.backend import LanceDBBackend


class _FakeEmbedder:
    """Minimal EmbeddingProvider stand-in. ``dim`` matches a real vault."""

    dim = 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dim for _ in texts]


class _FakeSearch:
    """Records how a search chain is built and what it was seeded with."""

    def __init__(self, table: _FakeTable, query_vector: Any) -> None:
        self._table = table
        self._table.search_calls.append(query_vector)
        self._where: str | None = None

    def where(self, expr: str) -> _FakeSearch:
        self._where = expr
        return self

    def limit(self, n: int) -> _FakeSearch:
        return self

    def to_list(self) -> list[dict[str, Any]]:
        # Honour the content_hash filter so existence semantics can be tested.
        if self._where is None:
            return list(self._table.rows)
        matched = []
        for row in self._table.rows:
            for key, value in self._table._parse_eq(self._where):
                if str(row.get(key)) == value:
                    matched.append(row)
        return matched


class _FakeTable:
    """A fake LanceDB table that records search() invocations.

    ``search_calls`` holds, in order, the positional argument each
    ``search(...)`` got — a zero vector for the buggy ANN path, or
    ``None`` / nothing for the intended filter-only path.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.search_calls: list[Any] = []
        self.count_rows_calls = 0

    def count_rows(self) -> int:
        self.count_rows_calls += 1
        return len(self.rows)

    def search(self, query_vector: Any = None) -> _FakeSearch:
        return _FakeSearch(self, query_vector)

    @staticmethod
    def _parse_eq(expr: str) -> list[tuple[str, str]]:
        """Parse ``field = 'value'`` clauses out of a simple where-expr."""
        pairs = []
        for clause in expr.split(" AND "):
            if "=" in clause:
                field, _, raw = clause.partition("=")
                pairs.append((field.strip(), raw.strip().strip("'")))
        return pairs


def _make_backend(rows: list[dict[str, Any]]) -> tuple[LanceDBBackend, _FakeTable]:
    """Build a LanceDBBackend with a fake table injected (no real connect)."""
    backend = LanceDBBackend(vault_path="<unused>", embedder=_FakeEmbedder())  # type: ignore[arg-type]
    table = _FakeTable(rows)
    backend._table = table  # _ensure_connected early-returns when _table is set
    return backend, table


def _is_zero_vector(arg: Any, dim: int = 768) -> bool:
    """True if ``arg`` looks like a zero query vector of embedder dimension."""
    if not isinstance(arg, (list, tuple)):
        return False
    return len(arg) == dim and all(v == 0.0 for v in arg)


class TestExistsUsesFilterOnlyPath:
    """AC: ``LanceDBBackend.exists`` uses LanceDB's filter-only API — no
    zero-vector ANN scoring."""

    async def test_exists_does_not_search_with_zero_vector(self) -> None:
        """``exists`` must not seed ``search()`` with a zero vector of
        embedder dimension. The filter-only path calls ``search()`` with no
        query vector (or ``None``); the buggy path passes ``[0.0]*dim``."""
        rows = [{"content_hash": "present-hash", "content": "x"}]
        backend, table = _make_backend(rows)

        await backend.exists("present-hash")

        assert table.search_calls, "exists() never called table.search()"
        for arg in table.search_calls:
            assert not _is_zero_vector(arg, backend._embedder.dim), (
                "exists() seeded search() with a zero query vector — that is the "
                "BON-915 ANN-scoring defect; use the filter-only search path "
                "(no query vector)."
            )

    async def test_exists_does_not_call_count_rows(self) -> None:
        """AC: ``count_rows`` is removed from the ``exists`` hot path. The
        buggy implementation calls ``count_rows()`` first (doubling cost)."""
        rows = [{"content_hash": "present-hash", "content": "x"}]
        backend, table = _make_backend(rows)

        await backend.exists("present-hash")

        assert table.count_rows_calls == 0, (
            f"exists() called count_rows() {table.count_rows_calls} time(s) — it "
            "must be removed from the hot path (the where-filter alone determines "
            "the answer)."
        )

    async def test_exists_on_empty_table_avoids_zero_vector_search(self) -> None:
        """Even the empty-table fast path must not fall through to a
        zero-vector ANN search."""
        backend, table = _make_backend([])

        result = await backend.exists("anything")

        assert result is False
        for arg in table.search_calls:
            assert not _is_zero_vector(arg, backend._embedder.dim), (
                "exists() on an empty table still issued a zero-vector ANN search."
            )


class TestExistsSemanticsPreserved:
    """AC: existing ``exists`` semantics preserved (true/false on hash
    presence)."""

    async def test_exists_returns_true_for_present_hash(self) -> None:
        rows = [
            {"content_hash": "h-aaa", "content": "a"},
            {"content_hash": "h-bbb", "content": "b"},
        ]
        backend, _ = _make_backend(rows)
        assert await backend.exists("h-bbb") is True

    async def test_exists_returns_false_for_absent_hash(self) -> None:
        rows = [{"content_hash": "h-aaa", "content": "a"}]
        backend, _ = _make_backend(rows)
        assert await backend.exists("h-zzz") is False

    async def test_exists_returns_false_on_empty_table(self) -> None:
        backend, _ = _make_backend([])
        assert await backend.exists("h-aaa") is False

    async def test_exists_escapes_single_quotes_in_hash(self) -> None:
        """A hash containing a single quote must not break the filter
        expression — the existing implementation escapes ``'`` -> ``''``."""
        rows = [{"content_hash": "h'with'quote", "content": "a"}]
        backend, _ = _make_backend(rows)
        # Should not raise and should resolve cleanly to a bool.
        result = await backend.exists("h'with'quote")
        assert isinstance(result, bool)


class TestRealLanceDBWiring:
    """Optional-dependency wiring check — only runs when ``lancedb`` is
    installed (``bonfire-ai[knowledge]``). Confirms the backend constructs
    and exposes ``exists`` as an async method on the real import path."""

    def test_backend_exposes_async_exists(self) -> None:
        pytest.importorskip("lancedb")
        import inspect

        assert inspect.iscoroutinefunction(LanceDBBackend.exists), (
            "LanceDBBackend.exists must remain an async method."
        )
