# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract — Wave 11 Lane D: shared handler-dispatch helper.

Background
----------
``src/bonfire/handlers/sage_correction_bounce.py`` calls
``backend.execute()`` directly inside ``_call_backend_execute``. That bypasses
``dispatch.runner.execute_with_retry`` and breaks two invariants the rest of
the framework relies on:

1.  **Event emission.** No ``DispatchStarted`` / ``DispatchCompleted`` /
    ``DispatchFailed`` events fire from the handler path, so every bus
    observer that subscribed to the dispatch lifecycle (``CostTracker``,
    ``CostLedgerConsumer``, ``KnowledgeIngestConsumer``, the budget
    watchdog) sees nothing when Sage spends money on a correction cycle.

2.  **Cost stamping.** ``_build_envelope_from_cycle_outcome`` returns an
    envelope with ``cost_usd = 0.0`` because it never reads
    ``backend_result.cost_usd``. The dollars Sage burns are invisible to
    ``PipelineResult.total_cost_usd``.

Together these two defects break the **bus-vs-PipelineResult parity
invariant** Wave 10 + Wave 11 Lane A restored on every other halt branch.

Fix
---
Introduce a shared helper ``bonfire.dispatch.handler_runner.run_handler_dispatch``
that emits the three dispatch events around ``backend.execute()`` and stamps
the backend result's cost onto the returned envelope. Refactor
``sage_correction_bounce`` to use it. ``_build_envelope_from_cycle_outcome``
threads the cost through onto the returned envelope so the engine
accumulator sees the real spend.

``pyproject.toml`` sets ``asyncio_mode = "auto"`` so async tests are
discovered without the ``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bonfire.events.bus import EventBus
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    DispatchCompleted,
    DispatchFailed,
    DispatchStarted,
)
from bonfire.models.plan import StageSpec
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Shared mocks
# ---------------------------------------------------------------------------


class _EventCollector:
    """Bus subscriber that records every event in order."""

    def __init__(self) -> None:
        self.events: list[BonfireEvent] = []

    async def __call__(self, event: BonfireEvent) -> None:
        self.events.append(event)

    def of_type(self, event_cls: type) -> list[BonfireEvent]:
        return [e for e in self.events if type(e) is event_cls]


class _CostBearingBackend:
    """Backend that returns an envelope with a configured cost_usd."""

    def __init__(self, *, cost: float = 0.42, fail: bool = False) -> None:
        self._cost = cost
        self._fail = fail
        self.calls: list[Envelope] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append(envelope)
        if self._fail:
            return envelope.model_copy(
                update={
                    "status": TaskStatus.FAILED,
                    "error": ErrorDetail(error_type="agent", message="boom"),
                    "cost_usd": self._cost,
                }
            )
        return envelope.with_result("ok", cost_usd=self._cost)

    async def health_check(self) -> bool:
        return True


class _ExplodingBackend:
    """Backend whose ``execute`` raises a RuntimeError."""

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        raise RuntimeError("backend exploded")

    async def health_check(self) -> bool:
        return True


def _make_options() -> DispatchOptions:
    return DispatchOptions(
        model="claude-test",
        max_turns=1,
        max_budget_usd=10.0,
        cwd="",
        tools=[],
        role="synthesizer",
    )


def _make_envelope() -> Envelope:
    return Envelope(task="lane D test", agent_name="sage-correction")


# ===========================================================================
# 1. Helper module exists with a callable run_handler_dispatch entrypoint
# ===========================================================================


class TestHandlerDispatchHelperExists:
    """The shared helper module ``bonfire.dispatch.handler_runner`` must exist
    with a public ``run_handler_dispatch`` async function. Naming matches
    existing dispatch-module conventions (``runner.execute_with_retry``).
    """

    def test_module_importable(self) -> None:
        """``bonfire.dispatch.handler_runner`` imports cleanly."""
        import bonfire.dispatch.handler_runner  # noqa: F401

    def test_run_handler_dispatch_is_callable(self) -> None:
        """The module exposes ``run_handler_dispatch``."""
        from bonfire.dispatch.handler_runner import run_handler_dispatch

        assert callable(run_handler_dispatch)


# ===========================================================================
# 2. Helper emits the three dispatch events around backend.execute()
# ===========================================================================


