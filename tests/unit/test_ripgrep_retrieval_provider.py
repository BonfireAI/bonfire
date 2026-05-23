# SPDX-License-Identifier: Apache-2.0
"""Tests for RipgrepRetrievalProvider — Tier 1 default."""

from __future__ import annotations

from dataclasses import dataclass

from bonfire.knowledge.retrieval_provider import RipgrepRetrievalProvider
from bonfire.protocols import ContextAtom


@dataclass
class _FakeVaultEntry:
    """Mirror the field shape the orphan retrieve_context() emits."""

    key: str
    body: str
    source_path: str
    score: float = 1.0


class _StubBackend:
    """Implements VaultBackend.query(query, *, limit, entry_type=None)."""

    def __init__(self, hits: list[_FakeVaultEntry]) -> None:
        self._hits = hits
        self.calls: list[tuple[str, int, str | None]] = []

    def query(
        self, query: str, *, limit: int, entry_type: str | None = None
    ) -> list[_FakeVaultEntry]:
        self.calls.append((query, limit, entry_type))
        return self._hits[:limit]


def test_provider_returns_empty_on_empty_query():
    backend = _StubBackend(hits=[])
    provider = RipgrepRetrievalProvider(backend=backend)
    result = provider.retrieve(query="anything")
    assert result == []


def test_provider_translates_vault_entries_to_context_atoms():
    backend = _StubBackend(
        hits=[
            _FakeVaultEntry(key="a", body="aaa", source_path="/a.md", score=0.9),
            _FakeVaultEntry(key="b", body="bbb", source_path="/b.md", score=0.5),
        ]
    )
    provider = RipgrepRetrievalProvider(backend=backend)
    result = provider.retrieve(query="search", token_budget=4000)
    assert len(result) == 2
    assert all(isinstance(r, ContextAtom) for r in result)
    assert [r.key for r in result] == ["a", "b"]
    assert [r.score for r in result] == [0.9, 0.5]


def test_provider_respects_default_limit():
    """RipgrepRetrievalProvider uses a default per-call limit so an oversized
    backend doesn't dump the entire corpus."""
    backend = _StubBackend(
        hits=[_FakeVaultEntry(key=f"k{i}", body=f"b{i}", source_path=f"/{i}.md") for i in range(50)]
    )
    provider = RipgrepRetrievalProvider(backend=backend, default_limit=5)
    result = provider.retrieve(query="q")
    assert len(result) == 5
    assert backend.calls[-1] == ("q", 5, None)


def test_provider_ignores_seed_keys_param():
    """Tier 1 has no graph notion — seed_keys is accepted (Protocol contract)
    but ignored. Tier 2 will honor it."""
    backend = _StubBackend(hits=[])
    provider = RipgrepRetrievalProvider(backend=backend)
    result = provider.retrieve(query="q", seed_keys=["x", "y"])
    assert result == []
    # Confirm we called backend with the query, not the seed keys.
    assert backend.calls[-1][0] == "q"
