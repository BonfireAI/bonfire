# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost tracker consumer — accumulates cost and emits budget threshold events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bonfire.models.events import (
    CostBudgetExceeded,
    CostBudgetWarning,
    DispatchCompleted,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class CostTracker:
    """Accumulates cost from DispatchCompleted events and emits budget alerts."""

    def __init__(self, budget_usd: float, bus: EventBus) -> None:
        self._budget_usd = budget_usd
        self._bus = bus
        self._total_cost_usd: float = 0.0
        self._warning_emitted: bool = False
        self._exceeded_emitted: bool = False

    @property
    def total_cost_usd(self) -> float:
        """Running total cost in USD."""
        return self._total_cost_usd

    async def _on_dispatch_completed(self, event: DispatchCompleted) -> None:
        """Accumulate cost and check thresholds."""
        self._total_cost_usd += event.cost_usd

        if self._budget_usd <= 0:
            percent = float("inf")
        else:
            percent = (self._total_cost_usd / self._budget_usd) * 100.0

        # Check 100% first (a single event could cross both)
        if percent >= 100.0 and not self._exceeded_emitted:
            self._exceeded_emitted = True
            await self._bus.emit(
                CostBudgetExceeded(
                    session_id=event.session_id,
                    sequence=0,
                    current_usd=self._total_cost_usd,
                    budget_usd=self._budget_usd,
                )
            )

        if percent >= 80.0 and not self._warning_emitted:
            self._warning_emitted = True
            await self._bus.emit(
                CostBudgetWarning(
                    session_id=event.session_id,
                    sequence=0,
                    current_usd=self._total_cost_usd,
                    budget_usd=self._budget_usd,
                    percent=percent if percent != float("inf") else 100.0,
                )
            )

    def register(self, bus: EventBus) -> None:
        """Subscribe to DispatchCompleted events."""
        bus.subscribe(DispatchCompleted, self._on_dispatch_completed)
