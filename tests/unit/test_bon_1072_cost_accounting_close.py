# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract — close the cost-accounting defect family (BON-1072).

Probe N+6 surfaced a cost-accounting defect family with three legs:

  M1. ``CostTracker`` (in-memory budget watcher) and ``CostLedgerConsumer``
      (JSONL persistence) both subscribe to *only* success events
      (``DispatchCompleted``, ``PipelineCompleted``). When a stage emits
      ``DispatchFailed`` with non-zero cost — or when a pipeline halts with
      ``PipelineFailed`` carrying a partial total — bus observers cannot
      reconstruct the cumulative cost the engine returned in
      ``PipelineResult.total_cost_usd``. The bus IS the cost-accounting
      surface; failure-path silence is a parity bug.

  M2. ``StageExecutor.execute_single`` (re-exported public API) drifted
      from ``PipelineEngine._execute_stage`` after Wave 9 Lane A added the
      ``cumulative_iteration_cost`` stamp. Both code paths claim to execute
      a stage with iteration; only one of them returns an envelope whose
      ``cost_usd`` field carries every dollar burned by intermediate
      iterations. Anyone calling the public executor directly (out-of-tree
      consumers, future pipeline rewrites) loses that accounting.

      Wave 11 Lane E (BON-1098) closed the drift permanently by deleting
      the ``StageExecutor`` class outright; only the live
      ``PipelineEngine._execute_stage`` path remains. The M2 parity test
      below therefore exercises only the engine path now (the
      ``"executor"`` parametrize branch was dropped with the class).

  M3. ``_handle_bounce`` accumulates the bounce target's cost into a local
      variable. On the SUCCESS path that local is returned to the caller
      and credited to ``total_cost``. On every FAILURE branch
      (bounce-target failed; retry failed; second-gate failure) the
      function returns ``None`` and the bounce target's cost vanishes.
      Symmetric to the success path; closes the gap.

  M4. ``CostLedgerConsumer._append`` uses raw ``open("a")``, bypassing the
      ``safe_append_text`` symlink-refusing primitive every other
      operator-controlled append site adopted in the W7.M rollout. The
      ledger lives at ``~/.bonfire/cost/cost_ledger.jsonl`` — operator
      space. Defense-in-depth gap; close it.

Each test pins one leg of the family. The tests deliberately read like
black-box contracts: they instantiate the engine / executor / consumer,
drive a small scenario, then assert on observable outputs (bus events,
ledger contents, returned ``PipelineResult.total_cost_usd``).

Plus one D3 doc-drift backstop: every ``bonfire <verb>`` example in
README / docs/ must match a Typer command registered on
``bonfire.cli.app.app``. Probe N+6 flagged D3 as narrative-only; this
test pins the live roster as the source of truth.

``pyproject.toml`` sets ``asyncio_mode = "auto"`` so async tests are
discovered without the ``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.events.consumers.cost import CostTracker
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    DispatchCompleted,
    DispatchFailed,
    PipelineFailed,
)
from bonfire.models.plan import GateContext, GateResult, StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Mocks reused across legs
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
            # Failure path STILL charges cost — the dollar already left
            # the wallet; whether the result was acceptable is a separate
            # axis from whether the call cost money.
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


class _AlwaysFailGate:
    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        return GateResult(
            gate_name="never",
            passed=False,
            severity="error",
            message="never passes",
        )


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
# Leg M1 — bus observers reconstruct cumulative cost on success + failure
# ===========================================================================


