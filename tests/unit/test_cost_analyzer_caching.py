# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests — BON-908 — `CostAnalyzer` re-reads + re-validates the whole
ledger on every method call.

Surfaced by the Mirror Path B production-1 performance Scout. Every public
method on ``CostAnalyzer`` (``cumulative_cost``, ``session_cost``,
``agent_costs``, ``model_costs``, ``all_sessions``, ``all_records``) opens
the JSONL ledger, iterates every line, runs ``json.loads`` and Pydantic
``model_validate`` per record.

The default ``bonfire cost`` callback (`cli/commands/cost.py:33-35`) calls
``cumulative_cost()`` AND ``all_sessions()`` — **two full ledger passes per
command**. On a long-lived operator's 10k+ line ledger this parse cost is
paid twice per invocation, every invocation.

These tests pin the *intended post-fix* behaviour, deterministically and
offline — they count file opens and Pydantic validations, never wall clock:

* ``_read_records`` is called / the ledger file is opened **at most once**
  per CLI invocation (memoize on ``self`` with mtime invalidation, or have
  the callback read once and pass the records down).
* Read-only aggregations avoid Pydantic per-record validation in the hot
  path (raw dict access where the types are simple).
* the memoized read **invalidates when the ledger file's mtime changes** —
  a stale cache must never serve old data after an append.

Test authors and implementation authors are different hands (TDD law).
Implementation NEVER edits this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import bonfire.cost.models as cost_models
from bonfire.cost.analyzer import CostAnalyzer
from bonfire.cost.models import DispatchRecord, PipelineRecord

if TYPE_CHECKING:
    pass


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
        ),
        PipelineRecord(
            timestamp=1002.0,
            session_id="ses_001",
            total_cost_usd=0.13,
            duration_seconds=54.3,
            stages_completed=2,
        ),
        DispatchRecord(
            timestamp=2000.0,
            session_id="ses_002",
            agent_name="warrior",
            cost_usd=0.06,
            duration_seconds=35.0,
        ),
        PipelineRecord(
            timestamp=2003.0,
            session_id="ses_002",
            total_cost_usd=0.41,
            duration_seconds=82.1,
            stages_completed=3,
        ),
    ]


class _OpenCounter:
    """Wraps ``Path.open`` to count opens of one specific file path."""

    def __init__(self, target: Path) -> None:
        self._target = target.resolve()
        self._original = Path.open
        self.count = 0

    def __enter__(self) -> _OpenCounter:
        counter = self

        def _counting_open(self_path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            if self_path.resolve() == counter._target:
                counter.count += 1
            return counter._original(self_path, *args, **kwargs)

        Path.open = _counting_open  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: object) -> None:
        Path.open = self._original  # type: ignore[method-assign]


