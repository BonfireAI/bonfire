"""RED tests — BON-341 W5.2 — `bonfire.knowledge.ingest` (innovative lens).

Sage D8.2 type locks:
- ``async def ingest_markdown(path, *, backend, project_name="", git_hash="") -> int``
- ``async def ingest_session(session_log_path, *, backend, project_name="", git_hash="") -> int``
- ``async def retrieve_context(query, *, backend, limit=5) -> list[VaultEntry]``

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.

Note: Sage locks retrieve_context to return ``list[VaultEntry]`` (NOT a formatted
string). V1 returned a string; Sage D8.2 is canonical and wins — tests assert list.
"""

from __future__ import annotations

import json

from bonfire.knowledge.ingest import ingest_markdown, ingest_session, retrieve_context
from bonfire.knowledge.memory import InMemoryVaultBackend

# ---------------------------------------------------------------------------
# Markdown ingestion
# ---------------------------------------------------------------------------


class TestIngestMarkdown:
    async def test_ingest_markdown_stores_chunks(self, tmp_path) -> None:
        """Markdown file ingests -> chunks stored, count returned."""
        md = tmp_path / "doc.md"
        md.write_text("# Title\n\nBody paragraph.\n\n# Second\n\nMore body.\n")
        backend = InMemoryVaultBackend()
        stored = await ingest_markdown(md, backend=backend)
        assert isinstance(stored, int)
        assert stored >= 1
        assert len(backend._entries) == stored

    async def test_ingest_markdown_dedups_on_rescan(self, tmp_path) -> None:
        """Re-ingesting the same file stores zero new entries."""
        md = tmp_path / "doc.md"
        md.write_text("# Alpha\n\nSome content body.\n")
        backend = InMemoryVaultBackend()
        first = await ingest_markdown(md, backend=backend)
        second = await ingest_markdown(md, backend=backend)
        assert first >= 1
        assert second == 0

    # knight-a(innovative): provenance propagates (project_name + git_hash).
    async def test_ingest_markdown_propagates_provenance(self, tmp_path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("# T\n\nBody.\n")
        backend = InMemoryVaultBackend()
        await ingest_markdown(md, backend=backend, project_name="myproj", git_hash="deadbeef")
        assert backend._entries
        e = backend._entries[0]
        assert e.project_name == "myproj"
        assert e.git_hash == "deadbeef"


# ---------------------------------------------------------------------------
# Markdown ingestion — resilience tier (BON-527)
# ---------------------------------------------------------------------------


class TestIngestMarkdownResilience:
    """Lock the typed-zero contract: missing/empty markdown returns 0, never raises.

    BON-527 re-adds the resilience tests filtered out of BON-341 RED to keep
    that wave at the D8.3 floor. The contract mirrors the backfill missing-dir
    pattern: ``ingest_markdown`` answers an unusable input with ``int`` 0 — not
    an exception, not ``None``.
    """

    async def test_ingest_markdown_missing_file_returns_zero(self, tmp_path) -> None:
        """A path that does not exist ingests to typed-zero, never raises."""
        missing = tmp_path / "does-not-exist.md"
        assert not missing.exists()
        backend = InMemoryVaultBackend()
        stored = await ingest_markdown(missing, backend=backend)
        assert stored == 0
        assert isinstance(stored, int)
        assert stored is not None
        assert backend._entries == []

    async def test_ingest_markdown_empty_file_returns_zero(self, tmp_path) -> None:
        """An empty file (and a whitespace-only file) ingests to typed-zero."""
        empty = tmp_path / "empty.md"
        empty.write_text("")
        backend = InMemoryVaultBackend()
        stored = await ingest_markdown(empty, backend=backend)
        assert stored == 0
        assert isinstance(stored, int)
        assert backend._entries == []

        whitespace = tmp_path / "whitespace.md"
        whitespace.write_text("   \n\t\n   \n")
        whitespace_stored = await ingest_markdown(whitespace, backend=backend)
        assert whitespace_stored == 0
        assert backend._entries == []

    async def test_ingest_markdown_directory_path_returns_zero(self, tmp_path) -> None:
        """A directory passed where a file is expected returns 0, never raises.

        ``is_file()`` is False for a directory, so the same typed-zero guard
        protects against this OSError-prone input.
        """
        backend = InMemoryVaultBackend()
        stored = await ingest_markdown(tmp_path, backend=backend)
        assert stored == 0
        assert backend._entries == []


# ---------------------------------------------------------------------------
# Session ingestion
# ---------------------------------------------------------------------------


class TestIngestSession:
    async def test_ingest_session_stores_session_log(self, tmp_path) -> None:
        """JSONL session log ingests -> events become VaultEntries."""
        log = tmp_path / "session.jsonl"
        events = [
            {
                "event_type": "dispatch.completed",
                "agent_id": "knight",
                "task": "test",
                "result_summary": "ok",
            },
            {
                "event_type": "session.ended",
                "status": "completed",
                "dispatch_count": 3,
                "total_cost_usd": 1.25,
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        backend = InMemoryVaultBackend()
        stored = await ingest_session(log, backend=backend)
        assert isinstance(stored, int)
        assert stored >= 1

    # knight-a(innovative): dedup across session ingestions.
    async def test_ingest_session_dedups_on_rescan(self, tmp_path) -> None:
        log = tmp_path / "session.jsonl"
        log.write_text(
            json.dumps(
                {
                    "event_type": "dispatch.completed",
                    "agent_id": "knight",
                    "task": "T",
                    "result_summary": "ok",
                }
            )
            + "\n"
        )
        backend = InMemoryVaultBackend()
        first = await ingest_session(log, backend=backend)
        second = await ingest_session(log, backend=backend)
        assert first >= 1
        assert second == 0


# ---------------------------------------------------------------------------
# Session ingestion — resilience tier (BON-527)
# ---------------------------------------------------------------------------


class TestIngestSessionResilience:
    """Lock the typed-zero contract: missing/empty session log returns 0, never raises."""

    async def test_ingest_session_missing_file_returns_zero(self, tmp_path) -> None:
        """A session-log path that does not exist ingests to typed-zero."""
        missing = tmp_path / "no-such-session.jsonl"
        assert not missing.exists()
        backend = InMemoryVaultBackend()
        stored = await ingest_session(missing, backend=backend)
        assert stored == 0
        assert isinstance(stored, int)
        assert stored is not None
        assert backend._entries == []

    async def test_ingest_session_empty_file_returns_zero(self, tmp_path) -> None:
        """An empty (and a blank-line-only) session log ingests to typed-zero."""
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        backend = InMemoryVaultBackend()
        stored = await ingest_session(empty, backend=backend)
        assert stored == 0
        assert isinstance(stored, int)
        assert backend._entries == []

        blank = tmp_path / "blank.jsonl"
        blank.write_text("\n\n   \n")
        blank_stored = await ingest_session(blank, backend=backend)
        assert blank_stored == 0
        assert backend._entries == []


# ---------------------------------------------------------------------------
# Retrieve context — Sage locks return type to list[VaultEntry]
# ---------------------------------------------------------------------------


class TestRetrieveContext:
    async def test_retrieve_context_delegates_to_backend_query(self) -> None:
        """retrieve_context calls backend.query with the provided string."""
        captured: dict = {}

        class SpyBackend:
            async def query(
                self, query: str, *, limit: int = 5, entry_type: str | None = None
            ) -> list:
                captured["query"] = query
                captured["limit"] = limit
                return []

            async def store(self, entry) -> str:
                return ""

            async def exists(self, content_hash: str) -> bool:
                return False

            async def get_by_source(self, source_path: str) -> list:
                return []

        backend = SpyBackend()
        await retrieve_context("alpha beta", backend=backend)
        assert captured["query"] == "alpha beta"

    async def test_retrieve_context_respects_limit(self) -> None:
        """limit kwarg flows to backend.query."""
        captured_limits: list[int] = []

        class LimitSpy:
            async def query(
                self, query: str, *, limit: int = 5, entry_type: str | None = None
            ) -> list:
                captured_limits.append(limit)
                return []

            async def store(self, entry) -> str:
                return ""

            async def exists(self, content_hash: str) -> bool:
                return False

            async def get_by_source(self, source_path: str) -> list:
                return []

        backend = LimitSpy()
        await retrieve_context("q", backend=backend, limit=3)
        assert 3 in captured_limits

    # knight-a(innovative): empty backend -> empty list (not None, not "").
    async def test_retrieve_context_empty_backend_returns_empty_list(self) -> None:
        backend = InMemoryVaultBackend()
        result = await retrieve_context("anything", backend=backend)
        assert result == []
