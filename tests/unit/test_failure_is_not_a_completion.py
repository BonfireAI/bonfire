# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""A halt must never record itself as a completion.

Four records had the same shape of defect: the failure path produced an
artifact indistinguishable from the success path, or gave a reason that
was not the reason that occurred. Each test below fails on the
pre-fix behaviour; each is paired with a negative control asserting a
genuine success still records as a success, so the suite cannot be
satisfied by code that simply reports everything as broken.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bonfire.cost.analyzer import CostAnalyzer
from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.cost.models import PipelineRecord
from bonfire.events.bus import EventBus
from bonfire.models.events import (
    PipelineCompleted,
    PipelineFailed,
    XPAwarded,
    XPPenalty,
)
from bonfire.onboard.flow import dispatch_user_message
from bonfire.onboard.orchestrator import _run_one, run_scan
from bonfire.onboard.protocol import UserMessage
from bonfire.xp.calculator import XPCalculator
from bonfire.xp.consumer import XPConsumer
from bonfire.xp.tracker import XPTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION = "sess-halt-vs-done"


def _completed(**over: object) -> PipelineCompleted:
    kwargs: dict = {
        "session_id": _SESSION,
        "sequence": 1,
        "total_cost_usd": 1.5,
        "duration_seconds": 10.0,
        "stages_completed": 1,
    }
    kwargs.update(over)
    return PipelineCompleted(**kwargs)


def _failed(**over: object) -> PipelineFailed:
    kwargs: dict = {
        "session_id": _SESSION,
        "sequence": 1,
        "failed_stage": "builder",
        "error_message": "builder raised RuntimeError: disk full",
        "total_cost_usd": 1.5,
        "duration_seconds": 10.0,
        "stages_completed": 1,
    }
    kwargs.update(over)
    return PipelineFailed(**kwargs)


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sink() -> tuple[list, object]:
    """A capture list and the async emit/broadcast callable that fills it."""
    captured: list = []

    async def emit(message: object) -> None:
        captured.append(message)

    return captured, emit


#: A ledger row as written BEFORE ``outcome`` existed — the shape the
#: operator already has on disk.
_LEGACY_ROW: dict = {
    "type": "pipeline",
    "timestamp": 1785232588.0,
    "session_id": "legacy",
    "total_cost_usd": 0.37,
    "duration_seconds": 0.0004,
    "stages_completed": 2,
}


class _Crashy:
    """A scanner that dies."""

    @staticmethod
    async def scan(path: Path, emit: object) -> int:
        raise RuntimeError("no git binary on PATH")


class _Empty:
    """A scanner that runs clean and legitimately finds nothing."""

    @staticmethod
    async def scan(path: Path, emit: object) -> int:
        return 0


# ---------------------------------------------------------------------------
# Defect 1 — the cost ledger, the operator's record of what they paid for
# ---------------------------------------------------------------------------


