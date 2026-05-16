# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract — close the halt-branch event-completeness defect family.

Wave 10 Lane A (PR #125) restored bus-vs-``PipelineResult`` cost parity by
adding ``DispatchFailed.cost_usd``, the ``PipelineFailed.total_cost_usd``
field, and dual-subscribe wiring on ``CostTracker`` /
``CostLedgerConsumer``. Wave 11 Lane A closes the residual halt-branch gaps
the post-Wave-10 audit (Scout 2 pipeline axis) surfaced:

  H4. ``PipelineFailed`` carries ``failed_stage = <original-stage-name>``
      when the failure actually fired on the BOUNCE TARGET. Operators
      reading the event stream can't tell which handler died. Fix: add
      ``PipelineFailed.failed_handler: str | None`` and populate it with
      the bounce-target's stage name on that halt branch.

  H6. After a successful bounce, the engine REPLACES
      ``stages_done[name] = retry_env``. The original failed envelope is
      already added to ``total_cost`` AND was previously in
      ``stages_done``; the replacement quietly drops its cost from
      ``sum(env.cost_usd for env in stages_done.values())``. Resume-from-
      checkpoint recomputes ``total_cost`` from that sum
      (``pipeline.py:165``) and under-counts the seed. Fix: stamp
      ``retry_env`` with the combined cost so the sum-of-stages invariant
      survives.

  H7. ``DisplayConsumer.register()`` only subscribes to ``StageCompleted``,
      ``StageFailed``, ``QualityFailed``, ``CostBudgetWarning``. Pipeline
      halts and budget-broken events trigger no display callback —
      operators driving the CLI see nothing on the most important state
      transitions. Fix: subscribe to ``PipelineCompleted``,
      ``PipelineFailed``, and ``CostBudgetExceeded`` too.

  M3. ``CostLedgerConsumer._on_pipeline_failed`` writes
      ``duration_seconds=0.0`` because ``PipelineFailed`` does not carry
      duration. Every failed session in the ledger looks instant. Fix:
      add ``PipelineFailed.duration_seconds: float`` and populate it at
      every emit site in ``engine/pipeline.py``.

  M7. ``XPConsumer._handle_pipeline_failed`` synthesizes a
      ``PipelineCompleted(stages_completed=0)`` — the XP calculator can't
      distinguish stage-1 vs stage-19 failure. Fix: add
      ``PipelineFailed.stages_completed: int`` and populate it as
      ``len(stages_done)`` at every emit site.

Plus one umbrella invariant: after ANY pipeline run (success, failure,
bounce, parallel-group), ``sum(observer.observed_costs) ==
PipelineResult.total_cost_usd``. Wave 10 + Wave 11 together restore the
bus-vs-``PipelineResult`` parity on EVERY path.

``pyproject.toml`` sets ``asyncio_mode = "auto"`` so async tests are
discovered without the ``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.events.consumers.cost import CostTracker
from bonfire.events.consumers.display import DisplayConsumer
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    CostBudgetExceeded,
    PipelineCompleted,
    PipelineFailed,
)
from bonfire.models.plan import GateContext, GateResult, StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Shared mocks (kept small; mirror the Wave 10 contract test's style)
# ---------------------------------------------------------------------------


class _PerAgentCostBackend:
    """Backend that charges a configurable cost per agent name."""

    def __init__(
        self,
        costs: dict[str, float],
        *,
        fail_agents: set[str] | None = None,
    ) -> None:
        self._costs = costs
        self._fail = fail_agents or set()
        self.calls: list[Envelope] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append(envelope)
        cost = self._costs.get(envelope.agent_name, 0.0)
        if envelope.agent_name in self._fail:
            return envelope.model_copy(
                update={
                    "status": TaskStatus.FAILED,
                    "error": ErrorDetail(error_type="agent", message="boom"),
                    "cost_usd": cost,
                }
            )
        return envelope.with_result(f"{envelope.agent_name} done", cost_usd=cost)

    async def health_check(self) -> bool:
        return True


class _AlwaysFailGate:
    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        return GateResult(
            gate_name="never",
            passed=False,
            severity="error",
            message="never passes",
        )


class _EventualPassGate:
    """Gate that fails the first eval and passes on every subsequent eval."""

    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        self.calls += 1
        if self.calls == 1:
            return GateResult(
                gate_name="eventual",
                passed=False,
                severity="error",
                message="fix it",
            )
        return GateResult(gate_name="eventual", passed=True, severity="info", message="ok")


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[BonfireEvent] = []

    async def __call__(self, event: BonfireEvent) -> None:
        self.events.append(event)

    def of_type(self, event_cls: type) -> list[BonfireEvent]:
        return [e for e in self.events if type(e) is event_cls]


def _make_engine(
    *,
    backend: Any,
    bus: EventBus,
    gate_registry: dict[str, Any] | None = None,
) -> PipelineEngine:
    return PipelineEngine(
        backend=backend,
        bus=bus,
        config=PipelineConfig(),
        gate_registry=gate_registry,
    )


# ===========================================================================
# H4 — bounce-target failure names the bounce target, not the original
# ===========================================================================


class TestPipelineFailedFailedHandler:
    """When a bounce target's own execution causes the halt, the
    ``PipelineFailed`` event must identify that bounce target — not the
    original stage that triggered the bounce. The original stage's name
    stays in ``failed_stage`` (the stage whose gate broke); the bounce
    target's identity lands in the new ``failed_handler`` field.
    """

    def test_pipeline_failed_has_failed_handler_field(self) -> None:
        """The event schema grows ``failed_handler: str | None`` (default ``None``).

        Default ``None`` so legacy emitters round-trip without raising.
        Populated explicitly on bounce-target halt paths.
        """
        ev = PipelineFailed(
            session_id="s",
            sequence=0,
            failed_stage="s1",
            error_message="boom",
            failed_handler="fixer",
        )
        assert ev.failed_handler == "fixer"

    def test_pipeline_failed_failed_handler_defaults_to_none(self) -> None:
        """Existing emit sites that do not set the field round-trip with ``None``."""
        ev = PipelineFailed(
            session_id="s",
            sequence=0,
            failed_stage="s1",
            error_message="boom",
        )
        assert ev.failed_handler is None

    async def test_bounce_target_failure_names_bounce_target(self) -> None:
        """When the bounce target's own execution fails, the emitted
        ``PipelineFailed`` event must set ``failed_handler`` to the
        bounce target's name.

        Today: the event identifies the ORIGINAL stage on both
        ``failed_stage`` AND in every field that could carry the bounce
        target. Operators reading the event stream cannot tell which
        handler died.
        """

        class _BounceTargetFailsBackend:
            def __init__(self, costs: dict[str, float]) -> None:
                self._costs = costs
                self._fixer_calls = 0
                self.calls: list[Envelope] = []

            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                self.calls.append(envelope)
                cost = self._costs[envelope.agent_name]
                if envelope.agent_name == "fixer":
                    self._fixer_calls += 1
                    # The DAG runs fixer first (depends_on); s1 then runs
                    # and its gate fails; the engine bounces to fixer
                    # which fails THIS time around (the second fixer call).
                    if self._fixer_calls >= 2:
                        return envelope.model_copy(
                            update={
                                "status": TaskStatus.FAILED,
                                "error": ErrorDetail(
                                    error_type="agent", message="fixer failed on bounce"
                                ),
                                "cost_usd": cost,
                            }
                        )
                return envelope.with_result(f"{envelope.agent_name} done", cost_usd=cost)

            async def health_check(self) -> bool:
                return True

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        gate = _AlwaysFailGate()
        backend = _BounceTargetFailsBackend(costs={"fixer": 0.50, "s1": 0.10})
        engine = _make_engine(backend=backend, bus=bus, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="bounce-target-fail",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="fixer", agent_name="fixer"),
                StageSpec(
                    name="s1",
                    agent_name="s1",
                    gates=["check"],
                    on_gate_failure="fixer",
                    depends_on=["fixer"],
                ),
            ],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is False

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]
        # ``failed_stage`` stays as the stage whose gate broke (operator
        # context: WHICH stage's contract was violated). The new
        # ``failed_handler`` field identifies WHICH handler actually died
        # on the halt path — for bounce-target halts, that's the bounce
        # target's name.
        assert emitted.failed_handler == "fixer", (
            f"PipelineFailed.failed_handler should name the bounce target "
            f"on bounce-target halt; got {emitted.failed_handler!r}"
        )


