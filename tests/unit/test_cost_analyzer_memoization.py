# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight RED tests — CostAnalyzer ledger memoization with mtime invalidation.

``CostAnalyzer`` powers ``bonfire cost``. Pre-fix, every public method
(``cumulative_cost``, ``session_cost``, ``agent_costs``, ``model_costs``,
``all_sessions``, ``all_records``) starts with ``self._read_records()`` —
which opens the file, iterates every line, runs ``json.loads``, AND
Pydantic-validates each record. The default ``cost_summary`` callback
(``bonfire cost`` with no subcommand) calls ``cumulative_cost()`` AND
``all_sessions()`` → **two full passes per command**.

On a long-lived operator's 100k+ line ledger this is a wall-clock pause
every invocation. The fix: memoize ``_read_records()`` on the analyzer
instance with file-mtime invalidation so any number of method calls in
one CLI invocation pay the read cost exactly once. Mtime invalidation
keeps the cache correct across ledger appends made between method calls.

This Knight pins:

- Two back-to-back ``_read_records()`` calls return the EXACT SAME tuple
  (cache hit, no file re-read).
- When the ledger mtime advances (file modified by another writer), the
  next ``_read_records()`` call returns a fresh tuple reflecting the new
  state (cache miss + invalidation).
- The cache survives across multiple aggregation method calls — calling
  ``cumulative_cost()`` then ``all_sessions()`` reads the ledger only once.
- The cache handles the empty-ledger case (file doesn't exist initially,
  then is created — second call should re-read since mtime is now defined).

