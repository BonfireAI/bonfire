# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract tests for the stdlib-``sqlite3`` persistent vault backend.

Mirrors the in-memory backend's contract (store -> exists -> query ->
get_by_source, content_hash dedup, entry_id round-trip) and adds the property
the in-memory backend cannot have: **persistence across reopening the same
file path**. No third-party dependencies -- this backend is the one that runs
in CI where the LanceDB vector deps are absent.

Async tests auto-discover (``asyncio_mode = "auto"``); no marker needed.
Implementation NEVER edits this file.
"""

from __future__ import annotations

from bonfire.knowledge import get_vault_backend
from bonfire.knowledge.hasher import content_hash as compute_hash
from bonfire.knowledge.sqlite_backend import SqliteVaultBackend
from bonfire.protocols import VaultBackend, VaultEntry


def _entry(content: str, **overrides: object) -> VaultEntry:
    """Build a VaultEntry with a default entry_type, overridable per call."""
    data: dict[str, object] = {"content": content, "entry_type": "code_chunk"}
    data.update(overrides)
    return VaultEntry(**data)


class TestProtocolConformance:
    def test_satisfies_vault_backend_protocol(self) -> None:
        backend = SqliteVaultBackend()
        assert isinstance(backend, VaultBackend)


class TestStoreAndExists:
    async def test_store_returns_entry_id(self) -> None:
        backend = SqliteVaultBackend()
        entry = _entry("hello world")
        returned = await backend.store(entry)
        assert returned == entry.entry_id

    async def test_store_computes_content_hash_when_absent(self) -> None:
        backend = SqliteVaultBackend()
        entry = _entry("compute my hash")
        assert entry.content_hash == ""
        await backend.store(entry)
        assert await backend.exists(compute_hash("compute my hash")) is True

    async def test_store_preserves_supplied_content_hash(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("payload", content_hash="explicit-hash"))
        assert await backend.exists("explicit-hash") is True

    async def test_exists_false_for_unknown_hash(self) -> None:
        backend = SqliteVaultBackend()
        assert await backend.exists("never-stored") is False


class TestRoundTrip:
    async def test_query_returns_full_entry(self) -> None:
        backend = SqliteVaultBackend()
        original = _entry(
            "alpha beta gamma",
            source_path="src/foo.py",
            project_name="proj",
            scanned_at="2026-06-29",
            git_hash="deadbeef",
            tags=["a", "b"],
            metadata={"k": "v", "n": 1},
        )
        await backend.store(original)
        results = await backend.query("alpha")
        assert len(results) == 1
        got = results[0]
        assert got.entry_id == original.entry_id
        assert got.content == "alpha beta gamma"
        assert got.entry_type == "code_chunk"
        assert got.source_path == "src/foo.py"
        assert got.project_name == "proj"
        assert got.scanned_at == "2026-06-29"
        assert got.git_hash == "deadbeef"
        assert got.tags == ["a", "b"]
        assert got.metadata == {"k": "v", "n": 1}


class TestQuery:
    async def test_query_substring_match(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("the quick brown fox"))
        await backend.store(_entry("a lazy dog sleeps"))
        results = await backend.query("quick")
        assert len(results) == 1
        assert results[0].content == "the quick brown fox"

    async def test_query_is_case_insensitive(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("UPPER CASE CONTENT"))
        results = await backend.query("upper")
        assert len(results) == 1

    async def test_query_no_match_returns_empty(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("hello world"))
        assert await backend.query("absent") == []

    async def test_query_empty_string_returns_empty(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("hello world"))
        assert await backend.query("   ") == []

    async def test_query_respects_limit(self) -> None:
        backend = SqliteVaultBackend()
        for i in range(10):
            await backend.store(_entry(f"shared token entry {i}"))
        results = await backend.query("shared", limit=3)
        assert len(results) == 3

    async def test_query_filters_by_entry_type(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("token here", entry_type="code_chunk"))
        await backend.store(_entry("token there", entry_type="scout_report"))
        results = await backend.query("token", entry_type="scout_report")
        assert len(results) == 1
        assert results[0].entry_type == "scout_report"

    async def test_query_ranks_more_word_hits_first(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("alpha only here", content_hash="one"))
        await backend.store(_entry("alpha and beta both", content_hash="two"))
        results = await backend.query("alpha beta")
        assert results[0].content == "alpha and beta both"


class TestGetBySource:
    async def test_get_by_source_returns_matching(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("a", source_path="src/x.py", content_hash="ha"))
        await backend.store(_entry("b", source_path="src/x.py", content_hash="hb"))
        await backend.store(_entry("c", source_path="src/y.py", content_hash="hc"))
        results = await backend.get_by_source("src/x.py")
        assert len(results) == 2
        assert {r.content for r in results} == {"a", "b"}

    async def test_get_by_source_empty_when_none(self) -> None:
        backend = SqliteVaultBackend()
        assert await backend.get_by_source("src/missing.py") == []


class TestDedupByContentHash:
    async def test_distinct_hashes_both_exist(self) -> None:
        backend = SqliteVaultBackend()
        await backend.store(_entry("first", content_hash="h1"))
        await backend.store(_entry("second", content_hash="h2"))
        assert await backend.exists("h1") is True
        assert await backend.exists("h2") is True

    async def test_exists_drives_ingest_dedup(self) -> None:
        """The ingest pattern: skip store when exists() reports the hash."""
        backend = SqliteVaultBackend()
        c_hash = compute_hash("dedup me")
        entry = _entry("dedup me")
        if not await backend.exists(c_hash):
            await backend.store(entry)
        # Second pass: hash now present, so ingest skips the store.
        would_store_again = not await backend.exists(c_hash)
        assert would_store_again is False
        # Exactly one row landed despite two ingest passes.
        assert len(await backend.query("dedup")) == 1


class TestPersistenceAcrossReopen:
    async def test_data_survives_reopening_same_file(self, tmp_path) -> None:
        """Write through one connection, reopen the SAME path, read it back.

        This is the property the in-memory backend cannot provide and the
        reason this backend exists: durable storage on disk.
        """
        db_file = str(tmp_path / "vault.db")

        writer = SqliteVaultBackend(db_path=db_file)
        entry = _entry(
            "persistent payload token",
            source_path="src/persist.py",
            content_hash="persist-hash",
            tags=["keep"],
            metadata={"durable": True},
        )
        await writer.store(entry)

        # A fresh backend over the same file path must see the prior write.
        reader = SqliteVaultBackend(db_path=db_file)
        assert await reader.exists("persist-hash") is True
        by_source = await reader.get_by_source("src/persist.py")
        assert len(by_source) == 1
        restored = by_source[0]
        assert restored.entry_id == entry.entry_id
        assert restored.content == "persistent payload token"
        assert restored.tags == ["keep"]
        assert restored.metadata == {"durable": True}

        hits = await reader.query("persistent")
        assert len(hits) == 1
        assert hits[0].entry_id == entry.entry_id

    async def test_reopen_does_not_duplicate_schema(self, tmp_path) -> None:
        """Reopening repeatedly is idempotent; data accumulates correctly."""
        db_file = str(tmp_path / "vault.db")
        first = SqliteVaultBackend(db_path=db_file)
        await first.store(_entry("one", content_hash="k1"))
        second = SqliteVaultBackend(db_path=db_file)
        await second.store(_entry("two", content_hash="k2"))
        third = SqliteVaultBackend(db_path=db_file)
        assert await third.exists("k1") is True
        assert await third.exists("k2") is True


class TestUpsertByEntryId:
    async def test_restoring_same_entry_id_replaces_row(self, tmp_path) -> None:
        backend = SqliteVaultBackend()
        first = _entry("original", entry_id="fixed-id", content_hash="orig")
        await backend.store(first)
        second = _entry("updated", entry_id="fixed-id", content_hash="upd")
        await backend.store(second)
        # Same id => single row; latest content wins.
        results = await backend.query("updated")
        assert len(results) == 1
        assert results[0].entry_id == "fixed-id"
        assert await backend.query("original") == []


class TestFactoryWiring:
    def test_factory_returns_sqlite_backend(self) -> None:
        backend = get_vault_backend(backend="sqlite", vault_path=":memory:")
        assert isinstance(backend, SqliteVaultBackend)

    def test_factory_memory_still_default(self) -> None:
        backend = get_vault_backend()
        assert not isinstance(backend, SqliteVaultBackend)

    async def test_factory_sqlite_persists_to_path(self, tmp_path) -> None:
        db_file = str(tmp_path / "factory.db")
        writer = get_vault_backend(backend="sqlite", vault_path=db_file)
        await writer.store(_entry("via factory", content_hash="fac"))
        reader = get_vault_backend(backend="sqlite", vault_path=db_file)
        assert await reader.exists("fac") is True