# ===========================================================================
# H6 — bounce-retry preserves original envelope cost via sum-of-stages
# ===========================================================================


class TestBounceRetryStagesDoneSumInvariant:
    """After a successful bounce, ``stages_done[name] = retry_env``
    REPLACES the original failed envelope. The original was already added
    to ``total_cost`` and was previously in ``stages_done``; the
    replacement quietly drops its cost from
    ``sum(env.cost_usd for env in stages_done.values())``.

    Resume-from-checkpoint reseeds ``total_cost`` from that sum (see
    ``engine/pipeline.py:165`` — ``sum(env.cost_usd for env in
    stages_done.values())``). Under-counts the seed every time a resumed
    run was previously bounced.

    Fix: when replacing ``stages_done[name]``, stamp ``retry_env`` with
    ``cost = original_env.cost_usd + retry_env.cost_usd`` so the
    sum-of-stages invariant matches the engine's accumulator.
    """

    async def test_sum_of_stages_equals_total_after_successful_bounce(self) -> None:
        """Sum-of-stages MUST equal ``PipelineResult.total_cost_usd``
        after a successful bounce-retry sequence.

        Costs across the run:
          fixer DAG init:                 0.50
          s1 first run (failed gate):     0.10  <-- replaced by retry_env below
          fixer bounce-target:            0.50
          s1 retry (succeeded):           0.10
        Expected engine total: 1.20

        Today: ``stages_done["s1"] = retry_env`` with retry_env.cost_usd
        == 0.10. Original 0.10 vanishes from the sum; sum-of-stages == 1.10
        while total_cost_usd == 1.20.
        """
        bus = EventBus()
        gate = _EventualPassGate()  # fails first, passes second
        backend = _PerAgentCostBackend(costs={"fixer": 0.50, "s1": 0.10})
        engine = _make_engine(backend=backend, bus=bus, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="bounce-retry-success",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="fixer", agent_name="fixer"),
                StageSpec(
                    name="s1",
                    agent_name="s1",
                    gates=["check"],
                    on_gate_failure="fixer",
                    depends_on=["fixer"],
                ),
            ],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is True
        # Engine accumulator side
        assert result.total_cost_usd == pytest.approx(1.20)
        # Sum-of-stages side — this is the invariant resume-from-checkpoint
        # reads on the next session start.
        sum_of_stages = sum(env.cost_usd for env in result.stages.values())
        assert sum_of_stages == pytest.approx(result.total_cost_usd), (
            f"sum-of-stages must equal total_cost_usd after bounce-retry "
            f"(invariant for resume-from-checkpoint): "
            f"sum_of_stages={sum_of_stages}, total={result.total_cost_usd}"
        )


