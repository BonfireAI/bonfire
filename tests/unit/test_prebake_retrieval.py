# SPDX-License-Identifier: Apache-2.0
"""Tests for prebake_retrieval — the retrieval-to-reach_context utility."""

from __future__ import annotations

import asyncio
import logging

from bonfire.prompt import precompose
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


# --- Timeout-containment contract -------------------------------------------
# The tests below pin the contract that a slow retrieval provider can never
# stall or break dispatch. prebake_retrieval must bound the provider call with
# a configurable timeout (BONFIRE_RETRIEVE_TIMEOUT_S, default 30.0s); on
# timeout it logs a WARNING containing "timed out", abandons (cancels) the
# provider call, and returns {} — identical containment to the exception path.


class _SlowProvider:
    """A provider whose retrieve hangs until cancelled; records cancellation."""

    def __init__(self) -> None:
        self.cancelled = False

    async def retrieve(
        self,
        *,
        query: str,
        seed_keys: list[str] | None = None,
        token_budget: int = 4000,
    ) -> list[ContextAtom]:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return []


def test_prebake_timeout_default_is_constant(monkeypatch):
    monkeypatch.delenv("BONFIRE_RETRIEVE_TIMEOUT_S", raising=False)
    assert precompose._retrieve_timeout() == precompose.DEFAULT_RETRIEVE_TIMEOUT_S
    assert precompose.DEFAULT_RETRIEVE_TIMEOUT_S == 30.0


def test_prebake_timeout_env_override(monkeypatch):
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "5")
    assert precompose._retrieve_timeout() == 5.0


async def test_prebake_slow_provider_times_out_returns_empty_dict(monkeypatch, caplog):
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "0.05")
    slow = _SlowProvider()
    with caplog.at_level(logging.WARNING):
        result = await prebake_retrieval("q", provider=slow)
    assert result == {}
    assert any("timed out" in r.message for r in caplog.records)
    # The slow call must be abandoned (cancelled), not left running.
    assert slow.cancelled is True


async def test_prebake_fast_provider_unaffected_by_timeout(monkeypatch):
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "5")
    atoms = [ContextAtom(key="a", body="aaa", source_path="/a.md", score=0.9)]
    provider = _FakeProvider(atoms=atoms)
    result = await prebake_retrieval("a task", provider=provider, token_budget=2000)
    assert result == {"retrieved_atoms": [a.model_dump() for a in atoms]}
    assert provider.calls == [("a task", None, 2000)]