class TestHelperEmitsDispatchEvents:
    """``run_handler_dispatch`` must emit ``DispatchStarted`` BEFORE calling
    ``backend.execute`` and ``DispatchCompleted`` AFTER a successful call.
    On exception, it emits ``DispatchFailed`` and re-raises.
    """

    async def test_emits_started_then_completed_on_success(self) -> None:
        from bonfire.dispatch.handler_runner import run_handler_dispatch

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _CostBearingBackend(cost=0.37)

        await run_handler_dispatch(
            backend=backend,
            envelope=_make_envelope(),
            options=_make_options(),
            event_bus=bus,
        )

        started = collector.of_type(DispatchStarted)
        completed = collector.of_type(DispatchCompleted)
        failed = collector.of_type(DispatchFailed)

        assert len(started) == 1, f"Expected exactly one DispatchStarted, got {len(started)}"
        assert len(completed) == 1, f"Expected exactly one DispatchCompleted, got {len(completed)}"
        assert len(failed) == 0, "DispatchFailed must NOT fire on success"

        # Ordering: started must come before completed.
        started_idx = collector.events.index(started[0])
        completed_idx = collector.events.index(completed[0])
        assert started_idx < completed_idx

    async def test_completed_event_carries_backend_cost(self) -> None:
        """``DispatchCompleted.cost_usd`` must mirror ``backend_result.cost_usd``.

        This is the parity invariant — the bus observer side must see the
        same dollars the handler/engine accumulator sees.
        """
        from bonfire.dispatch.handler_runner import run_handler_dispatch

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _CostBearingBackend(cost=0.73)

        await run_handler_dispatch(
            backend=backend,
            envelope=_make_envelope(),
            options=_make_options(),
            event_bus=bus,
        )

        completed = collector.of_type(DispatchCompleted)
        assert len(completed) == 1
        emitted: DispatchCompleted = completed[0]  # type: ignore[assignment]
        assert emitted.cost_usd == pytest.approx(0.73), (
            f"DispatchCompleted.cost_usd must equal backend_result.cost_usd: "
            f"got {emitted.cost_usd}, expected 0.73"
        )

    async def test_emits_failed_on_exception_and_reraises(self) -> None:
        """When ``backend.execute`` raises, the helper must emit
        ``DispatchFailed`` AND re-raise so the handler's existing
        try/except (mirroring the runner's ``execute_with_retry``
        semantics) can route the failure."""
        from bonfire.dispatch.handler_runner import run_handler_dispatch

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _ExplodingBackend()

        with pytest.raises(RuntimeError, match="backend exploded"):
            await run_handler_dispatch(
                backend=backend,
                envelope=_make_envelope(),
                options=_make_options(),
                event_bus=bus,
            )

        assert len(collector.of_type(DispatchStarted)) == 1
        assert len(collector.of_type(DispatchCompleted)) == 0
        assert len(collector.of_type(DispatchFailed)) == 1

    async def test_helper_tolerates_missing_bus(self) -> None:
        """Helper must no-op event emission when ``event_bus is None``
        (so handlers wired without a bus still run)."""
        from bonfire.dispatch.handler_runner import run_handler_dispatch

        backend = _CostBearingBackend(cost=0.10)
        # No raise expected.
        result = await run_handler_dispatch(
            backend=backend,
            envelope=_make_envelope(),
            options=_make_options(),
            event_bus=None,
        )
        # Helper returns the backend result unchanged on success.
        assert result.cost_usd == pytest.approx(0.10)


# ===========================================================================
# 3. sage_correction_bounce uses the helper (no raw backend.execute)
# ===========================================================================


class TestSageCorrectionBouncesThroughHelper:
    """The Sage correction handler must route its backend dispatch through
    the shared helper. A successful correction-cycle dispatch must emit the
    three dispatch events through the injected event bus.
    """

    async def test_handler_emits_dispatch_events_through_bus(self) -> None:
        """Wiring an event bus into the handler must cause the helper's
        events to land on it during a correction cycle."""
        from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)

        # Backend returns a structured backend_result whose cost is non-zero.
        backend_result = MagicMock(spec=Envelope)
        backend_result.cost_usd = 0.55
        backend_result.metadata = {"correction_commit_sha": "abc1234567890"}
        backend_result.result = ""

        backend = AsyncMock()
        backend.execute = AsyncMock(return_value=backend_result)

        # Cherry-pick + pytest re-verify succeed.
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        reverify_result = MagicMock()
        reverify_result.returncode = 0
        pytest_runner.run = AsyncMock(return_value=reverify_result)

        # Classifier returns SAGE_UNDER_MARKED so the cycle actually runs.
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="sage_under_marked")

        handler = SageCorrectionBounceHandler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
            event_bus=bus,
        )

        stage = StageSpec(
            name="sage_correction_bounce",
            agent_name="sage-correction",
            role="synthesizer",
            handler_name="sage_correction_bounce",
        )
        env = Envelope(task="t", agent_name="sage-correction")

        await handler.handle(stage, env, {"warrior": "1 failed"})

        started = collector.of_type(DispatchStarted)
        completed = collector.of_type(DispatchCompleted)
        assert len(started) == 1, (
            "SageCorrectionBounceHandler must emit DispatchStarted on its "
            "correction-cycle dispatch (via the shared helper)."
        )
        assert len(completed) == 1, (
            "SageCorrectionBounceHandler must emit DispatchCompleted on its "
            "correction-cycle dispatch."
        )

    async def test_handler_emits_dispatch_failed_on_backend_exception(self) -> None:
        """When the backend raises, DispatchFailed must reach the bus."""
        from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)

        backend = AsyncMock()
        backend.execute = AsyncMock(side_effect=RuntimeError("kaboom"))

        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="sage_under_marked")

        handler = SageCorrectionBounceHandler(
            backend=backend,
            classifier=classifier,
            git_workflow=MagicMock(),
            pytest_runner=AsyncMock(),
            event_bus=bus,
        )

        stage = StageSpec(
            name="sage_correction_bounce",
            agent_name="sage-correction",
            role="synthesizer",
            handler_name="sage_correction_bounce",
        )
        env = Envelope(task="t", agent_name="sage-correction")

        # Handler swallows the exception per the StageHandler contract.
        await handler.handle(stage, env, {"warrior": "1 failed"})

        assert len(collector.of_type(DispatchStarted)) == 1
        assert len(collector.of_type(DispatchFailed)) == 1