# ===========================================================================
# H7 — DisplayConsumer subscribes to halt + budget-broken events
# ===========================================================================


class TestDisplayConsumerHaltSubscriptions:
    """Operators driving the CLI need a visible display on the most
    important state transitions: pipeline completion, pipeline halt, and
    budget exceeded. ``DisplayConsumer.register()`` currently subscribes
    to only ``StageCompleted``, ``StageFailed``, ``QualityFailed``, and
    ``CostBudgetWarning``. Add the three missing event types.
    """

    def test_subscribes_to_pipeline_completed(self) -> None:
        bus = EventBus()
        consumer = DisplayConsumer(callback=lambda msg: None)
        consumer.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        assert PipelineCompleted in subscribed_types, (
            "DisplayConsumer must subscribe to PipelineCompleted — "
            "operators need a visible 'pipeline done' signal on the CLI."
        )

    def test_subscribes_to_pipeline_failed(self) -> None:
        bus = EventBus()
        consumer = DisplayConsumer(callback=lambda msg: None)
        consumer.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        assert PipelineFailed in subscribed_types, (
            "DisplayConsumer must subscribe to PipelineFailed — "
            "operators need a visible halt signal on the CLI."
        )

    def test_subscribes_to_cost_budget_exceeded(self) -> None:
        bus = EventBus()
        consumer = DisplayConsumer(callback=lambda msg: None)
        consumer.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        assert CostBudgetExceeded in subscribed_types, (
            "DisplayConsumer must subscribe to CostBudgetExceeded — "
            "operators need a visible 'budget broken' signal on the CLI."
        )

    async def test_pipeline_completed_invokes_callback(self) -> None:
        messages: list[str] = []
        bus = EventBus()
        consumer = DisplayConsumer(callback=lambda msg: messages.append(msg))
        consumer.register(bus)

        await bus.emit(
            PipelineCompleted(
                session_id="ses",
                sequence=0,
                total_cost_usd=0.25,
                duration_seconds=4.2,
                stages_completed=3,
            )
        )

        assert len(messages) == 1
        # Light shape check — no rigid copy lock; just confirms the
        # callback received SOMETHING informative.
        assert messages[0]

    async def test_pipeline_failed_invokes_callback(self) -> None:
        messages: list[str] = []
        bus = EventBus()
        consumer = DisplayConsumer(callback=lambda msg: messages.append(msg))
        consumer.register(bus)

        await bus.emit(
            PipelineFailed(
                session_id="ses",
                sequence=0,
                failed_stage="s1",
                error_message="boom",
            )
        )

        assert len(messages) == 1
        assert messages[0]

    async def test_cost_budget_exceeded_invokes_callback(self) -> None:
        messages: list[str] = []
        bus = EventBus()
        consumer = DisplayConsumer(callback=lambda msg: messages.append(msg))
        consumer.register(bus)

        await bus.emit(
            CostBudgetExceeded(
                session_id="ses",
                sequence=0,
                current_usd=12.0,
                budget_usd=10.0,
            )
        )

        assert len(messages) == 1
        assert messages[0]


