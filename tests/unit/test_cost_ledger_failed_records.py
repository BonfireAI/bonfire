# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for BON-1068 H1 — failed dispatches/pipelines must be recorded.

Defect (origin/main): ``CostLedgerConsumer.register`` subscribes ONLY to
``DispatchCompleted`` and ``PipelineCompleted``. Failed dispatches
(``DispatchFailed``) and failed pipelines (``PipelineFailed``) burned real
tokens before failing, but no JSONL row is appended — so ``bonfire cost``'s
"Built by Bonfire for $X.XX" rollup silently UNDER-COUNTS spend.

These tests assert the FIXED behavior:

  1. ``CostLedgerConsumer`` writes a ledger row when a ``DispatchFailed`` is
     emitted, carrying that dispatch's cost.
  2. It writes a row when a ``PipelineFailed`` is emitted, carrying that
     pipeline's cost.
  3. The cost record model carries a ``status`` field distinguishing
     ``completed`` from ``failed`` rows (acceptance criterion: every row
     records its outcome; the analyzer must sum every record, not only
     success).
  4. The Failed events themselves must carry a cost the consumer can read
     (``cost_usd`` on ``DispatchFailed`` / ``total_cost_usd`` on
     ``PipelineFailed``) — otherwise the burned spend is unknowable.

Why each FAILS on current code:
  - ``register`` never subscribes to the Failed events → emitting them
    produces NO ledger file → the read/assert fails (file missing / 0 rows).
  - ``DispatchFailed`` / ``PipelineFailed`` in ``models/events.py`` currently
    have NO ``cost_usd`` / ``total_cost_usd`` fields → constructing them with
    a cost raises a Pydantic ``ValidationError`` (frozen models reject
    unknown kwargs).
  - ``DispatchRecord`` / ``PipelineRecord`` have no ``status`` field → the
    completed-vs-failed assertions cannot pass.

``pyproject.toml`` sets ``asyncio_mode = "auto"``; ``async def`` tests run
without an explicit mark.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.events.bus import EventBus
from bonfire.models.events import DispatchFailed, PipelineFailed

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "cost" / "cost_ledger.jsonl"


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def consumer(ledger_path: Path, bus: EventBus) -> CostLedgerConsumer:
    c = CostLedgerConsumer(ledger_path=ledger_path)
    c.register(bus)
    return c


# ---------------------------------------------------------------------------
# H1.a — DispatchFailed carries cost and is persisted
# ---------------------------------------------------------------------------


class TestDispatchFailedRecorded:
    async def test_dispatch_failed_event_carries_cost(self) -> None:
        """A dispatch that fails still burned tokens. ``DispatchFailed`` MUST
        expose a ``cost_usd`` so the consumer can record the real spend.

        On current code ``DispatchFailed`` has no ``cost_usd`` field, so this
        construction raises a Pydantic ValidationError.
        """
        event = DispatchFailed(
            session_id="ses_fail",
            sequence=1,
            agent_name="warrior",
            error_message="terminal error after 3 retries",
            cost_usd=0.42,
        )
        assert event.cost_usd == 0.42

    async def test_dispatch_failed_appends_ledger_row(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Emitting ``DispatchFailed`` MUST append a JSONL row carrying the
        burned cost. On current code the consumer never subscribes to
        ``DispatchFailed`` → no file is written → this read fails.
        """
        await bus.emit(
            DispatchFailed(
                session_id="ses_fail",
                sequence=1,
                agent_name="warrior",
                error_message="terminal error",
                cost_usd=0.42,
            )
        )

        assert ledger_path.exists(), "failed dispatch must produce a ledger row"
        lines = [ln for ln in ledger_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "dispatch"
        assert data["agent_name"] == "warrior"
        assert data["cost_usd"] == 0.42

    async def test_dispatch_failed_row_marked_failed(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """The persisted row for a failed dispatch MUST be marked
        ``status="failed"`` so the analyzer can distinguish completed vs
        failed spend. On current code ``DispatchRecord`` has no ``status``
        field, so this key is absent.
        """
        await bus.emit(
            DispatchFailed(
                session_id="ses_fail",
                sequence=1,
                agent_name="warrior",
                error_message="boom",
                cost_usd=0.30,
            )
        )

        data = json.loads(ledger_path.read_text().strip())
        assert data["status"] == "failed"


# ---------------------------------------------------------------------------
# H1.b — PipelineFailed carries cost and is persisted
# ---------------------------------------------------------------------------


class TestPipelineFailedRecorded:
    async def test_pipeline_failed_event_carries_cost(self) -> None:
        """A pipeline that fails mid-run already spent on completed stages.
        ``PipelineFailed`` MUST expose ``total_cost_usd``.

        On current code ``PipelineFailed`` has no ``total_cost_usd`` field, so
        this construction raises a Pydantic ValidationError.
        """
        event = PipelineFailed(
            session_id="ses_fail",
            sequence=2,
            failed_stage="warrior",
            error_message="gate failed, no bounce target",
            total_cost_usd=0.77,
        )
        assert event.total_cost_usd == 0.77

    async def test_pipeline_failed_appends_ledger_row(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Emitting ``PipelineFailed`` MUST append a JSONL pipeline row
        carrying the burned cost. On current code the consumer never
        subscribes to ``PipelineFailed`` → no file is written.
        """
        await bus.emit(
            PipelineFailed(
                session_id="ses_fail",
                sequence=2,
                failed_stage="warrior",
                error_message="gate failed",
                total_cost_usd=0.77,
            )
        )

        assert ledger_path.exists(), "failed pipeline must produce a ledger row"
        data = json.loads(ledger_path.read_text().strip())
        assert data["type"] == "pipeline"
        assert data["total_cost_usd"] == 0.77
        assert data["status"] == "failed"


# ---------------------------------------------------------------------------
# H1.c — completed rows are explicitly marked completed (the other half of
# the status contract — a failed row is only meaningful if a completed row
# is distinguishable from it).
# ---------------------------------------------------------------------------


class TestCompletedRowStatus:
    async def test_completed_dispatch_row_marked_completed(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """A successful dispatch row MUST carry ``status="completed"`` so the
        completed/failed distinction is total. On current code there is no
        ``status`` field at all.
        """
        from bonfire.models.events import DispatchCompleted

        await bus.emit(
            DispatchCompleted(
                session_id="ses_ok",
                sequence=0,
                agent_name="scout",
                cost_usd=0.05,
                duration_seconds=1.0,
            )
        )
        data = json.loads(ledger_path.read_text().strip())
        assert data["status"] == "completed"