class TestBusObservedTotalParity:
    """The bus is the cost-accounting surface; subscribing to success
    events alone undercounts in any run that fails mid-flight.
    """

    async def test_cost_tracker_observes_dispatch_failed(self) -> None:
        """``DispatchFailed`` must carry the cost the backend actually
        charged on the failure path.

        Today the event has no ``cost_usd`` field, so ``CostTracker``
        cannot accumulate the failed-attempt spend even if it wanted to.
        The fix adds ``cost_usd: float = 0.0`` to ``DispatchFailed``
        (default ``0.0`` keeps legacy emitters valid) and wires the
        runner's accumulated cost into every emission site.
        """
        ev = DispatchFailed(
            session_id="s",
            sequence=0,
            agent_name="scout",
            error_message="boom",
            cost_usd=0.07,
        )
        assert ev.cost_usd == pytest.approx(0.07)

    async def test_cost_tracker_dual_subscribes_completed_and_failed(self) -> None:
        """After ``register``, ``CostTracker`` accumulates BOTH
        ``DispatchCompleted.cost_usd`` and ``DispatchFailed.cost_usd``.

        Without dual subscription, any pipeline that retries a flaky
        dispatch (the runner's whole reason for existing) silently
        undercounts the budget. ``cost_usd`` on the failed envelope is
        the per-attempt dollar charge — same shape as the success path,
        so the tracker can sum them uniformly.
        """
        bus = EventBus()
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(
            DispatchCompleted(
                session_id="s",
                sequence=0,
                agent_name="ok",
                cost_usd=0.10,
                duration_seconds=1.0,
            )
        )
        await bus.emit(
            DispatchFailed(
                session_id="s",
                sequence=0,
                agent_name="ko",
                error_message="boom",
                cost_usd=0.05,
            )
        )

        assert tracker.total_cost_usd == pytest.approx(0.15)

    async def test_bus_observed_total_equals_engine_total_on_success(self) -> None:
        """Happy-path parity sanity: the bus and the engine agree.

        Three sequential stages at $0.10 each — both surfaces report
        $0.30. This pins the floor before the failure-path tests cross
        the line.
        """
        bus = EventBus()
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        backend = _PerAgentCostBackend(costs={"a": 0.10, "b": 0.10, "c": 0.10})
        engine = _make_engine(backend=backend, bus=bus)
        plan = WorkflowPlan(
            name="three",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="a", agent_name="a"),
                StageSpec(name="b", agent_name="b", depends_on=["a"]),
                StageSpec(name="c", agent_name="c", depends_on=["b"]),
            ],
            budget_usd=10.0,
        )

        result = await engine.run(plan)
        assert result.success is True
        assert result.total_cost_usd == pytest.approx(0.30)
        assert tracker.total_cost_usd == pytest.approx(result.total_cost_usd)


# ===========================================================================
# Leg M1 (cont.) — PipelineFailed carries the total + the ledger persists it
# ===========================================================================


