# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost tracker consumer — accumulates cost and emits budget threshold events."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from bonfire.errors import ValidationError
from bonfire.models.events import (
    CostBudgetExceeded,
    CostBudgetWarning,
    DispatchCompleted,
    PipelineStarted,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class CostTracker:
    """Accumulates cost from DispatchCompleted events and emits budget alerts.

    State is partitioned per pipeline run: ``PipelineStarted`` re-bases the
    running total, the latch flags, and the active budget from the event's
    own ``budget_usd``. Without that reset the warning/exceeded latches stay
    stuck across runs and a later pipeline in the same process never gets its
    own budget alerts.
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

    async def _on_pipeline_started(self, event: PipelineStarted) -> None:
        """Re-base tally + latch state for a new pipeline run.

        The new run declares its own ``budget_usd``; we adopt it and clear
        the sticky warning/exceeded flags so this run's alerts fire on their
        own merits. A malformed budget (NaN/inf/negative) is a boundary
        violation: it would poison the threshold math (``percent`` becomes
        NaN, which compares false against every threshold and silently
        swallows all future alerts). We surface it LOUD as a typed
        ``ValidationError`` carrying context rather than absorbing the
        garbage.
        """
        budget = event.budget_usd
        if math.isnan(budget) or math.isinf(budget) or budget < 0:
            raise ValidationError(
                "PipelineStarted carried a non-finite or negative budget_usd",
                context={
                    "budget_usd": budget,
                    "session_id": event.session_id,
                    "plan_name": event.plan_name,
                },
            )

        self._budget_usd = budget
        self._total_cost_usd = 0.0
        self._warning_emitted = False
        self._exceeded_emitted = False
        logger.debug(
            "CostTracker re-based for pipeline start: plan=%s session=%s budget_usd=%.4f",
            event.plan_name,
            event.session_id,
            budget,
        )

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
            logger.info(
                "Budget exceeded: session=%s current_usd=%.4f budget_usd=%.4f",
                event.session_id,
                self._total_cost_usd,
                self._budget_usd,
            )
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
            logger.info(
                "Budget warning: session=%s current_usd=%.4f budget_usd=%.4f percent=%.1f",
                event.session_id,
                self._total_cost_usd,
                self._budget_usd,
                percent if percent != float("inf") else 100.0,
            )
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
        """Subscribe to DispatchCompleted (tally) and PipelineStarted (reset)."""
        bus.subscribe(DispatchCompleted, self._on_dispatch_completed)
        bus.subscribe(PipelineStarted, self._on_pipeline_started)