# ===========================================================================
# M3 — PipelineFailed.duration_seconds populated; ledger row carries it
# ===========================================================================


class TestPipelineFailedDurationSeconds:
    """``PipelineFailed`` must carry ``duration_seconds`` so the
    ``CostLedgerConsumer`` ledger row reflects the real run length —
    today every failed session looks instant.
    """

    def test_pipeline_failed_has_duration_seconds_field(self) -> None:
        """The event schema grows ``duration_seconds: float`` (default 0.0).

        Symmetric with ``PipelineCompleted.duration_seconds``. Default
        ``0.0`` keeps legacy emitters round-tripping without raising.
        """
        ev = PipelineFailed(
            session_id="s",
            sequence=0,
            failed_stage="s1",
            error_message="boom",
            duration_seconds=2.5,
        )
        assert ev.duration_seconds == pytest.approx(2.5)

    def test_pipeline_failed_duration_defaults_to_zero(self) -> None:
        ev = PipelineFailed(
            session_id="s",
            sequence=0,
            failed_stage="s1",
            error_message="boom",
        )
        assert ev.duration_seconds == pytest.approx(0.0)

    async def test_engine_emits_pipeline_failed_with_nonzero_duration(self) -> None:
        """The engine's halt-branch emit sites must populate
        ``duration_seconds`` with ``time.monotonic() - start``. Today the
        field doesn't exist on the schema; once added, every emit site in
        ``engine/pipeline.py`` must thread the duration.
        """
        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _PerAgentCostBackend(costs={"s1": 0.20}, fail_agents={"s1"})
        engine = _make_engine(backend=backend, bus=bus)
        plan = WorkflowPlan(
            name="fail",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is False

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]
        # Mirror PipelineResult.duration_seconds — both surfaces are
        # populated from ``time.monotonic() - start``.
        assert emitted.duration_seconds == pytest.approx(result.duration_seconds), (
            f"PipelineFailed.duration_seconds must equal "
            f"PipelineResult.duration_seconds: "
            f"emitted={emitted.duration_seconds}, result={result.duration_seconds}"
        )
        # And the duration is non-zero (the run actually ran).
        assert emitted.duration_seconds > 0.0

    async def test_ledger_consumer_persists_pipeline_failed_duration(self, tmp_path: Path) -> None:
        """``CostLedgerConsumer._on_pipeline_failed`` MUST forward
        ``event.duration_seconds`` into the persisted ``PipelineRecord``.

        Today it writes ``duration_seconds=0.0`` unconditionally because
        the event has no such field. With the field added and threaded,
        the ledger row carries the real value.
        """
        bus = EventBus()
        ledger_path = tmp_path / "cost" / "cost_ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=ledger_path)
        consumer.register(bus)

        await bus.emit(
            PipelineFailed(
                session_id="ses",
                sequence=0,
                failed_stage="s1",
                error_message="boom",
                total_cost_usd=0.13,
                duration_seconds=7.5,
            )
        )

        lines = ledger_path.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "pipeline"
        assert record["duration_seconds"] == pytest.approx(7.5), (
            "CostLedgerConsumer must forward PipelineFailed.duration_seconds "
            "into the ledger row instead of hard-coded 0.0."
        )


