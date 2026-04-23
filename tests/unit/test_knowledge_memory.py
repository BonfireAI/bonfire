"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.memory.

Covers ``InMemoryVaultBackend`` per Sage D8.2 type locks and D8.3 test names.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

import pytest

from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultBackend, VaultEntry


def _entry(
    *,
    content: str = "hello",
    entry_type: str = "code_chunk",
    source_path: str = "",
    content_hash: str = "",
) -> VaultEntry:
    return VaultEntry(
        content=content,
        entry_type=entry_type,
        source_path=source_path,
        content_hash=content_hash,
    )


class TestMemoryBackend:
    def test_implements_vault_backend_protocol(self):
        backend = InMemoryVaultBackend()
        assert isinstance(backend, VaultBackend)

    async def test_store_returns_entry_id(self):
        backend = InMemoryVaultBackend()
        entry = _entry()
        result = await backend.store(entry)
        assert result == entry.entry_id

    async def test_store_computes_content_hash_when_missing(self):
        backend = InMemoryVaultBackend()
        entry = _entry(content="hash me please", content_hash="")
        await backend.store(entry)
        stored = backend._entries[0]
        assert stored.content_hash != ""
        assert len(stored.content_hash) == 64

    async def test_query_substring_match_scores_by_word_count(self):
        backend = InMemoryVaultBackend()
        await backend.store(_entry(content="foo bar baz"))
        await backend.store(_entry(content="foo only"))
        await backend.store(_entry(content="nothing at all"))
        results = await backend.query("foo bar", limit=5)
        assert len(results) >= 1
        assert any("foo bar" in r.content for r in results)
        # Higher-overlap entry ranks first.
        assert "foo bar" in results[0].content

    async def test_query_filters_by_entry_type(self):
        backend = InMemoryVaultBackend()
        await backend.store(_entry(content="alpha", entry_type="code_chunk"))
        await backend.store(_entry(content="alpha", entry_type="decision_record"))
        results = await backend.query("alpha", entry_type="decision_record")
        assert len(results) == 1
        assert results[0].entry_type == "decision_record"

    async def test_query_limits_results(self):
        backend = InMemoryVaultBackend()
        for i in range(5):
            await backend.store(_entry(content=f"match token {i}"))
        results = await backend.query("match", limit=2)
        assert len(results) <= 2

    async def test_exists_returns_true_after_store(self):
        backend = InMemoryVaultBackend()
        entry = _entry(content="exists-check", content_hash="abc123")
        await backend.store(entry)
        assert await backend.exists("abc123") is True

    async def test_exists_returns_false_for_unknown_hash(self):
        backend = InMemoryVaultBackend()
        assert await backend.exists("nonexistent-hash") is False

    async def test_get_by_source_returns_all_matching(self):
        backend = InMemoryVaultBackend()
        await backend.store(_entry(content="a", source_path="/path/one.md"))
        await backend.store(_entry(content="b", source_path="/path/one.md"))
        await backend.store(_entry(content="c", source_path="/path/two.md"))
        results = await backend.get_by_source("/path/one.md")
        assert len(results) == 2
        assert all(r.source_path == "/path/one.md" for r in results)