# ===========================================================================
# 4. _build_envelope_from_cycle_outcome stamps the backend's cost
# ===========================================================================


class TestSageOutcomeEnvelopeCarriesCost:
    """The envelope returned by ``handle()`` on a successful correction
    cycle must carry ``cost_usd`` equal to the cost the backend reported.

    Today the returned envelope has ``cost_usd=0.0`` because
    ``_build_envelope_from_cycle_outcome`` never reads
    ``backend_result.cost_usd``. Engine accumulator
    (``pipeline.py:565``: ``cumulative_iteration_cost += result_env.cost_usd``)
    therefore never counts Sage correction spend.
    """

    async def test_envelope_cost_equals_backend_cost_on_corrected(self) -> None:
        from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler

        backend_result = MagicMock(spec=Envelope)
        backend_result.cost_usd = 0.91
        backend_result.metadata = {"correction_commit_sha": "deadbeefcafe"}
        backend_result.result = ""

        backend = AsyncMock()
        backend.execute = AsyncMock(return_value=backend_result)

        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        reverify_result = MagicMock()
        reverify_result.returncode = 0
        pytest_runner.run = AsyncMock(return_value=reverify_result)

        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="sage_under_marked")

        handler = SageCorrectionBounceHandler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )

        stage = StageSpec(
            name="sage_correction_bounce",
            agent_name="sage-correction",
            role="synthesizer",
            handler_name="sage_correction_bounce",
        )
        env = Envelope(task="t", agent_name="sage-correction")

        result_env = await handler.handle(stage, env, {"warrior": "1 failed"})

        assert result_env.cost_usd == pytest.approx(0.91), (
            "SageCorrectionBounceHandler must stamp the backend's cost_usd "
            "onto the returned envelope so the engine accumulator counts "
            f"Sage correction spend: got {result_env.cost_usd}, expected 0.91"
        )


# ===========================================================================
# 5. Audit: no rogue backend.execute() outside the helper + runner
# ===========================================================================


class TestNoRawBackendExecuteOutsideAllowedSites:
    """Grep audit: the only ``backend.execute(`` call sites in
    ``src/bonfire/`` must be inside the helper module
    (``dispatch/handler_runner.py``) or the runner
    (``dispatch/runner.py``). Any other site is the bus-parity bug we
    just closed re-opening.
    """

    def test_grep_reports_only_allowed_call_sites(self) -> None:
        from pathlib import Path

        src_root = Path(__file__).resolve().parents[2] / "src" / "bonfire"
        assert src_root.is_dir(), f"src tree not found at {src_root}"

        allowed = {
            "dispatch/runner.py",
            "dispatch/handler_runner.py",
        }

        offenders: list[str] = []
        for py in src_root.rglob("*.py"):
            text = py.read_text()
            if "backend.execute(" not in text:
                continue
            rel = py.relative_to(src_root).as_posix()
            if rel in allowed:
                continue
            offenders.append(rel)

        assert offenders == [], (
            f"Found raw `backend.execute(` outside the helper / runner: "
            f"{offenders}. All handler dispatches must route through "
            f"`bonfire.dispatch.handler_runner.run_handler_dispatch`."
        )


# ===========================================================================
# 6. Helper threads the BACKEND_RESULT cost back to the caller
# ===========================================================================


class TestHelperReturnsCostStampedResult:
    """``run_handler_dispatch`` returns the envelope it received from the
    backend with the cost preserved. The handler can then propagate that
    cost into its returned envelope without doing the bookkeeping itself.
    """

    async def test_returned_envelope_preserves_backend_cost(self) -> None:
        from bonfire.dispatch.handler_runner import run_handler_dispatch

        backend = _CostBearingBackend(cost=0.21)
        result: Any = await run_handler_dispatch(
            backend=backend,
            envelope=_make_envelope(),
            options=_make_options(),
            event_bus=None,
        )
        # Whatever the helper returns, its cost_usd attribute must equal
        # the backend's charge.
        assert result.cost_usd == pytest.approx(0.21)
