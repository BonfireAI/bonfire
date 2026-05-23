# SPDX-License-Identifier: Apache-2.0
"""Tests for prebake_retrieval — the retrieval-to-reach_context utility."""

from __future__ import annotations

import logging

from bonfire.prompt.precompose import prebake_retrieval
from bonfire.protocols import ContextAtom


class _FakeProvider:
    def __init__(self, atoms: list[ContextAtom]) -> None:
        self._atoms = atoms
        self.calls: list[tuple[str, list[str] | None, int]] = []

    async def retrieve(
        self,
        *,
        query: str,
        seed_keys: list[str] | None = None,
        token_budget: int = 4000,
    ) -> list[ContextAtom]:
        self.calls.append((query, seed_keys, token_budget))
        return self._atoms


class _RaisingProvider:
    async def retrieve(
        self,
        *,
        query: str,
        seed_keys: list[str] | None = None,
        token_budget: int = 4000,
    ) -> list[ContextAtom]:
        raise RuntimeError("boom")


async def test_prebake_with_none_provider_returns_empty_dict():
    result = await prebake_retrieval("any task", provider=None)
    assert result == {}


async def test_prebake_with_provider_returns_retrieved_atoms_dict():
    atoms = [
        ContextAtom(key="a", body="aaa", source_path="/a.md", score=0.9),
        ContextAtom(key="b", body="bbb", source_path="/b.md", score=0.5),
    ]
    provider = _FakeProvider(atoms=atoms)
    result = await prebake_retrieval("a task", provider=provider, token_budget=2000)
    assert "retrieved_atoms" in result
    assert len(result["retrieved_atoms"]) == 2
    assert result["retrieved_atoms"][0]["key"] == "a"
    assert provider.calls == [("a task", None, 2000)]


async def test_prebake_serializes_atoms_as_dicts():
    """reach_context is a dict; retrieved_atoms must be JSON-friendly."""
    atoms = [ContextAtom(key="k", body="b", source_path="/p", score=1.0)]
    provider = _FakeProvider(atoms=atoms)
    result = await prebake_retrieval("q", provider=provider)
    assert isinstance(result["retrieved_atoms"], list)
    for item in result["retrieved_atoms"]:
        assert isinstance(item, dict)
        assert set(item.keys()) == {"key", "body", "source_path", "score"}


async def test_prebake_catches_provider_exceptions(caplog):
    provider = _RaisingProvider()
    with caplog.at_level(logging.WARNING):
        result = await prebake_retrieval("q", provider=provider)
    assert result == {}
    assert any("RuntimeError" in r.message for r in caplog.records)


async def test_prebake_empty_provider_result_yields_empty_list():
    provider = _FakeProvider(atoms=[])
    result = await prebake_retrieval("q", provider=provider)
    assert result == {"retrieved_atoms": []}
