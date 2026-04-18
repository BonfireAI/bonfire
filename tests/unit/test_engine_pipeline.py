"""Canonical RED — ``bonfire.engine.pipeline`` (BON-334).

Synthesized from Knight-A orchestration + Knight-B contract fidelity.

The pipeline engine is the nervous system of Bonfire. A sloppy orchestrator
loses DAG ordering, leaks exceptions, forgets the budget, skips events,
loops forever on bounces, or never cleans up its parallel tasks.

Sage decisions:
    D3: No ``compiler`` kwarg. Public v0.1 drops it entirely.
    D5: GateChain does not wrap gate exceptions. The PipelineEngine's outer
        try/except catches raising gates and returns PipelineResult(ok=False).
        This file includes an explicit test that locks that invariant.
    D6: ``budget_remaining_usd`` clamped at zero (also locked in executor).
    D7: Single bounce — on_gate_failure target runs, original re-runs, gates
        re-evaluate ONCE. Double gate failure halts (no recursion, no loops).
    D8: PipelineResult has exactly these 8 fields with these types:
        - success: bool
        - session_id: str
        - stages: dict[str, Envelope] (default_factory=dict)
        - total_cost_usd: float = 0.0
        - duration_seconds: float = 0.0
        - error: str = ""
        - failed_stage: str = ""
        - gate_failure: GateResult | None = None

Contract locked (pipeline):
    DAG execution
      1. Single / linear / diamond / parallel-group plans all complete.
      2. Topological order is respected (dep runs before dependent).
      3. depends_on correctly propagates stage output into context.
      4. resume completed={...} skips those stages; emits StageSkipped.

    Gate evaluation
      5. Passing gate continues; failing error-gate halts.
      6. Warning-severity failure does NOT halt.
      7. Unknown gate emits QualityBypassed and pipeline continues.
      8. Multi-gate: first error short-circuits the chain.
      9. on_gate_failure target executes and original re-runs (single bounce).
     10. Double-gate-failure halts — no infinite loops.
     11. on_gate_failure=None with failing gate halts.

    Iteration
     12. max_iterations retries on stage failure.
     13. Early success on retry stops iterating.

    Budget enforcement
     14. Under budget -> success.
     15. Over budget -> PipelineResult with ok=False and "Budget" in error.
     16. Budget exceeded triggers PipelineFailed event, not raise.

    Events
     17. Success run emits PipelineStarted + StageStarted + StageCompleted
         + PipelineCompleted.
     18. Failed run emits PipelineFailed exactly once.
     19. Resume: StageSkipped emitted per pre-completed stage.
     20. session_id stamped on engine-owned events.

    Never-raise discipline
     21. Handler exception -> ok=False, no raise.
     22. Backend exception -> ok=False, no raise.
     23. Unknown handler -> ok=False, no raise.
     24. Gate exception -> PipelineResult, no raise (D5 lock).

    PipelineResult
     25. Frozen, serializable, 8-field shape locked.
     26. stages dict carries Envelopes.
     27. total_cost_usd and duration_seconds populated on run.
     28. Defaults correct on minimal construction.

    PipelineEngine API
     29. auto-generates session_id when none given.
     30. honors caller-supplied session_id.
     31. initial_envelope metadata merges; stage role overrides on collision.
     32. Compiler kwarg rejected in constructor (D3).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    QualityBypassed,
    StageCompleted,
    StageFailed,
    StageSkipped,
    StageStarted,
)
from bonfire.models.plan import GateContext, GateResult, StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _MockBackend:
    """Configurable backend returning COMPLETED envelopes by default."""

    def __init__(
        self,
        results: dict[str, str] | None = None,
        fail_agents: set[str] | None = None,
        cost: float = 0.01,
    ) -> None:
        self.results = results or {}
        self.fail_agents = fail_agents or set()
        self.cost = cost
        self.calls: list[Envelope] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append(envelope)
        if envelope.agent_name in self.fail_agents:
            return envelope.with_error(
                ErrorDetail(error_type="agent", message=f"{envelope.agent_name} failed")
            )
        text = self.results.get(envelope.agent_name, f"{envelope.agent_name} done")
        return envelope.with_result(text, cost_usd=self.cost)

    async def health_check(self) -> bool:
        return True


class _MockGate:
    """Configurable QualityGate for orchestration tests."""

    def __init__(
        self,
        passed: bool = True,
        severity: str = "error",
        message: str = "",
    ) -> None:
        self.passed = passed
        self.severity = severity
        self.message = message
        self.calls = 0

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        self.calls += 1
        return GateResult(
            gate_name="mock",
            passed=self.passed,
            severity=self.severity,
            message=self.message,
        )


class _EventualPassGate:
    """Fails first evaluation, passes on subsequent — used for bounce recovery."""

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


class _MockHandler:
    """Stub handler that always completes successfully."""

    def __init__(self, result: str = "handled") -> None:
        self.result = result
        self.calls = 0

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        self.calls += 1
        return envelope.with_result(self.result, cost_usd=0.02)


class _RaisingHandler:
    """Handler that explodes — exercises C19 never-raise."""

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        raise RuntimeError("handler exploded")


class _EventCollector:
    """Collects all emitted events."""

    def __init__(self) -> None:
        self.events: list[BonfireEvent] = []

    async def __call__(self, event: BonfireEvent) -> None:
        self.events.append(event)

    def of_type(self, event_cls: type) -> list[BonfireEvent]:
        return [e for e in self.events if type(e) is event_cls]


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------


def _single_plan(agent_name: str = "s1") -> WorkflowPlan:
    return WorkflowPlan(
        name="single",
        workflow_type=WorkflowType.STANDARD,
        stages=[StageSpec(name="s1", agent_name=agent_name)],
    )


def _linear_plan(*names: str, budget: float = 10.0) -> WorkflowPlan:
    stages = []
    for i, name in enumerate(names):
        deps = [names[i - 1]] if i > 0 else []
        stages.append(StageSpec(name=name, agent_name=name, depends_on=deps))
    return WorkflowPlan(
        name="linear",
        workflow_type=WorkflowType.STANDARD,
        stages=stages,
        budget_usd=budget,
    )


def _parallel_plan(group: str, *names: str) -> WorkflowPlan:
    return WorkflowPlan(
        name="parallel",
        workflow_type=WorkflowType.STANDARD,
        stages=[StageSpec(name=n, agent_name=n, parallel_group=group) for n in names],
    )


def _diamond_plan() -> WorkflowPlan:
    """A -> B,C -> D."""
    return WorkflowPlan(
        name="diamond",
        workflow_type=WorkflowType.STANDARD,
        stages=[
            StageSpec(name="A", agent_name="A"),
            StageSpec(name="B", agent_name="B", depends_on=["A"]),
            StageSpec(name="C", agent_name="C", depends_on=["A"]),
            StageSpec(name="D", agent_name="D", depends_on=["B", "C"]),
        ],
    )


def _make_engine(
    backend: _MockBackend | None = None,
    bus: EventBus | None = None,
    config: PipelineConfig | None = None,
    handlers: dict[str, Any] | None = None,
    gate_registry: dict[str, Any] | None = None,
):  # noqa: ANN201 — engine is lazily imported
    from bonfire.engine.pipeline import PipelineEngine

    return PipelineEngine(
        backend=backend or _MockBackend(),
        bus=bus or EventBus(),
        config=config or PipelineConfig(),
        handlers=handlers,
        gate_registry=gate_registry,
    )


# ===========================================================================
# 1. Imports
# ===========================================================================


class TestImports:
    """PipelineEngine and PipelineResult importable from both canonical paths."""

    def test_import_pipeline_engine_from_module(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        assert PipelineEngine is not None

    def test_import_pipeline_result_from_module(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        assert PipelineResult is not None

    def test_import_pipeline_engine_from_engine_package(self) -> None:
        from bonfire.engine import PipelineEngine

        assert PipelineEngine is not None

    def test_import_pipeline_result_from_engine_package(self) -> None:
        from bonfire.engine import PipelineResult

        assert PipelineResult is not None


# ===========================================================================
# 2. PipelineResult — frozen, 8-field shape (Sage D8)
# ===========================================================================


class TestPipelineResult:
    """PipelineResult: frozen Pydantic model with the V1 8-field shape (Sage D8)."""

    def test_field_list_matches_v1(self) -> None:
        """Locked 8-field set."""
        from bonfire.engine.pipeline import PipelineResult

        expected = {
            "success",
            "session_id",
            "stages",
            "total_cost_usd",
            "duration_seconds",
            "error",
            "failed_stage",
            "gate_failure",
        }
        assert set(PipelineResult.model_fields.keys()) == expected

    def test_is_frozen(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        r = PipelineResult(success=True, session_id="s1")
        with pytest.raises(ValidationError):
            r.success = False  # type: ignore[misc]

    def test_defaults_populated(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        result = PipelineResult(success=False, session_id="s1")
        assert result.stages == {}
        assert result.total_cost_usd == 0.0
        assert result.duration_seconds == 0.0
        assert result.error == ""
        assert result.failed_stage == ""
        assert result.gate_failure is None

    def test_stages_carry_envelopes(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        env = Envelope(task="done", status=TaskStatus.COMPLETED, result="ok")
        result = PipelineResult(
            success=True,
            session_id="s1",
            stages={"stage-1": env},
        )
        assert result.stages["stage-1"].result == "ok"

    def test_gate_failure_accepts_gate_result(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        gr = GateResult(gate_name="g", passed=False, severity="error", message="m")
        r = PipelineResult(success=False, session_id="s", gate_failure=gr)
        assert r.gate_failure is gr

    def test_serializable(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        result = PipelineResult(success=True, session_id="s1", total_cost_usd=0.42)
        dumped = result.model_dump()
        assert dumped["success"] is True
        assert dumped["total_cost_usd"] == 0.42


# ===========================================================================
# 3. PipelineEngine constructor — kw-only, no compiler (Sage D3)
# ===========================================================================


class TestPipelineEngineConstructor:
    """Constructor is kw-only with the v0.1 dep set (NO compiler — Sage D3)."""

    def test_constructor_is_keyword_only(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.__init__)
        params = list(sig.parameters.values())[1:]  # skip self
        assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in params), params

    def test_accepts_required_backend_bus_config(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(backend=_MockBackend(), bus=EventBus(), config=PipelineConfig())
        assert engine is not None

    def test_accepts_optional_handlers_kwarg(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(
            backend=_MockBackend(),
            bus=EventBus(),
            config=PipelineConfig(),
            handlers={},
        )
        assert engine is not None

    def test_accepts_optional_gate_registry_kwarg(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(
            backend=_MockBackend(),
            bus=EventBus(),
            config=PipelineConfig(),
            gate_registry={},
        )
        assert engine is not None

    def test_accepts_optional_context_builder_kwarg(self) -> None:
        from bonfire.engine.context import ContextBuilder
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(
            backend=_MockBackend(),
            bus=EventBus(),
            config=PipelineConfig(),
            context_builder=ContextBuilder(),
        )
        assert engine is not None

    def test_accepts_project_root_kwarg(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(
            backend=_MockBackend(),
            bus=EventBus(),
            config=PipelineConfig(),
            project_root="/tmp/proj",
        )
        assert engine is not None

    def test_rejects_compiler_kwarg(self) -> None:
        """Sage D3 — ``compiler`` kwarg is NOT accepted in v0.1."""
        from bonfire.engine.pipeline import PipelineEngine

        with pytest.raises(TypeError):
            PipelineEngine(
                backend=_MockBackend(),
                bus=EventBus(),
                config=PipelineConfig(),
                compiler=object(),  # type: ignore[call-arg]
            )


# ===========================================================================
# 4. run() signature
# ===========================================================================


class TestRunSignature:
    """run() is async; session_id, completed, initial_envelope are kw-only."""

    def test_run_is_async(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        assert inspect.iscoroutinefunction(PipelineEngine.run)

    def test_run_signature_has_kwonly_session_id(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.run)
        sess = sig.parameters.get("session_id")
        assert sess is not None
        assert sess.kind == inspect.Parameter.KEYWORD_ONLY

    def test_run_signature_has_kwonly_completed(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.run)
        c = sig.parameters.get("completed")
        assert c is not None
        assert c.kind == inspect.Parameter.KEYWORD_ONLY

    def test_run_signature_has_kwonly_initial_envelope(self) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.run)
        ie = sig.parameters.get("initial_envelope")
        assert ie is not None
        assert ie.kind == inspect.Parameter.KEYWORD_ONLY


# ===========================================================================
# 5. Basic sequencing
# ===========================================================================


class TestBasicSequencing:
    """Single and linear plans execute in topological order."""

    async def test_single_stage_success(self) -> None:
        engine = _make_engine()
        result = await engine.run(_single_plan())
        assert result.success is True

    async def test_auto_generates_session_id(self) -> None:
        engine = _make_engine()
        result = await engine.run(_single_plan())
        assert isinstance(result.session_id, str)
        assert result.session_id != ""

    async def test_session_id_preserved(self) -> None:
        engine = _make_engine()
        result = await engine.run(_single_plan(), session_id="sess-42")
        assert result.session_id == "sess-42"

    async def test_two_stage_linear_order(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        await engine.run(_linear_plan("s1", "s2"))
        order = [c.agent_name for c in backend.calls]
        assert order == ["s1", "s2"]

    async def test_three_stage_linear_order(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        await engine.run(_linear_plan("a", "b", "c"))
        assert [c.agent_name for c in backend.calls] == ["a", "b", "c"]

    async def test_second_stage_gets_first_result_in_context(self) -> None:
        backend = _MockBackend(results={"s1": "S1-OUT", "s2": "S2-OUT"})
        engine = _make_engine(backend=backend)
        await engine.run(_linear_plan("s1", "s2"))
        second = backend.calls[1]
        # Context or task should propagate s1 output.
        assert "S1-OUT" in second.context or "S1-OUT" in second.task

    async def test_completed_none_treated_as_empty(self) -> None:
        """Passing completed=None is equivalent to {}."""
        engine = _make_engine()
        result = await engine.run(_single_plan(), completed=None)
        assert result.success is True

    async def test_run_populates_stages_dict_on_success(self) -> None:
        engine = _make_engine()
        result = await engine.run(_linear_plan("s1", "s2"))
        assert "s1" in result.stages
        assert "s2" in result.stages
        assert isinstance(result.stages["s1"], Envelope)


# ===========================================================================
# 6. Parallel execution
# ===========================================================================


class TestParallelExecution:
    """Stages sharing parallel_group execute concurrently."""

    async def test_both_parallel_stages_complete(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        result = await engine.run(_parallel_plan("g", "p1", "p2"))
        assert result.success is True
        assert {c.agent_name for c in backend.calls} == {"p1", "p2"}

    async def test_parallel_one_fails_halts(self) -> None:
        backend = _MockBackend(fail_agents={"p2"})
        engine = _make_engine(backend=backend)
        result = await engine.run(_parallel_plan("g", "p1", "p2"))
        assert result.success is False


# ===========================================================================
# 7. DAG — diamond & dependency ordering
# ===========================================================================


class TestDAGExecution:
    """Topological ordering via graphlib.TopologicalSorter."""

    async def test_diamond_d_runs_last(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        await engine.run(_diamond_plan())
        order = [c.agent_name for c in backend.calls]
        assert order[0] == "A"
        assert order[-1] == "D"

    async def test_diamond_b_and_c_run_after_a(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        await engine.run(_diamond_plan())
        order = [c.agent_name for c in backend.calls]
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")

    async def test_root_runs_before_child(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="t",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="root", agent_name="root"),
                StageSpec(name="child", agent_name="child", depends_on=["root"]),
            ],
        )
        await engine.run(plan)
        order = [c.agent_name for c in backend.calls]
        assert order.index("root") < order.index("child")


# ===========================================================================
# 8. Resume — skip completed stages
# ===========================================================================


class TestResume:
    """Resuming with pre-completed stages skips them and still runs the rest."""

    async def test_resume_skips_completed_stage(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        plan = _linear_plan("A", "B", "C")
        pre = Envelope(task="pre", agent_name="A", status=TaskStatus.COMPLETED, result="done")
        result = await engine.run(plan, completed={"A": pre})

        agents = [c.agent_name for c in backend.calls]
        assert "A" not in agents
        assert "B" in agents
        assert "C" in agents
        assert result.success is True

    async def test_resume_emits_stage_skipped(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus)
        plan = _linear_plan("A", "B")
        pre = Envelope(task="pre", agent_name="A", status=TaskStatus.COMPLETED, result="done")
        await engine.run(plan, completed={"A": pre})

        skipped = collector.of_type(StageSkipped)
        assert any(e.stage_name == "A" for e in skipped)

    async def test_pre_completed_envelope_preserved_in_stages(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        pre = Envelope(
            task="t", agent_name="s1-agent", status=TaskStatus.COMPLETED, result="cached"
        )
        plan = WorkflowPlan(
            name="resume",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="s1", agent_name="s1-agent"),
                StageSpec(name="s2", agent_name="s2-agent", depends_on=["s1"]),
            ],
        )
        result = await engine.run(plan, completed={"s1": pre})
        assert result.stages["s1"].result == "cached"


# ===========================================================================
# 9. Gate evaluation
# ===========================================================================


class TestGateEvaluation:
    """Gates control the pipeline flow."""

    async def test_passing_gate_continues(self) -> None:
        gate = _MockGate(passed=True)
        engine = _make_engine(gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="g",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="s1", agent_name="s1", gates=["check"]),
                StageSpec(name="s2", agent_name="s2", depends_on=["s1"]),
            ],
        )
        result = await engine.run(plan)
        assert result.success is True
        assert gate.calls == 1

    async def test_failing_error_gate_halts(self) -> None:
        gate = _MockGate(passed=False, severity="error", message="bad")
        engine = _make_engine(gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="g",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", gates=["check"])],
        )
        result = await engine.run(plan)
        assert result.success is False
        assert result.gate_failure is not None
        assert result.gate_failure.passed is False

    async def test_warning_gate_does_not_halt(self) -> None:
        gate = _MockGate(passed=False, severity="warning", message="minor")
        engine = _make_engine(gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="g",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", gates=["check"])],
        )
        result = await engine.run(plan)
        assert result.success is True

    async def test_unknown_gate_emits_bypassed_and_continues(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus, gate_registry={})
        plan = WorkflowPlan(
            name="g",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", gates=["nonexistent"])],
        )
        result = await engine.run(plan)
        assert result.success is True
        assert len(collector.of_type(QualityBypassed)) >= 1

    async def test_multi_gate_first_error_short_circuits(self) -> None:
        pass_gate = _MockGate(passed=True)
        fail_gate = _MockGate(passed=False, severity="error")
        engine = _make_engine(gate_registry={"pass": pass_gate, "fail": fail_gate})
        plan = WorkflowPlan(
            name="g",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", gates=["pass", "fail"])],
        )
        result = await engine.run(plan)
        assert result.success is False
        assert result.gate_failure is not None


# ===========================================================================
# 10. Bounce-back — single bounce semantics (Sage D7)
# ===========================================================================


class TestBounceBack:
    """on_gate_failure: target executes, original re-runs ONCE, gates re-eval ONCE."""

    async def test_bounce_target_executes(self) -> None:
        gate = _MockGate(passed=False, severity="error")
        backend = _MockBackend()
        engine = _make_engine(backend=backend, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="b",
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
        )
        await engine.run(plan)
        # Fixer runs at least twice (initial + bounce).
        fixer_calls = [c for c in backend.calls if c.agent_name == "fixer"]
        assert len(fixer_calls) >= 2

    async def test_bounce_re_executes_original_stage(self) -> None:
        gate = _MockGate(passed=False, severity="error")
        backend = _MockBackend()
        engine = _make_engine(backend=backend, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="b",
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
        )
        await engine.run(plan)
        s1_calls = [c for c in backend.calls if c.agent_name == "s1"]
        assert len(s1_calls) >= 2

    async def test_bounce_recovers_when_second_gate_eval_passes(self) -> None:
        """When the re-evaluated gate passes, the pipeline continues."""
        gate = _EventualPassGate()
        backend = _MockBackend()
        engine = _make_engine(backend=backend, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="b",
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
        )
        result = await engine.run(plan)
        assert result.success is True

    async def test_bounce_without_target_halts(self) -> None:
        gate = _MockGate(passed=False, severity="error")
        engine = _make_engine(gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="b",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(
                    name="s1",
                    agent_name="s1",
                    gates=["check"],
                    on_gate_failure=None,
                )
            ],
        )
        result = await engine.run(plan)
        assert result.success is False

    async def test_double_gate_failure_halts_no_infinite_loop(self) -> None:
        """Sage D7 — permanently-failing gate halts after one bounce attempt."""
        gate = _MockGate(passed=False, severity="error", message="forever broken")
        backend = _MockBackend()
        engine = _make_engine(backend=backend, gate_registry={"check": gate})
        plan = WorkflowPlan(
            name="b",
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
        )
        result = await engine.run(plan)
        assert result.success is False


# ===========================================================================
# 11. Iteration — retry at pipeline level
# ===========================================================================


class TestIteration:
    """Stage max_iterations retries on agent failure."""

    async def test_stage_retries_up_to_max(self) -> None:
        backend = _MockBackend(fail_agents={"s1"})
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="i",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", max_iterations=3)],
        )
        await engine.run(plan)
        s1_calls = [c for c in backend.calls if c.agent_name == "s1"]
        assert len(s1_calls) == 3

    async def test_exhausted_iterations_yields_failure(self) -> None:
        backend = _MockBackend(fail_agents={"s1"})
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="i",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", max_iterations=2)],
        )
        result = await engine.run(plan)
        assert result.success is False


# ===========================================================================
# 12. Budget enforcement
# ===========================================================================


class TestBudget:
    """Pipeline halts when cumulative cost exceeds plan.budget_usd (V1 296-315)."""

    async def test_within_budget_succeeds(self) -> None:
        engine = _make_engine()
        plan = WorkflowPlan(
            name="ok",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=10.0,
        )
        result = await engine.run(plan)
        assert result.success is True

    async def test_over_budget_halts(self) -> None:
        backend = _MockBackend(cost=5.0)
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="over",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="s1", agent_name="s1"),
                StageSpec(name="s2", agent_name="s2", depends_on=["s1"]),
            ],
            budget_usd=1.0,
        )
        result = await engine.run(plan)
        assert result.success is False
        assert "budget" in result.error.lower()

    async def test_over_budget_does_not_raise(self) -> None:
        """Budget violation must return PipelineResult, never raise."""
        from bonfire.engine.pipeline import PipelineResult

        backend = _MockBackend(cost=100.0)
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="x",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="s1", agent_name="s1"),
                StageSpec(name="s2", agent_name="s2", depends_on=["s1"]),
            ],
            budget_usd=0.1,
        )
        result = await engine.run(plan)
        assert isinstance(result, PipelineResult)
        assert result.success is False


# ===========================================================================
# 13. Event emission — full sequence
# ===========================================================================


class TestEventEmission:
    """Pipeline emits the right events in the right sequence."""

    async def test_success_run_core_events(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus)
        await engine.run(_single_plan())

        assert len(collector.of_type(PipelineStarted)) == 1
        assert len(collector.of_type(StageStarted)) >= 1
        assert len(collector.of_type(StageCompleted)) >= 1
        assert len(collector.of_type(PipelineCompleted)) == 1

    async def test_failed_run_emits_pipeline_failed(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        backend = _MockBackend(fail_agents={"s1"})
        engine = _make_engine(backend=backend, bus=bus)
        await engine.run(_single_plan(agent_name="s1"))

        assert len(collector.of_type(PipelineFailed)) == 1
        assert len(collector.of_type(StageFailed)) >= 1

    async def test_engine_events_carry_session_id(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus)
        await engine.run(_single_plan(), session_id="sess-777")

        for event in collector.events:
            # Dispatch events may carry envelope-scoped IDs; assert only on
            # pipeline- and stage-scoped events here.
            if event.event_type.startswith("dispatch."):
                continue
            assert event.session_id == "sess-777"

    async def test_pipeline_started_emitted_first(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus)
        await engine.run(_single_plan())
        assert type(collector.events[0]) is PipelineStarted

    async def test_pipeline_completed_emitted_last_on_success(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus)
        await engine.run(_single_plan())
        assert type(collector.events[-1]) is PipelineCompleted

    async def test_pipeline_started_carries_plan_name_and_budget(self) -> None:
        collector = _EventCollector()
        bus = EventBus()
        bus.subscribe_all(collector)
        engine = _make_engine(bus=bus)
        plan = WorkflowPlan(
            name="test-plan",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
            budget_usd=9.99,
        )
        await engine.run(plan)
        started = next(e for e in collector.events if isinstance(e, PipelineStarted))
        assert started.plan_name == "test-plan"
        assert started.budget_usd == 9.99


# ===========================================================================
# 14. Never-raise discipline (includes D5 gate-exception lock)
# ===========================================================================


class TestNeverRaise:
    """PipelineEngine.run() NEVER raises — always returns a PipelineResult."""

    async def test_handler_exception_returns_failed_result(self) -> None:
        engine = _make_engine(handlers={"boom": _RaisingHandler()})
        plan = WorkflowPlan(
            name="x",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", handler_name="boom")],
        )
        # Must NOT raise.
        result = await engine.run(plan)
        assert result.success is False

    async def test_exploding_backend_returns_failed_result(self) -> None:
        from bonfire.engine.pipeline import PipelineResult

        class _Exploding:
            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                raise RuntimeError("total meltdown")

            async def health_check(self) -> bool:
                return True

        engine = _make_engine(backend=_Exploding())  # type: ignore[arg-type]
        result = await engine.run(_single_plan())
        assert isinstance(result, PipelineResult)
        assert result.success is False

    async def test_unknown_handler_does_not_raise(self) -> None:
        engine = _make_engine(handlers={})
        plan = WorkflowPlan(
            name="x",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", handler_name="nope")],
        )
        result = await engine.run(plan)
        assert result.success is False

    async def test_gate_exception_does_not_crash_pipeline(self) -> None:
        """Sage D5 — a raising gate is caught by the pipeline's outer try/except."""
        from bonfire.engine.pipeline import PipelineResult

        class _ExplodingGate:
            async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
                raise RuntimeError("gate exploded")

        engine = _make_engine(gate_registry={"boom": _ExplodingGate()})
        plan = WorkflowPlan(
            name="g",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", gates=["boom"])],
        )
        result = await engine.run(plan)
        assert isinstance(result, PipelineResult)
        # Must not raise — result may be success=False, caller inspects.


