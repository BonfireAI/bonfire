# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Performance tests — InMemoryVaultBackend (linear ingest).

The in-memory backend ships as the default when knowledge is unconfigured —
its docstring says "for testing" but the factory returns it for the bare
``enabled=False`` and ``backend="memory"`` paths. Production users hit it
unless they explicitly opt into LanceDB.

A naive implementation would be:

- ``exists(content_hash)`` as ``any(e.content_hash == hash for e in self._entries)``
  — a linear scan over the entire entries list per call.
- ``query(...)`` allocating a fresh ``e.content.lower()`` per entry per call —
  hot-path string allocation that grows linearly with vault size.

The ingest paths (``KnowledgeIngestConsumer._store``, the various
``knowledge.ingest`` entry points, ``TechScanner.scan_and_store``) ALL call
``exists()`` before ``store()``. Stacked together, the naive shape ingests
N entries via N linear-scan exists checks ⇒ **O(N²) ingest** for an
"in-memory backend marked for testing" that's actually the shipping default.

This module pins:

1. **Wall-clock cap on 10,000-entry ingest.** Linear behavior should complete
   well under 1 second; the quadratic shape takes 10s+ on this CPU. The test
   asserts < 1.0 s with the standard ``exists``-then-``store`` guard pattern
   that production callers use.

2. **Correctness regression guards** ensuring the indexed implementation does
   not break the existing semantics already pinned by
   ``test_knowledge_memory.py``. Specifically: the ``_entries`` list MUST
   still grow on every ``store()`` even when ``content_hash`` collides with
   a previously-stored entry — the existing
   ``test_store_appends_to_entries`` contract requires append-on-every-store,
   not dedup-on-hash.

The shipped implementation holds both performance properties:

- ``_hash_set: set[str]`` gives O(1) ``exists()``.
- ``_lower_cache: list[str]`` (parallel to ``_entries``, filled lazily once
  per entry) lets ``query()`` reuse pre-lowered content instead of calling
  ``e.content.lower()`` per entry per call.
- ``_entries: list[VaultEntry]`` stays the public attribute — the conformance
  test in ``test_knowledge_memory.py`` asserts ``backend._entries == []`` and
  ``isinstance(backend._entries, list)`` directly.
"""

from __future__ import annotations

import time

from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultEntry


class TestIngestScalesLinearly:
    """Ingest of 10k entries completes in < 1 s.

    Models the production-default ingest path: every entry is ``exists()``-
    checked before ``store()`` (mirroring ``KnowledgeIngestConsumer._store``,
    ``knowledge.ingest.ingest_*``, and ``TechScanner.scan_and_store`` — the
    callers that guard a store with an exists-check).
    """

    async def test_10k_entry_ingest_under_one_second(self) -> None:
        """Pre-fix: ~10s+ (quadratic). Post-fix: well under 1s (linear).

        The wall-clock cap is generous on purpose — the post-fix shape is
        dominated by Python attribute access + Pydantic instantiation, NOT
        by the dedup index. A 10x margin over expected wall-clock time
        keeps the test stable across CPUs and CI runners.
        """
        backend = InMemoryVaultBackend()
        n = 10_000

        # Pre-construct entries so the loop measures *backend operations*, not
        # Pydantic instantiation. Use distinct content + distinct hash so
        # exists() always returns False and store() always fires (worst case
        # for the quadratic shape).
        entries = [
            VaultEntry(
                content=f"entry content body {i}",
                entry_type="code_chunk",
                content_hash=f"hash-{i:08d}",
            )
            for i in range(n)
        ]

        start = time.perf_counter()
        for entry in entries:
            # Production guard pattern: exists-check then store-on-miss.
            if not await backend.exists(entry.content_hash):
                await backend.store(entry)
        elapsed = time.perf_counter() - start

        # Confirm we actually stored everything (sanity guard against the
        # exists/store contract drifting).
        assert len(backend._entries) == n

        # Linear cap: the post-fix shape is O(N); quadratic pre-fix would
        # take ~10s+ for N=10_000 on this CPU.
        assert elapsed < 1.0, (
            f"10k-entry ingest took {elapsed:.3f}s — expected sub-second under "
            "the linear-time fix; the pre-fix quadratic shape takes 10s+"
        )

    async def test_query_with_large_vault_does_not_allocate_per_entry_lower(
        self,
    ) -> None:
        """Naive: query() does e.content.lower() per entry per call.

        Indexed: lowercase is cached once per entry (the parallel
        ``_lower_cache``, filled lazily on first query). Verifies the
        property by timing 100 queries over a 5k-entry vault — naive this is
        ~5s+; indexed it should be sub-second.
        """
        backend = InMemoryVaultBackend()
        n = 5_000
        for i in range(n):
            await backend.store(
                VaultEntry(
                    content=f"content body number {i} alpha beta gamma",
                    entry_type="code_chunk",
                    content_hash=f"hash-{i:08d}",
                )
            )

        start = time.perf_counter()
        for _ in range(100):
            results = await backend.query("alpha beta gamma", limit=10)
            assert len(results) == 10
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, (
            f"100 queries over 5k-entry vault took {elapsed:.3f}s — expected "
            "sub-second with lower-cache; pre-fix per-entry .lower() takes 5s+"
        )


class TestPerfFixPreservesCorrectness:
    """Regression guards — the perf fix must NOT break existing semantics."""

    async def test_entries_list_grows_on_every_store_even_with_hash_collision(
        self,
    ) -> None:
        """``_entries`` list appends on every store, regardless of hash dedup.

        Test contract from ``test_knowledge_memory.py::test_store_appends_to_entries``:
        a single store yields ``len(_entries) == 1``. By extension, two stores
        yield ``len(_entries) == 2`` even when both share a content_hash —
        the in-memory backend does NOT dedup on store; only ``exists()`` is
        the contract for "have we seen this hash."
        """
        backend = InMemoryVaultBackend()
        e1 = VaultEntry(content="same body", entry_type="code_chunk", content_hash="dup-hash")
        e2 = VaultEntry(content="same body", entry_type="code_chunk", content_hash="dup-hash")
        await backend.store(e1)
        await backend.store(e2)
        assert len(backend._entries) == 2, (
            "perf fix must not silently dedup on store — _entries grows on every store"
        )

    async def test_exists_returns_true_for_any_stored_hash(self) -> None:
        """O(1) exists check returns True for hashes from any prior store."""
        backend = InMemoryVaultBackend()
        for i in range(50):
            await backend.store(
                VaultEntry(
                    content=f"c{i}",
                    entry_type="code_chunk",
                    content_hash=f"h-{i}",
                )
            )
        for i in range(50):
            assert await backend.exists(f"h-{i}") is True
        assert await backend.exists("h-not-stored") is False

    async def test_query_lower_cache_handles_uppercase_content(self) -> None:
        """Cached lowercase must match query.lower() — Unicode-safe."""
        backend = InMemoryVaultBackend()
        await backend.store(
            VaultEntry(
                content="ALPHA Beta Gamma",
                entry_type="code_chunk",
                content_hash="upper-1",
            )
        )
        # Query is lowercase — must still find the uppercase-stored entry.
        results = await backend.query("alpha beta")
        assert len(results) == 1
        assert results[0].content == "ALPHA Beta Gamma"
