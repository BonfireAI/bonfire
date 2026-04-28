"""Cost ledger consumer — persists cost events to JSONL."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.cost.models import DEFAULT_LEDGER_PATH, DispatchRecord, PipelineRecord
from bonfire.models.events import DispatchCompleted, PipelineCompleted

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class CostLedgerConsumer:
    """Subscribes to cost events and appends records to a JSONL ledger."""

    def __init__(self, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
        self._ledger_path = Path(ledger_path)

    def register(self, bus: EventBus) -> None:
        """Subscribe to cost-bearing events on the bus."""
        bus.subscribe(DispatchCompleted, self._on_dispatch_completed)
        bus.subscribe(PipelineCompleted, self._on_pipeline_completed)

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

    def _append(self, record: DispatchRecord | PipelineRecord) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")
