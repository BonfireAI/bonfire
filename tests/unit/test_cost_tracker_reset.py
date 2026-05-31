# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for BON-1008 — CostTracker resets sticky warning flags on
``PipelineStarted`` and partitions the budget tally per pipeline run.

Defect: ``CostTracker`` keeps ``_warning_emitted`` / ``_exceeded_emitted`` as
sticky booleans and a single ``_total_cost_usd`` counter shared across every
pipeline in the process. Once a budget warning fires for one pipeline, the
flag stays latched and later pipelines never get their own warning, and the
running total never resets — so a second pipeline inherits the first's spend.

``PipelineStarted`` carries the per-run ``budget_usd``, so a new pipeline run
re-bases both the latch state AND the budget tally. A malformed budget on the
event (non-finite, negative) is a boundary violation that must be surfaced
LOUD as a typed ``ValidationError`` — never silently accepted into the
threshold math.

``pyproject.toml`` sets ``asyncio_mode = "auto"``; ``async def`` tests are
discovered without an explicit marker.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from bonfire.errors import ValidationError
from bonfire.events.bus import EventBus
from bonfire.events.consumers.cost import CostTracker
from bonfire.models.events import (
    BonfireEvent,
    CostBudgetExceeded,
    CostBudgetWarning,
    DispatchCompleted,
    PipelineStarted,
)

_SESSION = "test-session-001"


def _dispatch_completed(**overrides: Any) -> DispatchCompleted:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "agent_name": "warrior-charlie",
        "cost_usd": 1.50,
        "duration_seconds": 3.2,
    }
    defaults.update(overrides)
    return DispatchCompleted(**defaults)


def _pipeline_started(**overrides: Any) -> PipelineStarted:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "plan_name": "dual",
        "budget_usd": 10.0,
    }
    defaults.update(overrides)
    return PipelineStarted(**defaults)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestRegisterSubscribesToPipelineStarted:
    """The tracker must now also listen for ``PipelineStarted`` so it can
    re-base its latch + tally state at the start of each run."""

    def test_register_subscribes_to_pipeline_started(self, bus: EventBus) -> None:
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        assert DispatchCompleted in subscribed_types
        assert PipelineStarted in subscribed_types


class TestFlagResetOnPipelineStarted:
    """``PipelineStarted`` re-bases the latch flags and the running total."""

    async def test_pipeline_started_resets_running_total(self, bus: EventBus) -> None:
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=5.0))
        assert tracker.total_cost_usd == pytest.approx(5.0)

        await bus.emit(_pipeline_started(budget_usd=10.0))
        assert tracker.total_cost_usd == pytest.approx(0.0)

    async def test_warning_flag_resets_so_second_pipeline_warns(self, bus: EventBus) -> None:
        captured: list[CostBudgetWarning] = []

        async def capture(event: CostBudgetWarning) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetWarning, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        # First pipeline crosses 80% -> one warning, flag latches.
        await bus.emit(_pipeline_started(budget_usd=10.0))
        await bus.emit(_dispatch_completed(cost_usd=8.0))
        assert len(captured) == 1

        # Second pipeline starts -> latch resets. Crossing 80% warns AGAIN.
        await bus.emit(_pipeline_started(budget_usd=10.0))
        await bus.emit(_dispatch_completed(cost_usd=8.0))
        assert len(captured) == 2

    async def test_exceeded_flag_resets_so_second_pipeline_exceeds(self, bus: EventBus) -> None:
        captured: list[CostBudgetExceeded] = []

        async def capture(event: CostBudgetExceeded) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetExceeded, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_pipeline_started(budget_usd=10.0))
        await bus.emit(_dispatch_completed(cost_usd=10.0))
        assert len(captured) == 1

        await bus.emit(_pipeline_started(budget_usd=10.0))
        await bus.emit(_dispatch_completed(cost_usd=10.0))
        assert len(captured) == 2


class TestBudgetPartitionedPerPipeline:
    """The budget itself is re-based from the new pipeline's declared
    ``budget_usd`` — sequential runs do not share budget state."""

    async def test_pipeline_started_adopts_new_budget(self, bus: EventBus) -> None:
        captured: list[CostBudgetWarning] = []

        async def capture(event: CostBudgetWarning) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetWarning, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        # Second pipeline declares a SMALLER budget; the warning threshold
        # must be computed against the new budget, not the constructor's.
        await bus.emit(_pipeline_started(budget_usd=2.0))
        await bus.emit(_dispatch_completed(cost_usd=1.6))  # 1.6 / 2.0 = 80%

        assert len(captured) == 1
        assert captured[0].budget_usd == pytest.approx(2.0)
        assert captured[0].percent == pytest.approx(80.0)


class TestBackToBackRegression:
    """Ticket acceptance #3 — two back-to-back pipelines each independently
    emit budget warnings AND exceeded events."""

    async def test_two_back_to_back_pipelines_each_warn_and_exceed(self, bus: EventBus) -> None:
        warnings: list[CostBudgetWarning] = []
        exceeded: list[CostBudgetExceeded] = []

        async def capture(event: BonfireEvent) -> None:
            if isinstance(event, CostBudgetWarning):
                warnings.append(event)
            elif isinstance(event, CostBudgetExceeded):
                exceeded.append(event)

        bus.subscribe_all(capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        for _ in range(2):
            await bus.emit(_pipeline_started(budget_usd=10.0))
            # One large dispatch crosses both 80% and 100%.
            await bus.emit(_dispatch_completed(cost_usd=12.0))

        assert len(warnings) == 2
        assert len(exceeded) == 2


class TestMalformedBudgetSurfacedLoud:
    """Elegance Law (contract A) — a malformed ``budget_usd`` on
    ``PipelineStarted`` is a boundary violation. It is surfaced as a TYPED
    ``ValidationError`` carrying context, never silently accepted into the
    threshold math (which would make ``percent`` NaN and silently swallow
    every future warning).
    """

    async def test_nan_budget_raises_typed_validation_error(self, bus: EventBus) -> None:
        tracker = CostTracker(budget_usd=10.0, bus=bus)

        with pytest.raises(ValidationError) as excinfo:
            await tracker._on_pipeline_started(_pipeline_started(budget_usd=math.nan))

        err = excinfo.value
        assert err.code == "validation"
        assert err.context.get("budget_usd") != err.context.get("budget_usd") or math.isnan(
            err.context["budget_usd"]  # type: ignore[arg-type]
        )
        assert err.context.get("session_id") == _SESSION

    async def test_negative_budget_raises_typed_validation_error(self, bus: EventBus) -> None:
        tracker = CostTracker(budget_usd=10.0, bus=bus)

        with pytest.raises(ValidationError) as excinfo:
            await tracker._on_pipeline_started(_pipeline_started(budget_usd=-5.0))

        err = excinfo.value
        assert err.context.get("budget_usd") == -5.0
        assert err.context.get("plan_name") == "dual"

    async def test_zero_budget_is_allowed(self, bus: EventBus) -> None:
        """A zero budget is a legitimate 'no spend allowed' contract — the
        existing ``budget_usd <= 0`` branch treats it as percent=inf. It must
        NOT raise; only NaN/negative are boundary violations.
        """
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        # Should not raise.
        await bus.emit(_pipeline_started(budget_usd=0.0))
        assert tracker.total_cost_usd == pytest.approx(0.0)
