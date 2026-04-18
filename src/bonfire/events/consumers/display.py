"""Display consumer — formats events into human-readable strings for a callback."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bonfire.models.events import (
    CostBudgetWarning,
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

    def register(self, bus: EventBus) -> None:
        """Subscribe to the four display-worthy event types."""
        bus.subscribe(StageCompleted, self._on_stage_completed)
        bus.subscribe(StageFailed, self._on_stage_failed)
        bus.subscribe(QualityFailed, self._on_quality_failed)
        bus.subscribe(CostBudgetWarning, self._on_cost_budget_warning)
