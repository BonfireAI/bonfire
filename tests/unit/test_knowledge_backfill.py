"""RED tests — BON-341 W5.2 — `bonfire.knowledge.backfill` (innovative lens).

Sage D8.2 type locks:
- ``async def backfill_sessions(sessions_dir, *, backend, project_name="") -> int``
- ``async def backfill_memory(memory_dir, *, backend, project_name="") -> int``
- ``async def backfill_all(root, *, backend, project_name="") -> dict[str, int]``
  LOCKED keys: ``{"sessions": int, "memory": int}``.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.

Note: Sage D8.2 canonicalizes the signatures (keyword-only backend/project_name,
int returns, backfill_all -> dict[str, int]). V1's signatures differed; Sage wins.
"""

from __future__ import annotations

import pytest

from bonfire.knowledge.backfill import backfill_all, backfill_memory, backfill_sessions
from bonfire.knowledge.memory import InMemoryVaultBackend


# ---------------------------------------------------------------------------
# backfill_sessions
# ---------------------------------------------------------------------------


class TestBackfillSessions:
    async def test_backfill_sessions_counts_stored_entries(self, tmp_path) -> None:
        """Ingests handoff files and returns count of new entries."""
        (tmp_path / "s001-handoff.md").write_text("# Session 1\n\nWork done here.\n")
        (tmp_path / "s002-handoff.md").write_text("# Session 2\n\nMore work.\n")
        backend = InMemoryVaultBackend()
        result = await backfill_sessions(tmp_path, backend=backend)
        assert isinstance(result, int)
        assert result >= 2

    async def test_backfill_sessions_returns_zero_for_empty_dir(self, tmp_path) -> None:
        backend = InMemoryVaultBackend()
        result = await backfill_sessions(tmp_path, backend=backend)
        assert result == 0

    # knight-a(innovative): missing directory returns 0 cleanly, no crash.
    async def test_backfill_sessions_missing_dir_returns_zero(self, tmp_path) -> None:
        backend = InMemoryVaultBackend()
        result = await backfill_sessions(tmp_path / "nope", backend=backend)
        assert result == 0


# ---------------------------------------------------------------------------
# backfill_memory
# ---------------------------------------------------------------------------


class TestBackfillMemory:
    async def test_backfill_memory_counts_stored_entries(self, tmp_path) -> None:
        (tmp_path / "note1.md").write_text("# Note 1\n\nSomething.\n")
        (tmp_path / "note2.md").write_text("# Note 2\n\nElse.\n")
        backend = InMemoryVaultBackend()
        result = await backfill_memory(tmp_path, backend=backend)
        assert isinstance(result, int)
        assert result >= 2

    # knight-a(innovative): non-md files ignored.
    async def test_backfill_memory_ignores_non_markdown(self, tmp_path) -> None:
        (tmp_path / "note.md").write_text("# N\n\nContent.\n")
        (tmp_path / "secret.env").write_text("SECRET=x")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        backend = InMemoryVaultBackend()
        result = await backfill_memory(tmp_path, backend=backend)
        # Only .md should be ingested.
        assert result >= 1
        for e in backend._entries:
            assert "secret.env" not in e.source_path
            assert "image.png" not in e.source_path


# ---------------------------------------------------------------------------
# backfill_all
# ---------------------------------------------------------------------------


class TestBackfillAll:
    async def test_backfill_all_returns_sessions_and_memory_keys(self, tmp_path) -> None:
        """LOCKED keys: {"sessions": int, "memory": int}."""
        sessions = tmp_path / "sessions"
        memory = tmp_path / "memory"
        sessions.mkdir()
        memory.mkdir()
        (sessions / "s001-handoff.md").write_text("# S1\n\nBody.\n")
        (memory / "note.md").write_text("# N\n\nContent.\n")
        backend = InMemoryVaultBackend()
        # backfill_all takes a single root (Sage D8.2: root arg).
        result = await backfill_all(tmp_path, backend=backend)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"sessions", "memory"}
        assert isinstance(result["sessions"], int)
        assert isinstance(result["memory"], int)

    # knight-a(innovative): counts are non-negative.
    async def test_backfill_all_counts_are_non_negative(self, tmp_path) -> None:
        backend = InMemoryVaultBackend()
        result = await backfill_all(tmp_path, backend=backend)
        assert result["sessions"] >= 0
        assert result["memory"] >= 0
