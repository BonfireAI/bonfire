# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract — Wave 11 Lane D: outer-exception PipelineFailed emit.

Background
----------
``src/bonfire/engine/pipeline.py`` ``PipelineEngine.run`` wraps the inner
loop in a try/except. The except branch returns a failed ``PipelineResult``
but does NOT emit ``PipelineFailed``. Sage D5's "a raising gate becomes
pipeline failure" path therefore silently bypasses every bus observer:
``CostLedgerConsumer`` never persists a ledger row, ``DisplayConsumer``
never shows the halt, ``XPConsumer`` never penalizes the run.

Wave 10 Lane A + Wave 11 Lane A restored bus-vs-``PipelineResult`` parity
on every other halt branch (sequential failure, parallel failure,
budget exceeded, gate failure). The outer-exception branch is the last
remaining hole — closing it restores the umbrella invariant: every
``PipelineResult.success == False`` corresponds to exactly one
``PipelineFailed`` event on the bus.

Fix
---
The outer ``except`` branch emits ``PipelineFailed`` populated with the
Wave 11 Lane A schema additions:

* ``failed_handler`` — the stage name where the exception fired (when
  determinable), else a sentinel.
* ``duration_seconds`` — wall-clock from start to exception.
* ``stages_completed`` — count of stages in ``stages_done`` (best-effort;
  may be ``0`` when the exception fired before any stage completed).

``pyproject.toml`` sets ``asyncio_mode = "auto"`` so async tests are
discovered without the ``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

from typing import Any

import pytest

from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope
from bonfire.models.events import BonfireEvent, PipelineFailed
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[BonfireEvent] = []

    async def __call__(self, event: BonfireEvent) -> None:
        self.events.append(event)

    def of_type(self, event_cls: type) -> list[BonfireEvent]:
        return [e for e in self.events if type(e) is event_cls]


class _BackendThatBlowsUp:
    """Backend whose ``execute`` blows up with an uncaught exception during
    a context-build step that lives outside the engine's inner per-stage
    try/except. We trigger the outer-exception branch by raising from
    ``health_check`` or by feeding a malformed dependency.
    """

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        raise RuntimeError("backend wire-up failed catastrophically")

    async def health_check(self) -> bool:
        return True


def _make_engine(*, backend: Any, bus: EventBus) -> PipelineEngine:
    return PipelineEngine(backend=backend, bus=bus, config=PipelineConfig())


# ===========================================================================
# 1. Outer-exception branch emits PipelineFailed
# ===========================================================================


class TestOuterExceptionEmitsPipelineFailed:
    """When ``PipelineEngine._run_inner`` raises (anything not caught by an
    inner per-stage try/except), the outer ``except`` in ``run`` must emit
    a ``PipelineFailed`` event before returning the failed result.

    Today: the outer except returns ``PipelineResult(success=False, ...)``
    silently. Bus observers see nothing. ``CostLedgerConsumer`` never
    persists. ``DisplayConsumer`` never renders the halt.
    """

    async def test_outer_exception_emits_pipeline_failed(self) -> None:
        """A pipeline whose run raises (anywhere in _run_inner) must emit
        ``PipelineFailed`` on the bus."""
        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)

        # Patch _run_inner to raise a deterministic error.
        engine = _make_engine(backend=_BackendThatBlowsUp(), bus=bus)

        async def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("inner pipeline blew up")

        engine._run_inner = _raise  # type: ignore[method-assign]

        plan = WorkflowPlan(
            name="outer-exc",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )
        result = await engine.run(plan)

        # The result already reports failure.
        assert result.success is False
        assert "inner pipeline blew up" in result.error

        # And — the part this lane closes — the bus saw the halt.
        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1, (
            "Outer-exception path must emit exactly one PipelineFailed event. "
            f"Got {len(failed_events)} (events: "
            f"{[type(e).__name__ for e in collector.events]})."
        )


# ===========================================================================
# 2. The emitted event populates Lane A's new fields
# ===========================================================================


