"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.ingest.

Covers ``ingest_markdown``, ``ingest_session``, ``retrieve_context`` per
Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

from pathlib import Path

from bonfire.knowledge.ingest import (
    ingest_markdown,
    ingest_session,
    retrieve_context,
)
from bonfire.knowledge.memory import InMemoryVaultBackend


class TestIngestMarkdown:
    async def test_ingest_markdown_stores_chunks(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text("# Heading\nbody content\n")
        backend = InMemoryVaultBackend()
        count = await ingest_markdown(md, backend=backend, project_name="test")
        assert count >= 1
        assert len(backend._entries) >= 1

    async def test_ingest_markdown_dedups_on_rescan(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text("# Heading\nbody content\n")
        backend = InMemoryVaultBackend()
        first = await ingest_markdown(md, backend=backend, project_name="test")
        assert first >= 1
        # Second call should skip all entries (content hashes unchanged).
        second = await ingest_markdown(md, backend=backend, project_name="test")
        assert second == 0


class TestIngestSession:
    async def test_ingest_session_stores_session_log(self, tmp_path: Path):
        log = tmp_path / "session.md"
        log.write_text("# Session\nsome events\n")
        backend = InMemoryVaultBackend()
        count = await ingest_session(log, backend=backend, project_name="test")
        assert count >= 1


class TestRetrieveContext:
    async def test_retrieve_context_delegates_to_backend_query(self):
        backend = InMemoryVaultBackend()
        from bonfire.protocols import VaultEntry

        await backend.store(
            VaultEntry(
                content="alpha bravo charlie",
                entry_type="code_chunk",
            )
        )
        results = await retrieve_context("alpha", backend=backend)
        assert len(results) >= 1
        assert "alpha" in results[0].content

    async def test_retrieve_context_respects_limit(self):
        backend = InMemoryVaultBackend()
        from bonfire.protocols import VaultEntry

        for i in range(5):
            await backend.store(
                VaultEntry(
                    content=f"token match number {i}",
                    entry_type="code_chunk",
                )
            )
        results = await retrieve_context("token", backend=backend, limit=2)
        assert len(results) <= 2