class TestSingleReadPerCliInvocation:
    """AC: ``_read_records`` is called at most once per CLI invocation.

    The ``bonfire cost`` (no subcommand) callback calls ``cumulative_cost()``
    then ``all_sessions()`` — the buggy analyzer opens + parses the ledger
    twice. The fix memoizes the read on the instance (analyzer is built
    fresh per CLI invocation, so one instance == one invocation).
    """

    def test_summary_path_opens_ledger_at_most_once(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        """Simulate the ``cost_summary`` callback on one analyzer instance:
        ``cumulative_cost()`` + ``all_sessions()``. The ledger file must be
        opened at most once across both calls."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        with _OpenCounter(ledger_path) as counter:
            analyzer.cumulative_cost()
            analyzer.all_sessions()

        assert counter.count <= 1, (
            f"`bonfire cost` summary path opened the ledger {counter.count} times "
            "on one analyzer instance — expected <= 1 (memoized read). Two full "
            "passes per command is the BON-908 defect."
        )

    def test_repeated_method_calls_reuse_one_read(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        """Every public read method on a single analyzer instance shares one
        ledger read. Calling all six must not re-open the file six times."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        with _OpenCounter(ledger_path) as counter:
            analyzer.cumulative_cost()
            analyzer.session_cost("ses_001")
            analyzer.agent_costs()
            analyzer.model_costs()
            analyzer.all_sessions()
            analyzer.all_records()

        assert counter.count <= 1, (
            f"Six read methods on one analyzer instance opened the ledger "
            f"{counter.count} times — expected <= 1 (memoized read)."
        )


class TestReadOnlyAggregationsAvoidPydantic:
    """AC: read-only aggregations (cumulative, agent_costs, model_costs)
    avoid Pydantic per-record validation; raw dict access where types are
    simple."""

    def test_cumulative_cost_does_not_validate_every_record_with_pydantic(
        self, ledger_path: Path
    ) -> None:
        """``cumulative_cost()`` over a 2000-line ledger must not run
        ``PipelineRecord.model_validate`` once per line. The hot read-only
        aggregation path should use raw dict access.

        Counted deterministically by wrapping ``model_validate`` on both
        record models and asserting the call count stays far below the
        record count.
        """
        n = 2000
        records: list[DispatchRecord | PipelineRecord] = []
        for i in range(n):
            records.append(
                PipelineRecord(
                    timestamp=float(i),
                    session_id=f"ses_{i}",
                    total_cost_usd=0.01,
                    duration_seconds=1.0,
                    stages_completed=1,
                )
            )
        _write_records(ledger_path, records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        validate_calls = {"n": 0}
        orig_dispatch = DispatchRecord.model_validate.__func__  # type: ignore[attr-defined]
        orig_pipeline = PipelineRecord.model_validate.__func__  # type: ignore[attr-defined]

        def _counted_dispatch(cls, *a, **k):  # type: ignore[no-untyped-def]
            validate_calls["n"] += 1
            return orig_dispatch(cls, *a, **k)

        def _counted_pipeline(cls, *a, **k):  # type: ignore[no-untyped-def]
            validate_calls["n"] += 1
            return orig_pipeline(cls, *a, **k)

        DispatchRecord.model_validate = classmethod(_counted_dispatch)  # type: ignore[method-assign]
        PipelineRecord.model_validate = classmethod(_counted_pipeline)  # type: ignore[method-assign]
        try:
            total = analyzer.cumulative_cost()
        finally:
            DispatchRecord.model_validate = classmethod(orig_dispatch)  # type: ignore[method-assign]
            PipelineRecord.model_validate = classmethod(orig_pipeline)  # type: ignore[method-assign]

        assert total == pytest.approx(n * 0.01)
        # A correct raw-dict aggregation does zero per-record model_validate.
        # We allow a tiny constant for any unavoidable validation, but a
        # per-line validate (>= n) is the defect.
        assert validate_calls["n"] < n, (
            f"cumulative_cost() ran model_validate {validate_calls['n']} times for "
            f"{n} records — read-only aggregations must avoid per-record Pydantic "
            "validation (raw dict access)."
        )


class TestCacheInvalidatesOnMtime:
    """AC: a unit test asserts cache invalidation on file mtime change."""

    def test_memoized_read_refreshes_when_ledger_mtime_changes(self, ledger_path: Path) -> None:
        """After the analyzer caches a read, appending to the ledger (which
        bumps its mtime) must invalidate the cache — the next call sees the
        new data, not stale cached records.

        A naive permanent memo passes the single-invocation tests above but
        silently serves stale data here.
        """
        first = [
            PipelineRecord(
                timestamp=1.0,
                session_id="ses_a",
                total_cost_usd=0.10,
                duration_seconds=1.0,
                stages_completed=1,
            )
        ]
        _write_records(ledger_path, first)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        assert analyzer.cumulative_cost() == pytest.approx(0.10)

        # Append a second record and force a distinct, later mtime.
        second = first + [
            PipelineRecord(
                timestamp=2.0,
                session_id="ses_b",
                total_cost_usd=0.25,
                duration_seconds=1.0,
                stages_completed=1,
            )
        ]
        _write_records(ledger_path, second)
        st = ledger_path.stat()
        import os

        os.utime(ledger_path, (st.st_atime, st.st_mtime + 10))

        assert analyzer.cumulative_cost() == pytest.approx(0.35), (
            "CostAnalyzer served a stale cached read after the ledger mtime "
            "changed — the memoized read must invalidate on mtime change."
        )

    def test_no_reread_when_ledger_unchanged(self, ledger_path: Path, sample_records: list) -> None:
        """The flip side of mtime invalidation: if the ledger is untouched
        between calls, the cache is reused — no second open."""
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)

        analyzer.cumulative_cost()  # primes the cache
        with _OpenCounter(ledger_path) as counter:
            analyzer.agent_costs()
            analyzer.all_sessions()

        assert counter.count == 0, (
            f"Ledger unchanged between calls but it was re-opened {counter.count} "
            "times — a primed cache must be reused when mtime is unchanged."
        )


def test_default_ledger_path_constant_unchanged() -> None:
    """Sanity pin: the analyzer keys its cache off the ledger path; the
    default path constant must still exist and be a Path."""
    assert isinstance(cost_models.DEFAULT_LEDGER_PATH, Path)
