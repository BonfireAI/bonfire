# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost ledger consumer — persists cost events to JSONL."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire._safe_write import safe_append_text
from bonfire.cost.models import DEFAULT_LEDGER_PATH, DispatchRecord, PipelineRecord
from bonfire.models.events import (
    DispatchCompleted,
    PipelineCompleted,
    PipelineFailed,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class CostLedgerConsumer:
    """Subscribes to cost events and appends records to a JSONL ledger.

    Subscribes to BOTH ``PipelineCompleted`` and ``PipelineFailed`` so
    the persisted ledger reflects partial-spend on halt paths;
    success-only persistence drops crash sessions entirely and
    downstream analyzers overcount session success rate.

    Writes route through ``bonfire._safe_write.safe_append_text`` so a
    planted symlink at the operator-controlled ledger path is refused
    at ``open(2)`` time (W7.M defense-in-depth parity).
    """

    def __init__(self, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
        self._ledger_path = Path(ledger_path)

    def register(self, bus: EventBus) -> None:
        """Subscribe to cost-bearing events on the bus."""
        bus.subscribe(DispatchCompleted, self._on_dispatch_completed)
        bus.subscribe(PipelineCompleted, self._on_pipeline_completed)
        bus.subscribe(PipelineFailed, self._on_pipeline_failed)

    async def _on_dispatch_completed(self, event: DispatchCompleted) -> None:
        record = DispatchRecord(
            timestamp=event.timestamp,
            session_id=event.session_id,
            agent_name=event.agent_name,
            cost_usd=event.cost_usd,
            duration_seconds=event.duration_seconds,
            model=event.model,
        )
        self._append(record)

    async def _on_pipeline_completed(self, event: PipelineCompleted) -> None:
        record = PipelineRecord(
            timestamp=event.timestamp,
            session_id=event.session_id,
            total_cost_usd=event.total_cost_usd,
            duration_seconds=event.duration_seconds,
            stages_completed=event.stages_completed,
        )
        self._append(record)

    async def _on_pipeline_failed(self, event: PipelineFailed) -> None:
        """Persist a ``PipelineRecord`` for halt-path runs.

        Wave 11 Lane A grew ``PipelineFailed`` to carry
        ``duration_seconds`` (M3) and ``stages_completed`` (M7),
        symmetric with ``PipelineCompleted``. Forwarding both fields
        means halt-path rows carry real run length and real progress
        — every failed session no longer looks instant with zero
        stages done, and downstream analyzers can compute meaningful
        success-rate / mean-time-to-halt over the ledger.
        """
        record = PipelineRecord(
            timestamp=event.timestamp,
            session_id=event.session_id,
            total_cost_usd=event.total_cost_usd,
            duration_seconds=event.duration_seconds,
            stages_completed=event.stages_completed,
        )
        self._append(record)

    def _append(self, record: DispatchRecord | PipelineRecord) -> None:
        """Append *record* as a single JSONL line via the symlink-safe writer."""
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        safe_append_text(self._ledger_path, record.model_dump_json() + "\n")