class TestLedgerDistinguishesHaltFromCompletion:
    async def test_halt_and_one_stage_success_are_distinguishable(self, tmp_path: Path) -> None:
        """The observed defect: a failed run showed up as '1 stages', exactly
        like a run that finished one stage. Rows differing only in timestamp
        are not distinguishable to any reader that aggregates by session."""
        ledger = tmp_path / "cost_ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=ledger)

        await consumer._on_pipeline_completed(_completed())
        await consumer._on_pipeline_failed(_failed())

        success, failure = _rows(ledger)
        distinguishing = {k for k in success if success[k] != failure.get(k)} - {"timestamp"}
        assert distinguishing, (
            "halt row and success row differ only by timestamp — the ledger "
            f"cannot tell a crash from a completion: {success!r} vs {failure!r}"
        )
        assert success["outcome"] == "completed"
        assert failure["outcome"] == "failed"

    async def test_halt_row_carries_the_reason_that_actually_occurred(self, tmp_path: Path) -> None:
        ledger = tmp_path / "cost_ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=ledger)

        await consumer._on_pipeline_failed(_failed())

        (row,) = _rows(ledger)
        assert row["failed_stage"] == "builder"
        assert "disk full" in row["error_message"]

    async def test_success_still_records_as_success(self, tmp_path: Path) -> None:
        """Negative control: the fix must not make completions look like halts."""
        ledger = tmp_path / "cost_ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=ledger)

        await consumer._on_pipeline_completed(_completed())

        (row,) = _rows(ledger)
        assert row["outcome"] == "completed"
        assert row["failed_stage"] is None
        assert row["error_message"] is None
        assert row["stages_completed"] == 1
        assert row["total_cost_usd"] == 1.5

    def test_rows_written_before_the_field_existed_still_load(self) -> None:
        """Migration: history on disk predates ``outcome``. Those rows must keep
        validating, and must NOT be fabricated into successes."""
        record = PipelineRecord.model_validate(_LEGACY_ROW)
        assert record.outcome == "unknown", (
            "a row that never recorded an outcome must not claim one; "
            "defaulting to 'completed' would fabricate the very history "
            "this defect corrupted"
        )

    def test_legacy_rows_still_aggregate_through_the_analyzer(self, tmp_path: Path) -> None:
        """The sole reader must not start skipping pre-migration rows."""
        ledger = tmp_path / "cost_ledger.jsonl"
        ledger.write_text(json.dumps(_LEGACY_ROW) + "\n")
        sessions = CostAnalyzer(ledger_path=ledger).all_sessions()
        assert [s.session_id for s in sessions] == ["legacy"]
        assert sessions[0].stages_completed == 2


# ---------------------------------------------------------------------------
# Defect 2 — the XP substrate. The reported defect was NOT what is broken.
# ---------------------------------------------------------------------------


class TestXPPenaltyStatesTheRealReason:
    @staticmethod
    def _consumer(tmp_path: Path) -> tuple[EventBus, list[object], XPTracker]:
        bus = EventBus()
        seen: list[object] = []

        async def capture(event: object) -> None:
            seen.append(event)

        bus.subscribe(XPAwarded, capture)
        bus.subscribe(XPPenalty, capture)
        tracker = XPTracker(tmp_path)
        XPConsumer(tracker=tracker, calculator=XPCalculator(), bus=bus)
        return bus, seen, tracker

    async def test_penalty_reason_names_the_stage_and_error(self, tmp_path: Path) -> None:
        """The reason was invented from a hardcoded count while the event's own
        ``failed_stage``/``error_message`` were discarded."""
        bus, seen, _ = self._consumer(tmp_path)

        await bus.emit(_failed())
        await asyncio.sleep(0)

        (penalty,) = seen
        assert isinstance(penalty, XPPenalty)
        assert "builder" in penalty.reason
        assert "disk full" in penalty.reason
        assert "1 stage failures" not in penalty.reason

    async def test_stageless_halt_does_not_invent_a_stage(self, tmp_path: Path) -> None:
        """Budget-exceeded and outer-exception halts carry no stage name."""
        bus, seen, _ = self._consumer(tmp_path)

        await bus.emit(_failed(failed_stage="", error_message="Budget exceeded: $9.00 > $5.00"))
        await asyncio.sleep(0)

        (penalty,) = seen
        assert "Budget exceeded" in penalty.reason
        assert "unknown stage" not in penalty.reason

    async def test_outer_sentinel_is_not_rendered_as_a_bounce_target(self, tmp_path: Path) -> None:
        bus, seen, _ = self._consumer(tmp_path)

        await bus.emit(_failed(failed_handler="__outer__"))
        await asyncio.sleep(0)

        (penalty,) = seen
        assert "__outer__" not in penalty.reason

    async def test_bounce_target_is_named_when_it_is_a_real_handler(self, tmp_path: Path) -> None:
        bus, seen, _ = self._consumer(tmp_path)

        await bus.emit(_failed(failed_handler="sage"))
        await asyncio.sleep(0)

        (penalty,) = seen
        assert "sage" in penalty.reason

    async def test_xp_store_already_recorded_failure_honestly(self, tmp_path: Path) -> None:
        """Control on the REPORTED defect, which did not reproduce: the store
        already carried ``success=False``. This pins that it stays true."""
        bus, _, tracker = self._consumer(tmp_path)

        await bus.emit(_failed())
        await asyncio.sleep(0)

        (event,) = tracker.events()
        assert event["success"] is False

    async def test_success_still_awards_and_reads_as_success(self, tmp_path: Path) -> None:
        """Negative control for the whole XP path."""
        bus, seen, tracker = self._consumer(tmp_path)

        await bus.emit(_completed())
        await asyncio.sleep(0)

        (award,) = seen
        assert isinstance(award, XPAwarded)
        assert "halted" not in award.reason
        assert tracker.events()[0]["success"] is True


