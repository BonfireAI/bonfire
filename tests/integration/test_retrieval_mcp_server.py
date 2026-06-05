# SPDX-License-Identifier: Apache-2.0
"""Integration smoke for the bonfire-public retrieval MCP server.

Tests the tool's handler directly. End-to-end stdio coverage — a subprocess
smoke that spawns the server and exchanges JSON-RPC frames — is not exercised
here; the handler is the unit under test.
"""

from __future__ import annotations

from bonfire.mcp.retrieval_server import handle_retrieve_context
from bonfire.protocols import ContextAtom


class _FakeProvider:
    def __init__(self, atoms: list[ContextAtom]) -> None:
        self._atoms = atoms

    async def retrieve(self, *, query, seed_keys=None, token_budget=4000):
        return self._atoms


async def test_handle_retrieve_context_returns_formatted_block_with_atoms():
    provider = _FakeProvider(
        atoms=[
            ContextAtom(
                key="lexicon-is-the-knowledge-store",
                body="The Lexicon IS memory.",
                source_path="/p/atom.md",
                score=0.9,
            ),
        ]
    )
    out = await handle_retrieve_context(
        query="lexicon",
        token_budget=4000,
        provider=provider,
    )
    assert "lexicon-is-the-knowledge-store" in out
    assert "The Lexicon IS memory." in out
    assert "/p/atom.md" in out


async def test_handle_retrieve_context_returns_empty_block_on_no_hits():
    provider = _FakeProvider(atoms=[])
    out = await handle_retrieve_context(
        query="zzz",
        token_budget=4000,
        provider=provider,
    )
    assert isinstance(out, str)
    assert "no atoms" in out.lower() or "0 atoms" in out.lower()


async def test_handle_retrieve_context_uses_discovery_when_provider_none():
    """When provider is None, the handler discovers via _discovery."""
    from bonfire import _discovery

    _discovery.discover_retrieval_provider.cache_clear()
    try:
        out = await handle_retrieve_context(query="anything", token_budget=4000)
        # Either Tier 1 (RipgrepRetrievalProvider with empty default backend)
        # or Tier 2 if installed. We only assert that no exception is raised
        # and we get a string back.
        assert isinstance(out, str)
    finally:
        _discovery.discover_retrieval_provider.cache_clear()
