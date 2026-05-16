# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Display consumer — formats events into human-readable strings for a callback."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bonfire.models.events import (
    CostBudgetExceeded,
    CostBudgetWarning,
    PipelineCompleted,
    PipelineFailed,
    QualityFailed,
    StageCompleted,
    StageFailed,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class DisplayConsumer:
    """Formats pipeline events and delivers them via a sync or async callback."""

    def __init__(
        self,
        callback: Callable[..., Any] | Any,
        persona: Any | None = None,
    ) -> None:
        self._callback = callback
        self._is_async = asyncio.iscoroutinefunction(callback)
        self._persona = persona

    async def _call(self, message: str) -> None:
        """Invoke the callback, handling both sync and async variants."""
        try:
            if self._is_async:
                await self._callback(message)
            else:
                self._callback(message)
        except Exception:
            logger.warning("Display callback failed", exc_info=True)

    async def _on_stage_completed(self, event: StageCompleted) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        msg = f"[{event.stage_name}] completed ({event.duration_seconds}s, ${event.cost_usd})"
        await self._call(msg)

    async def _on_stage_failed(self, event: StageFailed) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        msg = f"[{event.stage_name}] FAILED: {event.error_message}"
        await self._call(msg)

    async def _on_quality_failed(self, event: QualityFailed) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        msg = f"\u26a0 {event.gate_name} gate FAILED \u2014 {event.message}"
        await self._call(msg)

    async def _on_cost_budget_warning(self, event: CostBudgetWarning) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        msg = (
            f"\u26a0 Budget {event.percent}% consumed (${event.current_usd} / ${event.budget_usd})"
        )
        await self._call(msg)

    async def _on_pipeline_completed(self, event: PipelineCompleted) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        msg = (
            f"\u2714 Pipeline completed: {event.stages_completed} stages "
            f"in {event.duration_seconds:.1f}s (${event.total_cost_usd:.4f})"
        )
        await self._call(msg)

    async def _on_pipeline_failed(self, event: PipelineFailed) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        # When the halt fired on a bounce target, surface BOTH the
        # original stage (whose contract broke) and the bounce target
        # (the handler that died). Otherwise just the failed stage.
        if event.failed_handler and event.failed_handler != event.failed_stage:
            label = f"{event.failed_stage} \u2192 {event.failed_handler}"
        else:
            label = event.failed_stage or "<budget>"
        msg = f"\u2716 Pipeline HALTED at [{label}]: {event.error_message}"
        await self._call(msg)

    async def _on_cost_budget_exceeded(self, event: CostBudgetExceeded) -> None:
        if self._persona is not None:
            result = self._persona.format_event(event)
            if result is not None:
                await self._call(str(result))
            return
        msg = f"\u2716 Budget EXCEEDED: ${event.current_usd:.4f} > ${event.budget_usd:.4f}"
        await self._call(msg)

    def register(self, bus: EventBus) -> None:
        """Subscribe to the operator-facing state-transition event types.

        Originally four (stage success/failure, quality failure, budget
        warning); Wave 11 Lane A added the three halt-branch /
        budget-broken signals so operators driving the CLI see a
        visible message on every important state transition:

          * ``PipelineCompleted`` \u2014 the pipeline finished cleanly.
          * ``PipelineFailed`` \u2014 the pipeline halted (failed stage,
            failed gate, exceeded budget, or bounce-target died).
          * ``CostBudgetExceeded`` \u2014 the budget was crossed (distinct
            from the 80%-threshold ``CostBudgetWarning`` already wired).
        """
        bus.subscribe(StageCompleted, self._on_stage_completed)
        bus.subscribe(StageFailed, self._on_stage_failed)
        bus.subscribe(QualityFailed, self._on_quality_failed)
        bus.subscribe(CostBudgetWarning, self._on_cost_budget_warning)
        bus.subscribe(PipelineCompleted, self._on_pipeline_completed)
        bus.subscribe(PipelineFailed, self._on_pipeline_failed)
        bus.subscribe(CostBudgetExceeded, self._on_cost_budget_exceeded)
