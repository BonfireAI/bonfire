"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.backfill.

Covers ``backfill_sessions``, ``backfill_memory``, ``backfill_all`` per
Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

from pathlib import Path

from bonfire.knowledge.backfill import backfill_all, backfill_memory, backfill_sessions
from bonfire.knowledge.memory import InMemoryVaultBackend


class TestBackfillSessions:
    async def test_backfill_sessions_counts_stored_entries(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "s1.md").write_text("# S1\nbody\n")
        (sessions_dir / "s2.md").write_text("# S2\nother body\n")
        backend = InMemoryVaultBackend()
        count = await backfill_sessions(sessions_dir, backend=backend)
        assert count >= 2

    async def test_backfill_sessions_returns_zero_for_empty_dir(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        backend = InMemoryVaultBackend()
        count = await backfill_sessions(empty_dir, backend=backend)
        assert count == 0


class TestBackfillMemory:
    async def test_backfill_memory_counts_stored_entries(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "m1.md").write_text("# Memo\ncontent one\n")
        (memory_dir / "m2.md").write_text("# Memo\ncontent two\n")
        backend = InMemoryVaultBackend()
        count = await backfill_memory(memory_dir, backend=backend)
        assert count >= 2


class TestBackfillAll:
    async def test_backfill_all_returns_sessions_and_memory_keys(self, tmp_path: Path):
        sessions = tmp_path / "sessions"
        memory = tmp_path / "memory"
        sessions.mkdir()
        memory.mkdir()
        (sessions / "s.md").write_text("# S\nbody\n")
        (memory / "m.md").write_text("# M\nbody\n")
        backend = InMemoryVaultBackend()
        result = await backfill_all(tmp_path, backend=backend)
        assert set(result.keys()) == {"sessions", "memory"}
        assert isinstance(result["sessions"], int)
        assert isinstance(result["memory"], int)