# ---------------------------------------------------------------------------
# Defect 3 — a scanner that crashed is not a scanner that found nothing
# ---------------------------------------------------------------------------


class TestCrashedScannerIsNotAnEmptyScan:
    async def test_crash_and_empty_scan_are_distinguishable(self) -> None:
        crashed, crash_emit = _sink()
        empty, empty_emit = _sink()
        await _run_one("git_state", _Crashy, Path("."), crash_emit)
        await _run_one("git_state", _Empty, Path("."), empty_emit)

        (crash_frame,) = crashed
        (empty_frame,) = empty
        assert crash_frame.model_dump() != empty_frame.model_dump(), (
            "a dead scanner and an empty one emit identical frames — the "
            "browser cannot tell 'the scan died' from 'we found nothing'"
        )
        assert (crash_frame.failed, empty_frame.failed) == (True, False)
        assert "RuntimeError" in crash_frame.error
        assert "no git binary" in crash_frame.error

    async def test_clean_scan_is_untouched(self) -> None:
        """Negative control: a working scanner still reports its count."""
        sink, emit = _sink()
        result = await _run_one("git_state", _Empty, Path("."), emit)

        assert result == (0, False)
        assert sink[0].error is None

    @pytest.mark.parametrize(
        ("scanners", "expected_failed"),
        [
            ([("git_state", _Crashy), ("mcp_servers", _Empty)], 1),
            ([("git_state", _Empty), ("mcp_servers", _Empty)], 0),
        ],
    )
    async def test_summary_frame_counts_failed_panels(
        self, monkeypatch, scanners: list, expected_failed: int
    ) -> None:
        """The same defect one level up: an all-crashed run summarised as
        ``total_items=0``, identical to a clean scan of an empty project.
        The zero-failure row is the negative control."""
        monkeypatch.setattr("bonfire.onboard.orchestrator._get_scanners", lambda: scanners)
        sink, emit = _sink()
        await run_scan(Path("."), emit)

        assert sink[-1].total_items == 0
        assert sink[-1].failed_panels == expected_failed


# ---------------------------------------------------------------------------
# Defect 4 — a wrong reason sends the user to fix something that is not broken
# ---------------------------------------------------------------------------


class TestFrameRejectionNamesTheRealCause:
    @staticmethod
    async def _reject(frame: dict) -> object:
        sink, broadcast = _sink()
        await dispatch_user_message(
            frame,
            conversation=None,
            broadcast=broadcast,
            conversation_done=asyncio.Event(),
        )
        return sink[0]

    @pytest.mark.parametrize(
        ("label", "frame"),
        [
            ("missing text", {"type": "user_message"}),
            ("text is a number", {"type": "user_message", "text": 12345}),
        ],
    )
    async def test_non_length_failures_are_not_called_too_long(
        self, label: str, frame: dict
    ) -> None:
        error = await self._reject(frame)
        assert error.code != "message_too_long", (
            f"{label}: reported as a length problem over a message that was "
            "never long — the user is sent to fix something that is not broken"
        )
        assert error.code == "invalid_message"

    async def test_missing_field_says_which_field(self) -> None:
        error = await self._reject({"type": "user_message"})
        assert "text" in error.message

    async def test_genuinely_too_long_still_says_too_long(self) -> None:
        """Negative control: the real length violation keeps its own code, and
        the existing cap contract is unchanged."""
        error = await self._reject({"type": "user_message", "text": "x" * 9000})
        assert error.code == "message_too_long"
        assert "8 KiB" in error.message

    def test_the_length_cap_itself_is_still_enforced(self) -> None:
        with pytest.raises(ValidationError):
            UserMessage.model_validate({"type": "user_message", "text": "x" * 9000})