class TestPipelineFailedEmission:
    """``PipelineFailed`` must carry ``total_cost_usd`` so subscribers
    can persist or alert on the partial-spend total even on the halt
    path. ``CostLedgerConsumer`` subscribes to it.
    """

    def test_pipeline_failed_has_total_cost_usd_field(self) -> None:
        """The event schema grows ``total_cost_usd: float`` (default 0.0).

        ``PipelineCompleted`` already carries the field; ``PipelineFailed``
        is the failure-path symmetric. Default ``0.0`` so existing
        emitters that do not set the field round-trip without raising.
        """
        from bonfire.models.events import PipelineFailed as PF

        ev = PF(
            session_id="s",
            sequence=0,
            failed_stage="stg",
            error_message="boom",
            total_cost_usd=0.42,
        )
        assert ev.total_cost_usd == pytest.approx(0.42)

    async def test_engine_emits_pipeline_failed_with_total_cost(self) -> None:
        """Halt branch (failed stage) must emit ``PipelineFailed`` with
        the accumulated total stamped on.

        The engine's halt paths (failed stage, budget exceeded, gate
        failure) all construct ``PipelineFailed`` today; only the
        ``total_cost_usd`` field is missing from the schema. With the
        field added and threaded, the bus observer can reconstruct the
        same number ``PipelineResult.total_cost_usd`` returns.
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
        assert result.total_cost_usd == pytest.approx(0.20)

        failed_events = collector.of_type(PipelineFailed)
        assert len(failed_events) == 1
        emitted: PipelineFailed = failed_events[0]  # type: ignore[assignment]
        assert emitted.total_cost_usd == pytest.approx(result.total_cost_usd)

    async def test_ledger_consumer_subscribes_pipeline_failed(self, tmp_path: Path) -> None:
        """``CostLedgerConsumer`` must dual-subscribe to ``PipelineCompleted``
        AND ``PipelineFailed``. A halted pipeline must STILL leave a
        ``PipelineRecord`` in the ledger so downstream analytics see the
        partial spend; otherwise the JSONL ledger drops crash-paths
        entirely and the analyzer overcounts session success rate.
        """
        bus = EventBus()
        ledger_path = tmp_path / "cost" / "cost_ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=ledger_path)
        consumer.register(bus)

        await bus.emit(
            PipelineFailed(
                session_id="ses",
                sequence=0,
                failed_stage="stg",
                error_message="boom",
                total_cost_usd=0.13,
            )
        )

        lines = ledger_path.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "pipeline"
        assert record["total_cost_usd"] == pytest.approx(0.13)


# ===========================================================================
# Leg M1 (parallel) — TaskGroup accumulator survives mixed success+failure
# ===========================================================================


class TestParallelGroupAccumulation:
    """When a parallel group has BOTH a succeeding and a failing sibling,
    the bus-observed total must equal the engine's internal accounting.

    The dual-pass accumulator in ``_run_parallel_group`` already credits
    EVERY sibling's cost (Wave 9.2 fix); this test pins that the bus
    observer sees the same number once ``DispatchFailed`` carries cost.
    """

    async def test_mixed_success_failure_parallel_group_parity(self) -> None:
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
        # Both siblings ran; total reflects both costs.
        assert result.total_cost_usd == pytest.approx(0.40)
        # Bus observer reconstructed the same number from dispatch events.
        assert tracker.total_cost_usd == pytest.approx(result.total_cost_usd)


# ===========================================================================
# Leg M3 — _handle_bounce preserves bounce_target.cost_usd on failure
# ===========================================================================


class TestBounceTargetCostPreservedOnFailure:
    """The bounce target's cost MUST be credited to the pipeline total
    even when the bounce path fails (target fails, retry fails, or the
    second gate eval fails). Symmetric to the success path which already
    threads the cost via the returned ``cost_delta``.
    """

    async def test_failed_retry_after_bounce_preserves_bounce_target_cost(self) -> None:
        """Bounce target succeeds; the *retried* original stage then
        fails. The bounce target's cost must still land in
        ``result.total_cost_usd``.

        Cost ledger across the run:
          s1 first run (DAG):      0.10
          fixer initial (DAG):     0.50
          fixer bounce-target:     0.50  <-- discarded today on retry-FAILED
          s1 retry (failed):       0.10  <-- the retried original now fails

        Expected total: 1.20
        """

        class _SecondCallFailsBackend:
            """Backend that fails ``s1`` on its second call (post-bounce retry)."""

            def __init__(self, costs: dict[str, float]) -> None:
                self._costs = costs
                self._s1_calls = 0
                self.calls: list[Envelope] = []

            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                self.calls.append(envelope)
                cost = self._costs[envelope.agent_name]
                if envelope.agent_name == "s1":
                    self._s1_calls += 1
                    if self._s1_calls >= 2:
                        return envelope.model_copy(
                            update={
                                "status": TaskStatus.FAILED,
                                "error": ErrorDetail(error_type="agent", message="retry failed"),
                                "cost_usd": cost,
                            }
                        )
                return envelope.with_result(f"{envelope.agent_name} done", cost_usd=cost)

            async def health_check(self) -> bool:
                return True

        bus = EventBus()
        gate = _EventualPassGate()  # fails first eval -> bounce; passes second
        backend = _SecondCallFailsBackend(costs={"fixer": 0.50, "s1": 0.10})
        engine = _make_engine(backend=backend, bus=bus, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="bounce-retry-fail",
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
        # Pipeline halts because the retried original failed.
        assert result.success is False
        # Expected: 0.10 + 0.50 (DAG) + 0.50 (bounce target) + 0.10 (retry) = 1.20
        # Bug: bounce-target's 0.50 vanishes -> 0.70
        assert result.total_cost_usd == pytest.approx(1.20), (
            f"bounce target's cost lost on retry-failed path: "
            f"expected 1.20, got {result.total_cost_usd}"
        )

    async def test_failed_bounce_target_preserves_partial_cost(self) -> None:
        """Bounce target itself fails. Its cost still hit the wallet —
        the engine's total must reflect that, even though the bounce
        could not recover the gate failure.
        """

        class _BounceTargetFailsBackend:
            def __init__(self, costs: dict[str, float]) -> None:
                self._costs = costs
                self.calls: list[Envelope] = []

            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                self.calls.append(envelope)
                cost = self._costs[envelope.agent_name]
                # ``fixer`` succeeds on its FIRST call (DAG init) but
                # fails on the bounce-target call so the bounce path
                # halts on the target itself.
                if envelope.agent_name == "fixer":
                    fixer_calls = [c for c in self.calls if c.agent_name == "fixer"]
                    if len(fixer_calls) >= 2:
                        return envelope.model_copy(
                            update={
                                "status": TaskStatus.FAILED,
                                "error": ErrorDetail(error_type="agent", message="fixer failed"),
                                "cost_usd": cost,
                            }
                        )
                return envelope.with_result(f"{envelope.agent_name} done", cost_usd=cost)

            async def health_check(self) -> bool:
                return True

        bus = EventBus()
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
        # Expected costs:
        #   fixer DAG          0.50
        #   s1 DAG             0.10
        #   fixer bounce       0.50  <-- failed, but still cost money
        # Total: 1.10  (bug: 0.60, fixer bounce dropped)
        assert result.total_cost_usd == pytest.approx(1.10), (
            f"failed bounce target's cost lost: expected 1.10, got {result.total_cost_usd}"
        )


# ===========================================================================
# Leg M2 — PipelineEngine._execute_stage stamps cumulative iteration cost
# ===========================================================================


class TestStageExecutorCumulativeCostParity:
    """``PipelineEngine._execute_stage`` MUST stamp the sum of every
    iteration's cost onto the returned envelope's ``cost_usd`` field.

    Pre-Wave-11-Lane-E this contract was asserted across BOTH the
    standalone ``StageExecutor.execute_single`` path AND the engine
    path; the parametrize matrix is now collapsed to just ``"engine"``
    because Lane E deleted the ``StageExecutor`` class and the dead
    code path that was diverging (BON-1098 / Probe N+7 findings
    H1/H2/H3/M4). The class name on this test is preserved so the M2
    leg is still discoverable by ticket-history grep.
    """

    @staticmethod
    def _build_path_runner(path: str):
        """Return an async callable ``(spec, plan, sid, backend) -> Envelope``
        for the engine path.

        ``path`` is ``"engine"`` (only). Preserved as a shape-stable hook
        so that a future second execution surface can re-introduce a
        parametrize axis without rewriting callers.
        """

        async def run_engine(
            spec: StageSpec,
            plan: WorkflowPlan,
            session_id: str,
            backend: Any,
        ) -> Envelope:
            # Drive a single-stage pipeline; pull the resulting envelope
            # out of ``stages``.
            engine = PipelineEngine(backend=backend, bus=EventBus(), config=PipelineConfig())
            result = await engine.run(plan, session_id=session_id)
            return result.stages[spec.name]

        if path != "engine":
            raise ValueError(f"unsupported path: {path!r} (only 'engine' remains after Lane E)")
        return run_engine

    @pytest.mark.parametrize("path", ["engine"])
    async def test_successful_stage_stamps_cumulative_iteration_cost(self, path: str) -> None:
        """After two failed iterations and a third successful one, the
        returned envelope's ``cost_usd`` MUST equal the sum of all three
        iteration costs.

        ``PipelineEngine._execute_stage`` stamps this via
        ``cumulative_iteration_cost`` (Wave 9 Lane A).
        """

        class _FailTwiceThenSucceed:
            def __init__(self, cost: float) -> None:
                self._cost = cost
                self._n = 0
                self.calls: list[Envelope] = []

            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                self.calls.append(envelope)
                self._n += 1
                if self._n < 3:
                    return envelope.model_copy(
                        update={
                            "status": TaskStatus.FAILED,
                            "error": ErrorDetail(error_type="agent", message="flake"),
                            "cost_usd": self._cost,
                        }
                    )
                return envelope.with_result("ok", cost_usd=self._cost)

            async def health_check(self) -> bool:
                return True

        backend = _FailTwiceThenSucceed(cost=0.20)
        spec = StageSpec(name="s1", agent_name="s1", max_iterations=3)
        plan = WorkflowPlan(
            name="cum",
            workflow_type=WorkflowType.STANDARD,
            stages=[spec],
            budget_usd=10.0,
        )

        runner = self._build_path_runner(path)
        env = await runner(spec, plan, "ses_cum", backend)

        assert env.status != TaskStatus.FAILED
        # 3 iterations * $0.20 = $0.60 — every dollar accounted for.
        assert env.cost_usd == pytest.approx(0.60), (
            f"{path} dropped intermediate iteration cost: expected 0.60, got {env.cost_usd}"
        )


# ===========================================================================
# Leg M4 — CostLedgerConsumer._append uses safe_append_text (W7.M parity)
# ===========================================================================


class TestLedgerSafeAppend:
    """The ledger lives at an operator-controlled path
    (``~/.bonfire/cost/cost_ledger.jsonl``). Every other operator-
    controlled append site in Bonfire routes through
    ``bonfire._safe_write.safe_append_text`` so a planted symlink is
    refused at open(2) time. The cost ledger MUST use the same primitive.
    """

    async def test_append_routes_through_safe_append_text(self, tmp_path: Path) -> None:
        """Patch the safe_append_text export; emit an event; assert the
        patched helper was called at least once with the ledger path.
        """
        bus = EventBus()
        ledger_path = tmp_path / "cost" / "cost_ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=ledger_path)
        consumer.register(bus)

        # Patch the helper as imported into the consumer module so the
        # patch survives any local-alias re-import.
        with patch("bonfire.cost.consumer.safe_append_text") as mock_safe:
            await bus.emit(
                DispatchCompleted(
                    session_id="ses",
                    sequence=0,
                    agent_name="scout",
                    cost_usd=0.02,
                    duration_seconds=1.0,
                )
            )

        assert mock_safe.call_count >= 1, (
            "CostLedgerConsumer._append must route through "
            "bonfire._safe_write.safe_append_text (W7.M parity); "
            "raw open('a') is forbidden at operator-controlled write sites."
        )
        # First positional arg is the ledger path the helper writes to.
        called_path = mock_safe.call_args_list[0].args[0]
        assert Path(called_path) == ledger_path


# ===========================================================================
# D3 doc-drift backstop — every README/docs `bonfire <verb>` matches the
# live Typer command roster on bonfire.cli.app.app.
# ===========================================================================


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_DIR = _REPO_ROOT / "docs"
_README = _REPO_ROOT / "README.md"


def _live_command_roster() -> set[str]:
    """Walk the Typer app and return every fully-qualified command path.

    Returns the set of names like ``{"init", "scan", "cost", "cost agents",
    ...}``. Used as the ground truth against which README + docs are
    audited.
    """
    from bonfire.cli.app import app as cli_app

    def _walk(typer_app: Any, prefix: str = "") -> list[str]:
        out: list[str] = []
        for cmd_info in typer_app.registered_commands:
            name = cmd_info.name or (cmd_info.callback.__name__ if cmd_info.callback else "")
            if not name:
                continue
            qualified = f"{prefix} {name}".strip()
            out.append(qualified)
        for grp in typer_app.registered_groups:
            gname = grp.name or (grp.typer_instance.info.name if grp.typer_instance else "")
            if not gname:
                continue
            out.append(f"{prefix} {gname}".strip())
            out.extend(_walk(grp.typer_instance, f"{prefix} {gname}".strip()))
        return out

    return set(_walk(cli_app))


# Match a ``bonfire <verb>[ <subverb>]`` CLI invocation. The match is
# anchored on lowercase ``bonfire `` (capital ``Bonfire`` is the product
# name, not the CLI binary) and is collected only from CONTEXTS that
# clearly look like command examples — fenced code blocks and backtick
# spans. Free-prose mentions of ``Bonfire`` followed by an adjective
# (``bonfire architecture``, ``bonfire codebase``) MUST NOT match: they
# are documentation, not commands.
_BONFIRE_INVOCATION_RE = re.compile(
    r"bonfire\s+(-{1,2}[a-z][\w-]*|[a-z][a-z0-9-]*)(?:\s+(-{1,2}[a-z][\w-]*|[a-z][a-z0-9-]*))?",
)


# Code-fence languages that hold shell-style CLI invocations. Other
# languages (``markdown``, ``yaml``, ``json``) hold template prose or
# data, not commands — we ignore them so a doc-template paragraph
# mentioning ``the bonfire pipeline`` does not trip the gate.
_SHELL_FENCE_LANGS: frozenset[str] = frozenset(
    {"", "bash", "sh", "shell", "console", "zsh", "text"}
)


def _iter_command_spans(text: str) -> list[str]:
    """Yield each backtick-span or shell-fenced-code-block body in *text*.

    The doc-drift gate cares about CLI examples, not free prose. Examples
    appear in two shapes in the public docs / README:

      * Backtick spans like ``\\`bonfire init\\```.
      * Fenced ```bash / ```shell / ```text code blocks (or unlabeled
        ``` fences) where the operator would copy-paste literally.

    Fenced blocks tagged with a non-shell language (e.g. ```markdown,
    ```yaml, ```json, ```python) are excluded — they are documentation
    or data, not CLI examples.

    Free prose mentions of the product name (``Bonfire is...``) live
    OUTSIDE all these spans and are correctly ignored.
    """
    spans: list[str] = []

    # Backtick spans — single ` ... ` (not the triple-backtick fence).
    for m in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", text):
        spans.append(m.group(1))

    # Fenced code blocks — only those whose language tag is shell-shaped.
    for m in re.finditer(r"```([a-zA-Z0-9_-]*)\n([\s\S]*?)```", text):
        lang = m.group(1).lower()
        if lang not in _SHELL_FENCE_LANGS:
            continue
        spans.append(m.group(2))

    return spans


def _extract_invocations(text: str) -> set[str]:
    """Return the set of ``bonfire <verb>[ <subverb>]`` invocations in *text*.

    Only collects matches inside backtick-spans or shell-fenced code
    blocks (see :func:`_iter_command_spans`). Flag tokens (``--help``,
    ``-v``) are tolerated as the optional second token (they're not
    commands but they DO appear in real example invocations like
    ``bonfire --help``); the caller drops them via the leading-``-``
    guard.
    """
    out: set[str] = set()
    for span in _iter_command_spans(text):
        for m in _BONFIRE_INVOCATION_RE.finditer(span):
            verb = m.group(1)
            # Flag-only invocations (``bonfire --help``) do not need a
            # Typer registration — Typer ships the flag itself.
            if verb.startswith("-"):
                continue
            sub = m.group(2)
            if sub and not sub.startswith("-"):
                out.add(f"{verb} {sub}")
            else:
                out.add(verb)
    return out


# Verbs that appear in narrative prose explaining what is NOT YET shipped
# (``bonfire run`` is the documented public-port plan for 0.1.x — the
# README explicitly notes "There is no `bonfire run` command" today).
# These are documentation, not invocations, so they get an explicit
# allowlist with the public-doc rationale.
_NARRATIVE_ALLOWLIST: frozenset[str] = frozenset({"run"})


def test_doc_bonfire_verbs_match_registered_commands() -> None:
    """Every ``bonfire <verb>`` in README and docs/ must resolve to a
    Typer command on ``bonfire.cli.app.app``.

    Probe N+6 flagged D3 as narrative-only — there was no automated
    backstop preventing a doc author from referencing a CLI verb that
    does not exist in the shipped Typer registry. This test is that
    backstop.

    Allowlisted: ``bonfire run`` — the README and architecture doc both
    discuss the planned post-v0.1 CLI verb explicitly as "not shipped
    yet". That is narrative documentation of a public-port plan, not a
    spurious example. Any new entry to the allowlist requires a public
    rationale alongside it.
    """
    live = _live_command_roster()
    # Top-level names alone — for matching against single-verb
    # invocations like ``bonfire init``, the live roster contains
    # ``"init"`` as a top-level entry, and ``"cost"`` as both a group
    # entry and the prefix of ``"cost session"``.
    sources: list[tuple[str, str]] = []
    sources.append(("README.md", _README.read_text(encoding="utf-8")))
    for path in sorted(_DOCS_DIR.rglob("*.md")):
        sources.append((path.relative_to(_REPO_ROOT).as_posix(), path.read_text(encoding="utf-8")))

    offenders: list[tuple[str, str]] = []
    for rel, text in sources:
        for inv in _extract_invocations(text):
            verb = inv.split(" ", 1)[0]
            if verb in _NARRATIVE_ALLOWLIST:
                continue
            if inv in live:
                continue
            # Two-word invocation may legitimately be a one-word verb
            # followed by a positional argument (``bonfire init .``,
            # ``bonfire persona set <name>`` — the SECOND token is the
            # subcommand). Re-test as just the first verb when the
            # combined form is unknown.
            if verb in live:
                continue
            offenders.append((rel, inv))

    assert not offenders, (
        "README / docs/ reference `bonfire <verb>` invocations that do not "
        "exist in the shipped Typer command roster.\n"
        "Either add the verb to bonfire.cli.app.app (or one of its "
        "sub-Typers), or rewrite the doc to use a registered verb.\n"
        f"  Live roster: {sorted(live)}\n"
        "  Offenders:\n" + "\n".join(f"    {rel}: bonfire {inv}" for rel, inv in offenders)
    )