# ===========================================================================
# 15. Handlers as stage executors
# ===========================================================================


class TestHandlers:
    """Stages with handler_name use handler registry instead of backend."""

    async def test_handler_used_instead_of_backend(self) -> None:
        handler = _MockHandler(result="custom-result")
        backend = _MockBackend()
        engine = _make_engine(backend=backend, handlers={"custom": handler})
        plan = WorkflowPlan(
            name="h",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", handler_name="custom")],
        )
        result = await engine.run(plan)
        assert result.success is True
        assert handler.calls == 1
        assert len(backend.calls) == 0

    async def test_unknown_handler_fails_gracefully(self) -> None:
        engine = _make_engine(handlers={})
        plan = WorkflowPlan(
            name="h",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", handler_name="missing")],
        )
        result = await engine.run(plan)
        assert result.success is False


# ===========================================================================
# 16. PipelineResult runtime — totals populated on run
# ===========================================================================


class TestRunResultFields:
    """Pipeline runs populate total_cost_usd / duration_seconds / failed_stage."""

    async def test_tracks_total_cost(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        plan = _linear_plan("s1", "s2")
        result = await engine.run(plan)
        # Each stage costs 0.01 under the default MockBackend.
        assert result.total_cost_usd == pytest.approx(0.02)

    async def test_tracks_duration(self) -> None:
        engine = _make_engine()
        result = await engine.run(_single_plan())
        assert result.duration_seconds >= 0.0

    async def test_failed_stage_populated_on_failure(self) -> None:
        backend = _MockBackend(fail_agents={"s1"})
        engine = _make_engine(backend=backend)
        result = await engine.run(_single_plan(agent_name="s1"))
        assert result.success is False
        assert result.failed_stage == "s1"


# ===========================================================================
# 17. initial_envelope metadata merging
# ===========================================================================


class TestInitialEnvelope:
    """initial_envelope metadata merges; stage role overrides on collision."""

    async def test_initial_metadata_propagates_to_stages(self) -> None:
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="meta",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1")],
        )
        initial = Envelope(task="t", metadata={"ticket_ref": "EX-1"})
        await engine.run(plan, initial_envelope=initial)

        assert backend.calls
        assert backend.calls[0].metadata.get("ticket_ref") == "EX-1"

    async def test_stage_role_overrides_initial_metadata(self) -> None:
        """Stage-level role wins on key collision (last-write)."""
        backend = _MockBackend()
        engine = _make_engine(backend=backend)
        plan = WorkflowPlan(
            name="meta",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="s1", agent_name="s1", role="stage-role")],
        )
        initial = Envelope(task="t", metadata={"role": "initial-role"})
        await engine.run(plan, initial_envelope=initial)

        assert backend.calls[0].metadata.get("role") == "stage-role"
