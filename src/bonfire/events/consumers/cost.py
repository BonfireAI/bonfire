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
    DispatchFailed,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class CostTracker:
    """Accumulates cost from dispatch events and emits budget alerts.

    Subscribes to BOTH ``DispatchCompleted`` and ``DispatchFailed`` so
    flaky / retried / outright-failed attempts whose backend still
    charged real money land in the running total. Success-only
    accounting silently undercounts the budget every time a transient
    backend failure costs the wallet before the runner gives up.
    """

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

    async def _accumulate(self, session_id: str, cost_usd: float) -> None:
        """Accumulate *cost_usd* against the running total and check thresholds.

        Shared core used by both the ``DispatchCompleted`` and
        ``DispatchFailed`` subscribers so the budget-threshold logic
        stays in one place and cannot drift between paths.
        """
        self._total_cost_usd += cost_usd

        if self._budget_usd <= 0:
            percent = float("inf")
        else:
            percent = (self._total_cost_usd / self._budget_usd) * 100.0

        # Check 100% first (a single event could cross both)
        if percent >= 100.0 and not self._exceeded_emitted:
            self._exceeded_emitted = True
            await self._bus.emit(
                CostBudgetExceeded(
                    session_id=session_id,
                    sequence=0,
                    current_usd=self._total_cost_usd,
                    budget_usd=self._budget_usd,
                )
            )

        if percent >= 80.0 and not self._warning_emitted:
            self._warning_emitted = True
            await self._bus.emit(
                CostBudgetWarning(
                    session_id=session_id,
                    sequence=0,
                    current_usd=self._total_cost_usd,
                    budget_usd=self._budget_usd,
                    percent=percent if percent != float("inf") else 100.0,
                )
            )

    async def _on_dispatch_completed(self, event: DispatchCompleted) -> None:
        """Accumulate the success-path cost and check thresholds."""
        await self._accumulate(event.session_id, event.cost_usd)

    async def _on_dispatch_failed(self, event: DispatchFailed) -> None:
        """Accumulate the failure-path cost and check thresholds.

        ``DispatchFailed.cost_usd`` is the cumulative dollars the runner
        charged across every attempt before giving up. Same scalar shape
        as ``DispatchCompleted.cost_usd`` so the tracker can sum
        uniformly.
        """
        await self._accumulate(event.session_id, event.cost_usd)

    def register(self, bus: EventBus) -> None:
        """Subscribe to both success and failure dispatch events."""
        bus.subscribe(DispatchCompleted, self._on_dispatch_completed)
        bus.subscribe(DispatchFailed, self._on_dispatch_failed)