class TestOuterExceptionEmitFieldsPopulated:
    """The ``PipelineFailed`` event emitted on the outer-exception path
    must populate the three Wave 11 Lane A schema additions:

      * ``failed_handler``  — naming string (not the legacy ``None``)
      * ``duration_seconds`` — wall-clock; > 0.0 because the run actually ran
      * ``stages_completed`` — best-effort progress count (>= 0)

    Defaults stay the same on the SCHEMA (round-trip compat); the contract
    here is that the engine's OUTER-EXCEPTION EMIT SITE populates them.
    """

    async def test_failed_handler_is_populated_with_a_string(self) -> None:
        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        engine = _make_engine(backend=_BackendThatBlowsUp(), bus=bus)

        async def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("kaboom")

        engine._run_inner = _raise  # type: ignore[method-assign]

        plan = WorkflowPlan(
            name="outer-exc",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )
        await engine.run(plan)

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]

        # ``failed_handler`` must be a non-empty string so operators
        # reading the bus can tell the halt came from the outer path
        # (vs the bounce-target path that names a specific handler).
        assert emitted.failed_handler is not None, (
            "Outer-exception PipelineFailed must populate failed_handler "
            "(use a sentinel like '__outer__' when the handler name cannot "
            "be determined; do not leave None — operators need a signal "
            "distinguishing outer-exception halts from bounce-target halts)."
        )
        assert isinstance(emitted.failed_handler, str)
        assert emitted.failed_handler != ""

    async def test_duration_seconds_is_positive(self) -> None:
        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        engine = _make_engine(backend=_BackendThatBlowsUp(), bus=bus)

        async def _raise(*args: Any, **kwargs: Any) -> None:
            # Give the wall clock a measurable delta.
            import asyncio

            await asyncio.sleep(0.001)
            raise RuntimeError("kaboom")

        engine._run_inner = _raise  # type: ignore[method-assign]

        plan = WorkflowPlan(
            name="outer-exc",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )
        result = await engine.run(plan)

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]

        # Symmetric with PipelineResult.duration_seconds (both populated
        # from time.monotonic() - start). Must be > 0 (the run ran).
        assert emitted.duration_seconds > 0.0, (
            "Outer-exception PipelineFailed.duration_seconds must be > 0; "
            f"got {emitted.duration_seconds}"
        )
        assert emitted.duration_seconds == pytest.approx(result.duration_seconds, abs=0.05), (
            "Outer-exception PipelineFailed.duration_seconds must match "
            "PipelineResult.duration_seconds within tolerance: "
            f"emitted={emitted.duration_seconds}, result={result.duration_seconds}"
        )

    async def test_stages_completed_is_non_negative_int(self) -> None:
        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        engine = _make_engine(backend=_BackendThatBlowsUp(), bus=bus)

        async def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("kaboom")

        engine._run_inner = _raise  # type: ignore[method-assign]

        plan = WorkflowPlan(
            name="outer-exc",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )
        await engine.run(plan)

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]

        # Best-effort progress count. Default (and most likely value when
        # the exception fires before any stage completes) is 0; the
        # contract is that the field is a non-negative int.
        assert isinstance(emitted.stages_completed, int)
        assert emitted.stages_completed >= 0


# ===========================================================================
# 3. Umbrella: every PipelineResult.success == False corresponds to ONE
#    PipelineFailed event on the bus, including the outer-exception path.
# ===========================================================================


class TestOuterExceptionBusResultParity:
    """Closing the outer-exception emit hole restores the umbrella
    invariant: ``PipelineResult.success is False`` <=> exactly one
    ``PipelineFailed`` on the bus."""

    async def test_failure_always_emits_exactly_one_pipeline_failed(self) -> None:
        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        engine = _make_engine(backend=_BackendThatBlowsUp(), bus=bus)

        async def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("outer halt")

        engine._run_inner = _raise  # type: ignore[method-assign]

        plan = WorkflowPlan(
            name="outer",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )
        result = await engine.run(plan)
        assert result.success is False

        failed = collector.of_type(PipelineFailed)
        assert len(failed) == 1, (
            "Bus-vs-result parity: PipelineResult.success==False MUST "
            "correspond to exactly one PipelineFailed on the bus, including "
            "on the outer-exception path. Lane D closes this gap."
        )