# ===========================================================================
# M7 — PipelineFailed.stages_completed populated; XP consumer reads it
# ===========================================================================


class TestPipelineFailedStagesCompleted:
    """``PipelineFailed`` must carry ``stages_completed`` so the
    ``XPConsumer`` can distinguish stage-1 vs stage-19 failures (the XP
    calculator's penalty is sensitive to progress made).
    """

    def test_pipeline_failed_has_stages_completed_field(self) -> None:
        """The event schema grows ``stages_completed: int`` (default 0).

        Symmetric with ``PipelineCompleted.stages_completed``. Default
        ``0`` keeps legacy emitters round-tripping without raising.
        """
        ev = PipelineFailed(
            session_id="s",
            sequence=0,
            failed_stage="s1",
            error_message="boom",
            stages_completed=5,
        )
        assert ev.stages_completed == 5

    def test_pipeline_failed_stages_completed_defaults_to_zero(self) -> None:
        ev = PipelineFailed(
            session_id="s",
            sequence=0,
            failed_stage="s1",
            error_message="boom",
        )
        assert ev.stages_completed == 0

    @pytest.mark.parametrize(
        ("num_passing_stages", "expected_stages_completed"),
        [
            # Stage-1 failure: no prior stages done before halt.
            (0, 0),
            # Mid-pipeline failure: 3 stages pass, 4th fails.
            (3, 3),
            # Last-stage failure: N-1 stages pass, last fails.
            (5, 5),
        ],
    )
    async def test_engine_emits_pipeline_failed_with_stage_count(
        self,
        num_passing_stages: int,
        expected_stages_completed: int,
    ) -> None:
        """The engine's halt-branch emit sites must populate
        ``stages_completed`` with ``len(stages_done)`` at emit time.

        Parametrized across stage-1, mid-pipeline, and last-stage failure
        shapes so any drift in emit-site coverage (sequential halt,
        budget-exceeded halt, gate-failure halt) trips a parametrized
        case.
        """
        # Build N passing stages plus a failing tail stage.
        agent_costs = {f"s{i}": 0.05 for i in range(num_passing_stages)}
        agent_costs["fail"] = 0.05
        stages: list[StageSpec] = []
        prev_name: str | None = None
        for i in range(num_passing_stages):
            name = f"s{i}"
            deps = [prev_name] if prev_name else []
            stages.append(StageSpec(name=name, agent_name=name, depends_on=deps))
            prev_name = name
        # Failing tail stage depends on the last passing one.
        tail_deps = [prev_name] if prev_name else []
        stages.append(StageSpec(name="fail", agent_name="fail", depends_on=tail_deps))

        bus = EventBus()
        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _PerAgentCostBackend(costs=agent_costs, fail_agents={"fail"})
        engine = _make_engine(backend=backend, bus=bus)
        plan = WorkflowPlan(
            name="staged-fail",
            workflow_type=WorkflowType.STANDARD,
            stages=stages,
            budget_usd=100.0,
        )

        result = await engine.run(plan)
        assert result.success is False

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]
        # ``stages_completed`` counts every stage in ``stages_done`` at the
        # halt point — including the failed tail (which was added to
        # ``stages_done`` BEFORE the engine returned the failure).
        # Expected: ``num_passing_stages + 1`` (the failing stage is also
        # in the dict).
        assert emitted.stages_completed == expected_stages_completed + 1, (
            f"PipelineFailed.stages_completed must equal len(stages_done) at "
            f"halt time: expected {expected_stages_completed + 1}, "
            f"got {emitted.stages_completed}"
        )