Out of scope (acceptance criterion #2 in the ticket, deferred to follow-up):

- Skipping Pydantic per-record validation for read-only aggregations
  (raw dict access for ``cumulative_cost`` / ``agent_costs`` / ``model_costs``).
  The memoization alone delivers the headline "one read per CLI invocation"
  performance win; the Pydantic-bypass is a secondary optimization with
  broader code-shape impact (the aggregation methods would need a parallel
  raw-dict path). Filed for a separate PR.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from bonfire.cost.analyzer import CostAnalyzer
from bonfire.cost.models import DispatchRecord, PipelineRecord


def _write_records(path: Path, records: list[DispatchRecord | PipelineRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "cost_ledger.jsonl"


@pytest.fixture
def sample_records() -> list[DispatchRecord | PipelineRecord]:
    return [
        DispatchRecord(
            timestamp=1000.0,
            session_id="ses_001",
            agent_name="scout",
            cost_usd=0.09,
            duration_seconds=20.0,
            model="claude-sonnet-4-6",
        ),
        DispatchRecord(
            timestamp=1001.0,
            session_id="ses_001",
            agent_name="knight",
            cost_usd=0.12,
            duration_seconds=25.0,
            model="claude-sonnet-4-6",
        ),
        PipelineRecord(
            timestamp=1100.0,
            session_id="ses_001",
            total_cost_usd=0.30,
            duration_seconds=120.0,
            stages_completed=3,
        ),
    ]


class TestReadRecordsMemoization:
    """``_read_records()`` caches on first call, returns cached tuple on subsequent calls."""

    def test_back_to_back_calls_return_same_tuple_instance(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """Two ``_read_records()`` calls in a row return the exact same tuple object."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        first = analyzer._read_records()
        second = analyzer._read_records()

        assert first is second, (
            "Pre-fix: each _read_records call re-reads the ledger and returns a "
            "fresh tuple. Post-fix: the second call hits the cache and returns "
            "the same tuple instance — pinned via identity check."
        )

    def test_back_to_back_calls_return_equal_content(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """Cache hit returns identical record content (sanity guard)."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        first_dispatches, first_pipelines = analyzer._read_records()
        second_dispatches, second_pipelines = analyzer._read_records()

        assert len(first_dispatches) == 2
        assert len(first_pipelines) == 1
        # Same identity (cache hit) + same content.
        assert first_dispatches is second_dispatches
        assert first_pipelines is second_pipelines


class TestCacheInvalidatesOnMtimeChange:
    """When the ledger mtime advances, the next call returns a fresh read."""

    def test_cache_invalidates_when_ledger_modified(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """File modification (mtime change) triggers cache invalidation."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        first_dispatches, first_pipelines = analyzer._read_records()
        first_dispatch_count = len(first_dispatches)

        # Sleep briefly to ensure mtime advances on platforms with low-resolution
        # filesystem timestamps; then append a new record.
        time.sleep(0.01)
        new_record = DispatchRecord(
            timestamp=2000.0,
            session_id="ses_002",
            agent_name="warrior",
            cost_usd=0.50,
            duration_seconds=60.0,
            model="claude-opus-4-8",
        )
        _write_records(ledger_path, [*sample_records, new_record])

        # Force a mtime advance to be deterministic across filesystems with
        # second-resolution timestamps (older ext4, NFS, etc.).
        original_mtime = ledger_path.stat().st_mtime
        os.utime(ledger_path, (original_mtime + 1, original_mtime + 1))

        second_dispatches, _ = analyzer._read_records()

        assert len(second_dispatches) == first_dispatch_count + 1, (
            f"Cache invalidation failed: expected {first_dispatch_count + 1} "
            f"dispatches after ledger append; got {len(second_dispatches)}"
        )

    def test_cache_holds_when_ledger_unmodified(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """Two calls with no file changes in between use the cache (same tuple identity)."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        first = analyzer._read_records()
        # No file modification — second call should hit cache.
        second = analyzer._read_records()

        assert first is second


class TestCacheAcrossPublicMethods:
    """Calling multiple aggregation methods reads the ledger only once."""

    def test_cumulative_cost_then_all_sessions_reads_ledger_once(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two consecutive aggregation calls share one underlying read.

        Models the ``cost_summary`` CLI callback shape from the ticket:
        ``bonfire cost`` calls both ``cumulative_cost()`` and
        ``all_sessions()``. Pre-fix: two full ledger reads. Post-fix: one.
        """
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        # Spy on Path.open to count actual file-read invocations.
        open_count = 0
        original_open = Path.open

        def counting_open(self: Path, *args: object, **kwargs: object) -> object:
            nonlocal open_count
            if self == ledger_path:
                open_count += 1
            return original_open(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "open", counting_open)

        # Both aggregation methods — pre-fix: 2 opens; post-fix: 1.
        cumulative = analyzer.cumulative_cost()
        sessions = analyzer.all_sessions()

        assert cumulative == 0.30
        assert len(sessions) == 1
        assert open_count == 1, (
            f"Expected 1 ledger open across cumulative_cost + all_sessions; "
            f"got {open_count}. Pre-fix: each method re-reads."
        )

    def test_cache_survives_all_aggregation_calls(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """All six public methods called in sequence return consistent results.

        Regression guard: the memoization must not change the observable
        result of any public method.
        """
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        cumulative = analyzer.cumulative_cost()
        session = analyzer.session_cost("ses_001")
        agents = analyzer.agent_costs()
        models = analyzer.model_costs()
        all_sessions = analyzer.all_sessions()
        all_recs = analyzer.all_records()

        assert cumulative == 0.30
        assert session is not None
        assert session.session_id == "ses_001"
        assert len(agents) == 2
        assert {a.agent_name for a in agents} == {"scout", "knight"}
        assert len(models) == 1
        assert models[0].model == "claude-sonnet-4-6"
        assert len(all_sessions) == 1
        assert len(all_recs) == 3


class TestCacheInvalidatesOnAtomicReplacement:
    """A same-mtime, different-inode file replacement must bust the cache.

    Atomic file swaps are common in practice: a ``mv``/``rename`` of a freshly
    written temp file over the ledger, or restoring a backup with its original
    timestamp preserved (``cp -p``, ``rsync --times``, archive extraction). In
    all of these the *contents* change but the mtime can land on the exact same
    value the cache last saw — either because the replacement file was written
    in the same filesystem-timestamp tick, or because the writer deliberately
    stamped the old mtime back on. A cache keyed on mtime alone would then serve
    stale cost data forever, silently mis-reporting spend.

    The fix widens the cache key to also carry the inode number (``st_ino``) and
    file size (``st_size``). An atomic replacement allocates a new inode (and
    usually a different size), so the key changes even when the mtime does not,
    and the next read is correctly treated as a cache miss.
    """

    def test_same_mtime_inode_change_busts_cache(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """Replacing the ledger atomically while pinning the old mtime re-reads.

        Simulates ``mv tmp ledger`` (a fresh inode) followed by stamping the
        original mtime back on the new file — the exact shape of a restored
        backup. The mtime is identical to what the cache recorded, so an
        mtime-only key would wrongly hit the cache. The inode differs, so the
        widened key must miss and pick up the new contents.
        """
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        first_dispatches, _ = analyzer._read_records()
        assert len(first_dispatches) == 2

        # Capture the mtime the cache just recorded so we can restore it onto
        # the replacement file, recreating the "same mtime" hazard exactly.
        original_stat = ledger_path.stat()
        original_mtime_ns = original_stat.st_mtime_ns
        original_ino = original_stat.st_ino

        # Build the replacement on a sibling path, then rename it over the
        # ledger. rename() within a directory is atomic and gives the target a
        # new inode — modelling a real backup-restore / temp-swap writer.
        replacement = ledger_path.with_name("cost_ledger.jsonl.new")
        extra_record = DispatchRecord(
            timestamp=3000.0,
            session_id="ses_003",
            agent_name="sage",
            cost_usd=0.77,
            duration_seconds=42.0,
            model="claude-opus-4-8",
        )
        _write_records(replacement, [*sample_records, extra_record])
        os.replace(replacement, ledger_path)

        # Pin the OLD mtime back onto the new inode — the worst case where the
        # mtime gives the cache no signal at all.
        os.utime(ledger_path, ns=(original_mtime_ns, original_mtime_ns))

        replaced_stat = ledger_path.stat()
        assert replaced_stat.st_mtime_ns == original_mtime_ns, (
            "test setup invariant: replacement must carry the original mtime"
        )
        assert replaced_stat.st_ino != original_ino, (
            "test setup invariant: atomic replace must allocate a new inode "
            "(if this fails the filesystem reused the inode and the scenario "
            "cannot be exercised here)"
        )

        second_dispatches, _ = analyzer._read_records()

        assert len(second_dispatches) == 3, (
            "Same-mtime atomic replacement served stale cache: the cache key is "
            "keyed on mtime alone and missed the inode change. Expected the new "
            "3-dispatch ledger; got the stale 2-dispatch cache."
        )

    def test_same_mtime_size_change_busts_cache(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """An in-place truncate/rewrite to a different size with the old mtime re-reads.

        Some writers rewrite a file in place (same inode) but change its length.
        If a low-resolution filesystem or a deliberate ``utime`` leaves the mtime
        unchanged, the size component of the key is the safety net that catches
        the change.
        """
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        first_dispatches, _ = analyzer._read_records()
        assert len(first_dispatches) == 2

        original_stat = ledger_path.stat()
        original_mtime_ns = original_stat.st_mtime_ns
        original_size = original_stat.st_size

        # Rewrite in place with fewer records so the size shrinks, then restore
        # the old mtime. Truncating to a single record changes st_size while
        # leaving st_ino untouched (same path, opened "w").
        _write_records(ledger_path, sample_records[:1])
        os.utime(ledger_path, ns=(original_mtime_ns, original_mtime_ns))

        rewritten_stat = ledger_path.stat()
        assert rewritten_stat.st_mtime_ns == original_mtime_ns, (
            "test setup invariant: rewrite must carry the original mtime"
        )
        assert rewritten_stat.st_size != original_size, (
            "test setup invariant: rewrite must change the file size"
        )

        second_dispatches, _ = analyzer._read_records()

        assert len(second_dispatches) == 1, (
            "Same-mtime in-place rewrite served stale cache: the size component "
            "of the cache key failed to catch the change. Expected the new "
            "1-dispatch ledger; got the stale 2-dispatch cache."
        )


class TestCacheEmptyLedgerHandling:
    """Edge cases around file existence + initial-empty cache state."""

    def test_missing_ledger_returns_empty_lists(
        self,
        tmp_path: Path,
    ) -> None:
        """If the ledger file doesn't exist, _read_records returns empty lists.

        Cache should hold this "missing" state cleanly — second call hits cache.
        """
        analyzer = CostAnalyzer(ledger_path=tmp_path / "nonexistent.jsonl")

        first = analyzer._read_records()
        second = analyzer._read_records()

        assert first == ([], [])
        # Identity check: cached empty-result is reused.
        assert first is second

    def test_ledger_created_after_first_read_invalidates_cache(
        self,
        ledger_path: Path,
        sample_records: list[DispatchRecord | PipelineRecord],
    ) -> None:
        """If the file is created AFTER an initial empty read, the cache notices."""
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        # First read: file doesn't exist.
        first_dispatches, first_pipelines = analyzer._read_records()
        assert first_dispatches == []
        assert first_pipelines == []

        # File created.
        _write_records(ledger_path, sample_records)

        # Second read: must NOT return the cached empty result.
        second_dispatches, second_pipelines = analyzer._read_records()
        assert len(second_dispatches) == 2, (
            "Cache failed to invalidate when the ledger file appeared between calls"
        )
        assert len(second_pipelines) == 1
