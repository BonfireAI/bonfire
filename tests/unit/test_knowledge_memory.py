"""RED tests — BON-341 W5.2 — `bonfire.knowledge.memory.InMemoryVaultBackend`.

Innovative lens. Sage D8.2 locks the full protocol surface:

- ``__init__(self) -> None``
- ``_entries: list[VaultEntry]`` (typed instance attribute).
- ``async def store(self, entry: VaultEntry) -> str`` — returns entry_id.
- ``async def query(self, query: str, *, limit: int = 5, entry_type: str | None = None) -> list[VaultEntry]``
- ``async def exists(self, content_hash: str) -> bool``
- ``async def get_by_source(self, source_path: str) -> list[VaultEntry]``

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import pytest

from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultBackend, VaultEntry


class TestProtocolConformance:
    """Sage D8.3: test_implements_vault_backend_protocol."""

    def test_implements_vault_backend_protocol(self) -> None:
        """InMemoryVaultBackend satisfies the VaultBackend @runtime_checkable protocol."""
        backend = InMemoryVaultBackend()
        assert isinstance(backend, VaultBackend)

    # knight-a(innovative): split-from-protocol — instance attribute typed.
    def test_new_backend_has_empty_entries_list(self) -> None:
        """Freshly constructed backend has no stored entries."""
        backend = InMemoryVaultBackend()
        assert backend._entries == []
        assert isinstance(backend._entries, list)


class TestStore:
    """Storage semantics. Multiple narrow tests (innovative split)."""

    async def test_store_returns_entry_id(self) -> None:
        """store() returns the entry's entry_id (string)."""
        backend = InMemoryVaultBackend()
        entry = VaultEntry(content="alpha", entry_type="code_chunk", content_hash="h1")
        returned = await backend.store(entry)
        assert returned == entry.entry_id

    async def test_store_appends_to_entries(self) -> None:
        """store() appends to ._entries list."""
        backend = InMemoryVaultBackend()
        entry = VaultEntry(content="x", entry_type="code_chunk", content_hash="h")
        await backend.store(entry)
        assert len(backend._entries) == 1

    async def test_store_computes_content_hash_when_missing(self) -> None:
        """Empty content_hash on entry -> backend computes via knowledge.hasher."""
        backend = InMemoryVaultBackend()
        # Construct entry with no content_hash — backend must compute.
        entry = VaultEntry(content="needs-hashing", entry_type="code_chunk")
        assert entry.content_hash == ""  # Pydantic default
        await backend.store(entry)
        stored = backend._entries[0]
        assert stored.content_hash != "", "backend must compute hash when absent"
        # Must match knowledge.hasher output.
        from bonfire.knowledge.hasher import content_hash

        assert stored.content_hash == content_hash("needs-hashing")

    # knight-a(innovative): edge — pre-supplied hash is preserved (no overwrite).
    async def test_store_preserves_existing_content_hash(self) -> None:
        """If entry already has content_hash, backend must NOT overwrite it."""
        backend = InMemoryVaultBackend()
        entry = VaultEntry(
            content="payload",
            entry_type="code_chunk",
            content_hash="explicit-hash-value",
        )
        await backend.store(entry)
        assert backend._entries[0].content_hash == "explicit-hash-value"


class TestQuery:
    """Query semantics — substring match with word-count scoring."""

    async def test_query_substring_match_scores_by_word_count(self) -> None:
        """Entries containing more query words score higher and come first."""
        backend = InMemoryVaultBackend()
        await backend.store(
            VaultEntry(
                content="alpha beta", entry_type="code_chunk", content_hash="a"
            )
        )
        await backend.store(
            VaultEntry(
                content="alpha beta gamma", entry_type="code_chunk", content_hash="b"
            )
        )
        await backend.store(
            VaultEntry(content="unrelated", entry_type="code_chunk", content_hash="c")
        )
        results = await backend.query("alpha beta gamma")
        assert len(results) == 2
        # Higher word-count match comes first.
        assert results[0].content == "alpha beta gamma"

    async def test_query_filters_by_entry_type(self) -> None:
        """entry_type kwarg filters results before scoring."""
        backend = InMemoryVaultBackend()
        await backend.store(
            VaultEntry(content="alpha", entry_type="code_chunk", content_hash="a")
        )
        await backend.store(
            VaultEntry(
                content="alpha",
                entry_type="project_manifest",
                content_hash="b",
            )
        )
        results = await backend.query("alpha", entry_type="project_manifest")
        assert len(results) == 1
        assert results[0].entry_type == "project_manifest"

    async def test_query_limits_results(self) -> None:
        """limit=N truncates result list to N items."""
        backend = InMemoryVaultBackend()
        for i in range(10):
            await backend.store(
                VaultEntry(
                    content=f"alpha payload {i}",
                    entry_type="code_chunk",
                    content_hash=f"h{i}",
                )
            )
        results = await backend.query("alpha", limit=3)
        assert len(results) == 3

    # knight-a(innovative): edge — zero matches returns empty list cleanly.
    async def test_query_returns_empty_when_no_match(self) -> None:
        backend = InMemoryVaultBackend()
        await backend.store(
            VaultEntry(content="hello", entry_type="code_chunk", content_hash="h")
        )
        assert await backend.query("zzz") == []


class TestExists:
    """Content-hash existence checks."""

    async def test_exists_returns_true_after_store(self) -> None:
        backend = InMemoryVaultBackend()
        entry = VaultEntry(
            content="payload", entry_type="code_chunk", content_hash="known-hash"
        )
        await backend.store(entry)
        assert await backend.exists("known-hash") is True

    async def test_exists_returns_false_for_unknown_hash(self) -> None:
        backend = InMemoryVaultBackend()
        assert await backend.exists("never-seen") is False

    # knight-a(innovative): empty string edge case.
    async def test_exists_false_for_empty_hash_on_empty_backend(self) -> None:
        backend = InMemoryVaultBackend()
        assert await backend.exists("") is False


class TestGetBySource:
    """Source-path filtering."""

    async def test_get_by_source_returns_all_matching(self) -> None:
        backend = InMemoryVaultBackend()
        await backend.store(
            VaultEntry(
                content="a",
                entry_type="code_chunk",
                content_hash="h1",
                source_path="/src/mod.py",
            )
        )
        await backend.store(
            VaultEntry(
                content="b",
                entry_type="code_chunk",
                content_hash="h2",
                source_path="/src/mod.py",
            )
        )
        await backend.store(
            VaultEntry(
                content="c",
                entry_type="code_chunk",
                content_hash="h3",
                source_path="/src/other.py",
            )
        )
        results = await backend.get_by_source("/src/mod.py")
        assert len(results) == 2
        assert {e.content for e in results} == {"a", "b"}

    # knight-a(innovative): missing source returns empty, not KeyError.
    async def test_get_by_source_returns_empty_for_unknown_path(self) -> None:
        backend = InMemoryVaultBackend()
        assert await backend.get_by_source("/nowhere") == []


class TestConstructorParameterless:
    """Sage D8.2: __init__(self) -> None — no required args."""

    def test_constructor_takes_no_arguments(self) -> None:
        """Constructor must accept no positional/keyword args."""
        backend = InMemoryVaultBackend()
        assert backend is not None

    def test_constructor_rejects_positional_args(self) -> None:
        """Innovative check — constructor should not accept arbitrary positional args."""
        with pytest.raises(TypeError):
            InMemoryVaultBackend("unexpected")  # type: ignore[call-arg]
