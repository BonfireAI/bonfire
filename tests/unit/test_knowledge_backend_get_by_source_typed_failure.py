# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Elegance-Law contract for ``LanceDBBackend.get_by_source()``.

``get_by_source()`` is the source-path retrieval path on the ``VaultBackend``
contract: callers ask "give me every entry that originated from this file" and
treat the returned list as the complete, authoritative answer. A real backend
failure — ``search().where().to_list()`` raising because the table is corrupt,
the store is unreachable, or a vector op blows up — was previously swallowed
into ``return []``. That ``[]`` is **indistinguishable from a legitimate
"no entries for this source path"**, so a failed lookup masqueraded as "nothing
is stored from here": the caller proceeds on partial truth with no typed signal,
no retryable flag, no context. That is exactly the swallowed-failure the Elegance
Law forbids — and the exact masquerade its structural sibling ``query()`` already
had removed (``query`` now raises a typed ``RetrievalError`` instead of ``[]``).

``get_by_source()`` is the overlooked sibling: same ``table.search(...).where(
...).to_list()`` shape, same "list of entries" return type, same indistinguishable
``[]``. This test pins the matching contract: a backend failure inside
``get_by_source()`` must surface as a typed :class:`bonfire.errors.RetrievalError`
(the one vocabulary; ``code == "retrieval"``, ``retryable is True``) carrying the
originating exception as its ``__cause__`` and naming the source path in its
structured context — NOT a bare ``[]``. A genuine empty result (zero matching
entries) stays a legitimate success and returns ``[]``.

Note the deliberate divergence from the *other* sibling, ``exists()``: that method
fail-opens to ``False`` by documented design (its caller treats a false-negative
as a harmless dedup miss). ``get_by_source()`` has no such fail-open caller — its
list IS the answer — so, like ``query()``, it must raise rather than degrade.

``lancedb`` is not a test dependency, so we never connect to a real store: we
pre-set the backend's private ``_table``/``_db`` so ``_ensure_connected()`` is a
no-op and inject a fake table whose ``.search(...).where(...).to_list()`` raises.
That exercises the exact ``except`` arm under test without any LanceDB runtime.
"""

from __future__ import annotations

import pytest

from bonfire.errors import BonfireError, RetrievalError
from bonfire.knowledge.backend import LanceDBBackend


class _FakeEmbedder:
    """Minimal embedder stub — ``get_by_source()`` only reads ``dim`` for the
    zero-vector probe; it never embeds free text."""

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
    """Non-empty table whose source-path query fails at ``to_list()``."""

    def count_rows(self) -> int:
        # Non-empty so ``get_by_source()`` proceeds past the early empty-table
        # guard and reaches the protected ``search(...).where(...).to_list()``.
        return 1

    def search(self, _vector: object) -> _ExplodingSearch:
        return _ExplodingSearch()


class _EmptyHitSearch:
    def limit(self, _n: int) -> _EmptyHitSearch:
        return self

    def where(self, _clause: str) -> _EmptyHitSearch:
        return self

    def to_list(self) -> list[dict[str, object]]:
        return []


class _EmptyHitTable:
    """Non-empty table whose source-path query legitimately matches nothing."""

    def count_rows(self) -> int:
        return 1

    def search(self, _vector: object) -> _EmptyHitSearch:
        return _EmptyHitSearch()


def _make_backend(table: object) -> LanceDBBackend:
    backend = LanceDBBackend(vault_path=":memory:", embedder=_FakeEmbedder())
    # Pre-wire the lazy-connect fields so ``_ensure_connected()`` short-circuits
    # (it returns early when ``_table is not None``) and never imports lancedb.
    backend._table = table
    backend._db = object()
    return backend


@pytest.mark.asyncio
async def test_get_by_source_backend_failure_raises_typed_retrieval_error() -> None:
    """A failed ``get_by_source()`` lookup must speak the one vocabulary, not ``[]``."""
    backend = _make_backend(_ExplodingTable())

    with pytest.raises(RetrievalError) as exc_info:
        await backend.get_by_source("/src/whatever.py")

    err = exc_info.value
    assert isinstance(err, BonfireError), "must be in the one Bonfire vocabulary"
    assert err.code == "retrieval"
    assert err.retryable is True, "a transient retrieval failure is retryable"


@pytest.mark.asyncio
async def test_get_by_source_failure_chains_the_original_exception() -> None:
    """The typed error must carry the originating exception (no lost traceback)."""
    backend = _make_backend(_ExplodingTable())

    with pytest.raises(RetrievalError) as exc_info:
        await backend.get_by_source("/src/whatever.py")

    cause = exc_info.value.__cause__
    assert isinstance(cause, RuntimeError)
    assert "simulated LanceDB to_list failure" in str(cause)


@pytest.mark.asyncio
async def test_get_by_source_failure_context_carries_the_source_path() -> None:
    """Structured context must name the source path so the failure is self-describing."""
    backend = _make_backend(_ExplodingTable())

    with pytest.raises(RetrievalError) as exc_info:
        await backend.get_by_source("/src/needle.py")

    assert exc_info.value.context.get("source_path") == "/src/needle.py"


@pytest.mark.asyncio
async def test_get_by_source_zero_hits_is_a_success_not_an_error() -> None:
    """A genuine empty result (no matching entries) stays a success — returns []."""
    backend = _make_backend(_EmptyHitTable())

    result = await backend.get_by_source("/src/unstored.py")

    assert result == []