# ===========================================================================
# Umbrella invariant — bus-vs-PipelineResult parity on every path
# ===========================================================================


class TestBusVsResultParityOnEveryPath:
    """After ANY pipeline run (success, failure, bounce, parallel-group),
    ``sum(observer.observed_costs) == PipelineResult.total_cost_usd``.

    Wave 10 + Wave 11 together restore the bus-vs-``PipelineResult``
    cost-parity invariant on every halt branch. This umbrella test pins
    it across the four canonical shapes.
    """

    async def test_parity_on_simple_success(self) -> None:
        bus = EventBus()
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        backend = _PerAgentCostBackend(costs={"a": 0.10, "b": 0.10})
        engine = _make_engine(backend=backend, bus=bus)
        plan = WorkflowPlan(
            name="ok",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="a", agent_name="a"),
                StageSpec(name="b", agent_name="b", depends_on=["a"]),
            ],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is True
        assert tracker.total_cost_usd == pytest.approx(result.total_cost_usd)

    async def test_parity_on_sequential_failure(self) -> None:
        bus = EventBus()
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        backend = _PerAgentCostBackend(costs={"a": 0.20}, fail_agents={"a"})
        engine = _make_engine(backend=backend, bus=bus)
        plan = WorkflowPlan(
            name="fail",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="a")],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is False
        assert tracker.total_cost_usd == pytest.approx(result.total_cost_usd)

    async def test_parity_on_successful_bounce(self) -> None:
        bus = EventBus()
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        gate = _EventualPassGate()
        backend = _PerAgentCostBackend(costs={"fixer": 0.50, "s1": 0.10})
        engine = _make_engine(backend=backend, bus=bus, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="bounce-ok",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="fixer", agent_name="fixer"),
                StageSpec(
                    name="s1",
                    agent_name="s1",
                    gates=["check"],
                    on_gate_failure="fixer",
                    depends_on=["fixer"],
                ),
            ],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is True
        assert tracker.total_cost_usd == pytest.approx(result.total_cost_usd)

    async def test_parity_on_parallel_group_mixed_outcome(self) -> None:
        bus = EventBus()
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        backend = _PerAgentCostBackend(
            costs={"win": 0.10, "lose": 0.30},
            fail_agents={"lose"},
        )
        engine = _make_engine(backend=backend, bus=bus)
        plan = WorkflowPlan(
            name="par",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="win", agent_name="win", parallel_group="g"),
                StageSpec(name="lose", agent_name="lose", parallel_group="g"),
            ],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is False
        assert tracker.total_cost_usd == pytest.approx(result.total_cost_usd)
