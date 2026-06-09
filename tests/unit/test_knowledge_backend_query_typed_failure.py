# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Elegance-Law contract for ``LanceDBBackend.query()``.

``query()`` is the primary retrieval path: callers (``RipgrepRetrievalProvider``,
``ingest.retrieve_similar``) delegate to it directly and treat its return value as
"the matching entries". A real backend failure — ``search().to_list()`` raising
because the table is corrupt, the store is unreachable, or a vector op blows up —
was previously swallowed into ``return []``. That ``[]`` is **indistinguishable
from a legitimate zero-hit result**, so a failed lookup masqueraded as "nothing
matched": the caller proceeds on partial truth with no typed signal, no retryable
flag, no context. That is exactly the swallowed-failure the Elegance Law forbids.

This test pins the contract: a backend failure inside ``query()`` must surface as
a typed :class:`bonfire.errors.RetrievalError` (the one vocabulary; ``code ==
"retrieval"``, ``retryable is True``) carrying the originating exception as its
``__cause__`` — NOT a bare ``[]``. A genuine empty result (zero hits) stays a
legitimate success and returns ``[]``.

``lancedb`` is not a test dependency, so we never connect to a real store: we
pre-set the backend's private ``_table``/``_db`` so ``_ensure_connected()`` is a
no-op and inject a fake table whose ``.search(...).to_list()`` raises. That
exercises the exact ``except`` arm under test without any LanceDB runtime.
"""

from __future__ import annotations

import pytest

from bonfire.errors import BonfireError, RetrievalError
from bonfire.knowledge.backend import LanceDBBackend


class _FakeEmbedder:
    """Minimal embedder stub — ``query()`` only needs ``embed()`` + ``dim``."""

    dim = 4

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


class _ExplodingSearch:
    """A search builder whose terminal ``.to_list()`` blows up."""

    def limit(self, _n: int) -> _ExplodingSearch:
        return self

    def where(self, _clause: str) -> _ExplodingSearch:
        return self

    def to_list(self) -> list[dict[str, object]]:
        raise RuntimeError("simulated LanceDB to_list failure")


class _ExplodingTable:
    """Non-empty table whose query path fails at ``to_list()``."""

    def count_rows(self) -> int:
        # Non-empty so ``query()`` proceeds past the early empty-table guard
        # and reaches the protected ``search(...).to_list()`` block.
        return 1

    def search(self, _vector: object) -> _ExplodingSearch:
        return _ExplodingSearch()


class _EmptyHitTable:
    """Non-empty table whose query legitimately returns zero matches."""

    def count_rows(self) -> int:
        return 1

    def search(self, _vector: object) -> _EmptyHitSearch:
        return _EmptyHitSearch()


class _EmptyHitSearch:
    def limit(self, _n: int) -> _EmptyHitSearch:
        return self

    def where(self, _clause: str) -> _EmptyHitSearch:
        return self

    def to_list(self) -> list[dict[str, object]]:
        return []


def _make_backend(table: object) -> LanceDBBackend:
    backend = LanceDBBackend(vault_path=":memory:", embedder=_FakeEmbedder())
    # Pre-wire the lazy-connect fields so ``_ensure_connected()`` short-circuits
    # (it returns early when ``_table is not None``) and never imports lancedb.
    backend._table = table
    backend._db = object()
    return backend


@pytest.mark.asyncio
async def test_query_backend_failure_raises_typed_retrieval_error() -> None:
    """A failed ``query()`` lookup must speak the one vocabulary, not return ``[]``."""
    backend = _make_backend(_ExplodingTable())

    with pytest.raises(RetrievalError) as exc_info:
        await backend.query("anything")

    err = exc_info.value
    assert isinstance(err, BonfireError), "must be in the one Bonfire vocabulary"
    assert err.code == "retrieval"
    assert err.retryable is True, "a transient retrieval failure is retryable"


@pytest.mark.asyncio
async def test_query_failure_chains_the_original_exception() -> None:
    """The typed error must carry the originating exception (no lost traceback)."""
    backend = _make_backend(_ExplodingTable())

    with pytest.raises(RetrievalError) as exc_info:
        await backend.query("anything")

    cause = exc_info.value.__cause__
    assert isinstance(cause, RuntimeError)
    assert "simulated LanceDB to_list failure" in str(cause)


@pytest.mark.asyncio
async def test_query_failure_context_carries_the_query() -> None:
    """Structured context must name the query so the failure is self-describing."""
    backend = _make_backend(_ExplodingTable())

    with pytest.raises(RetrievalError) as exc_info:
        await backend.query("needle-in-haystack")

    assert exc_info.value.context.get("query") == "needle-in-haystack"


@pytest.mark.asyncio
async def test_query_zero_hits_is_a_success_not_an_error() -> None:
    """A genuine empty result (zero hits) stays a legitimate success — returns []."""
    backend = _make_backend(_EmptyHitTable())

    result = await backend.query("no-matches-here")

    assert result == []
