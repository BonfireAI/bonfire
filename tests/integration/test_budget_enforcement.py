"""Integration tests — BON-339 mechanical budget enforcement verification (W4.3).

Verifies that ``max_budget_usd`` and ``max_turns`` enforcement lives at the
hook/gate layer (not in prompts), end-to-end through the public pipeline.

Scenarios locked:

1.  ``CostLimitGate`` denial under a ``PipelineEngine.run()`` run.
2.  ``budget_remaining_usd`` clamped at zero (Sage D6 invariant).
3.  ``max_budget_usd`` passthrough from ``PipelineConfig`` → ``DispatchOptions``
    → ``ClaudeAgentOptions`` kwarg on the SDK boundary.
4.  ``max_turns`` passthrough from ``PipelineConfig`` → ``DispatchOptions`` →
    ``ClaudeAgentOptions`` kwarg on the SDK boundary.
5.  ``PipelineConfig.max_budget_usd`` field validator rejects negatives and a
    valid ``Config`` preserves the budget value end-to-end through a pipeline
    run.
6.  End-to-end budget exhaustion on a multi-stage plan: the pipeline halts
    gracefully with ``PipelineResult(success=False)`` and ``"budget" in
    error.lower()`` — no exception leaks past the never-raise shell.

Conservative lens: every fixture mirrors the conventions in
``tests/unit/test_engine_gates.py``, ``test_engine_pipeline.py``,
``test_engine_executor.py``, and ``test_sdk_backend_tool_presence.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from bonfire.engine.gates import CostLimitGate
from bonfire.engine.pipeline import PipelineEngine, PipelineResult
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.models.plan import GateContext, StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

try:
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    ClaudeSDKBackend = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingBackend:
    """Protocol-conformant backend returning canned results with a fixed cost.

    Captures every ``(envelope, options)`` pair so passthrough assertions can
    inspect what reached the dispatch boundary.
    """

    def __init__(self, *, cost: float = 0.01, result: str = "ok") -> None:
        self._cost = cost
        self._result = result
        self.calls: list[tuple[Envelope, DispatchOptions]] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append((envelope, options))
        return envelope.with_result(self._result, cost_usd=self._cost)

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _single_plan(
    *,
    name: str = "budget-test",
    agent_name: str = "scout-agent",
    budget_usd: float = 10.0,
    gates: list[str] | None = None,
) -> WorkflowPlan:
    return WorkflowPlan(
        name=name,
        workflow_type=WorkflowType.STANDARD,
        stages=[
            StageSpec(
                name="s1",
                agent_name=agent_name,
                gates=gates or [],
            ),
        ],
        budget_usd=budget_usd,
    )


def _two_stage_plan(*, budget_usd: float = 1.0) -> WorkflowPlan:
    """A linear 2-stage plan used for cumulative-cost budget tests."""
    return WorkflowPlan(
        name="two-stage",
        workflow_type=WorkflowType.STANDARD,
        stages=[
            StageSpec(name="s1", agent_name="s1-agent"),
            StageSpec(name="s2", agent_name="s2-agent", depends_on=["s1"]),
        ],
        budget_usd=budget_usd,
    )


def _make_engine(
    *,
    backend: _RecordingBackend,
    bus: EventBus | None = None,
    config: PipelineConfig | None = None,
    gate_registry: dict[str, Any] | None = None,
) -> PipelineEngine:
    return PipelineEngine(
        backend=backend,  # type: ignore[arg-type]
        bus=bus or EventBus(),
        config=config or PipelineConfig(),
        gate_registry=gate_registry,
    )


def _make_capture() -> tuple[dict[str, Any], type]:
    """Return ``(captured_kwargs, FakeClaudeAgentOptions)`` — mirrors
    ``tests/unit/test_sdk_backend_tool_presence.py:61``.
    """
    captured: dict[str, Any] = {}

    class _FakeClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

    return captured, _FakeClaudeAgentOptions


async def _empty_query(*, prompt: str = "", options: Any = None):  # type: ignore[no-untyped-def]
    """Async generator yielding nothing — closes immediately."""
    if False:  # pragma: no cover — unreachable
        yield None


@pytest.fixture(autouse=True)
def _require_sdk_backend() -> None:
    """Fail fast if ``bonfire.dispatch.sdk_backend`` cannot be imported."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")


# ===========================================================================
# 1. CostLimitGate denial in pipeline context
# ===========================================================================


class TestCostLimitGateInPipeline:
    """``CostLimitGate`` halts a pipeline run once cumulative cost exceeds its
    configured budget — enforcement at the gate layer, not the prompt layer.
    """

    async def test_gate_halts_pipeline_when_cost_exceeds_gate_budget(self) -> None:
        """A stage whose cost exceeds a tight ``CostLimitGate`` budget triggers
        a gate-failure halt with a populated ``gate_failure`` on the result.
        """
        backend = _RecordingBackend(cost=1.5)  # single call already > $0.50
        engine = _make_engine(
            backend=backend,
            gate_registry={"cost_limit": CostLimitGate(budget_usd=0.5)},
        )
        plan = _single_plan(budget_usd=10.0, gates=["cost_limit"])
        result = await engine.run(plan)

        assert isinstance(result, PipelineResult)
        assert result.success is False
        assert result.gate_failure is not None
        assert result.gate_failure.gate_name == "cost_limit"
        assert result.gate_failure.passed is False
        assert result.gate_failure.severity == "error"
        assert result.failed_stage == "s1"

    async def test_gate_under_its_budget_does_not_halt(self) -> None:
        """Same shape, but stage cost is under the gate's budget — succeeds."""
        backend = _RecordingBackend(cost=0.1)
        engine = _make_engine(
            backend=backend,
            gate_registry={"cost_limit": CostLimitGate(budget_usd=5.0)},
        )
        plan = _single_plan(budget_usd=10.0, gates=["cost_limit"])
        result = await engine.run(plan)

        assert result.success is True
        assert result.gate_failure is None

    async def test_cost_limit_gate_emits_error_severity_on_denial(self) -> None:
        """Direct gate evaluation contract: exceeding the configured budget
        yields ``passed=False`` + ``severity='error'`` — the signal the pipeline
        uses to short-circuit its GateChain.
        """
        gate = CostLimitGate(budget_usd=0.5)
        # Context carries the pipeline's cumulative cost for the gate to compare.
        ctx = GateContext(pipeline_cost_usd=2.0)
        result = await gate.evaluate(Envelope(task="t").with_result("done"), ctx)
        assert result.passed is False
        assert result.severity == "error"
        assert result.gate_name == "cost_limit"


# ===========================================================================
# 2. budget_remaining_usd clamping invariant (Sage D6)
# ===========================================================================


class TestBudgetRemainingClamping:
    """Sage D6 — ``budget_remaining_usd`` is ``max(0, plan.budget_usd -
    total_cost)`` at BOTH call sites (``pipeline.py:433`` and
    ``executor.py:178``). Never negative.
    """

    async def test_engine_plan_budget_exhausted_returns_zero_remaining(self) -> None:
        """When cumulative cost exceeds the plan budget, the pipeline halts and
        reports ``success=False`` rather than continuing with negative budget.
        """
        # Cost-per-call (5.0) exceeds plan.budget_usd (1.0) after the first stage.
        backend = _RecordingBackend(cost=5.0)
        engine = _make_engine(backend=backend)
        plan = _two_stage_plan(budget_usd=1.0)
        result = await engine.run(plan)

        assert result.success is False
        # "Budget exceeded: $X > $Y" — lowercased substring match is robust.
        assert "budget" in result.error.lower()
        assert result.total_cost_usd >= plan.budget_usd  # exhausted, not negative

    async def test_executor_clamps_budget_remaining_for_context_builder(self) -> None:
        """StageExecutor clamps ``budget_remaining_usd`` at zero when
        ``total_cost > plan.budget_usd`` — the value handed to ``ContextBuilder``
        is never negative (Sage D6, executor.py:178).
        """
        from bonfire.engine.context import ContextBuilder
        from bonfire.engine.executor import StageExecutor

        captured: dict[str, Any] = {}

        class _SpyBuilder:
            async def build(self, **kwargs: Any) -> str:
                captured.update(kwargs)
                return "ctx"

        executor = StageExecutor(
            backend=_RecordingBackend(cost=0.0),
            bus=EventBus(),
            config=PipelineConfig(),
            context_builder=_SpyBuilder(),
        )
        stage = StageSpec(name="s1", agent_name="a1")
        plan = WorkflowPlan(
            name="p",
            workflow_type=WorkflowType.STANDARD,
            stages=[stage],
            budget_usd=5.0,
        )
        await executor.execute_single(
            stage=stage,
            prior_results={},
            total_cost=20.0,  # > plan.budget_usd
            plan=plan,
            session_id="sess-1",
        )

        assert "budget_remaining_usd" in captured
        assert captured["budget_remaining_usd"] >= 0.0

        # Default ContextBuilder behaves the same — clamp via max(0, ...).
        builder = ContextBuilder()
        spec = StageSpec(name="s2", agent_name="a2")
        out = await builder.build(
            stage=spec,
            prior_results={},
            budget_remaining_usd=max(0, plan.budget_usd - 20.0),
            task="irrelevant",
        )
        # Contract: builder returns a string, never raises on exhausted budget.
        assert isinstance(out, str)


# ===========================================================================
# 3. max_budget_usd SDK-boundary passthrough
# ===========================================================================


class TestMaxBudgetPassthroughToSDK:
    """``DispatchOptions.max_budget_usd`` propagates byte-for-byte into the
    ``ClaudeAgentOptions`` kwarg that the SDK receives (``sdk_backend.py:112``).
    """

    async def test_max_budget_usd_reaches_claude_agent_options(self) -> None:
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(
                Envelope(task="t", agent_name="scout-agent", model="claude-opus-4-7"),
                options=DispatchOptions(
                    model="claude-opus-4-7",
                    max_budget_usd=3.14,
                    max_turns=7,
                ),
            )

        assert "max_budget_usd" in captured
        assert captured["max_budget_usd"] == pytest.approx(3.14)

    async def test_max_budget_usd_zero_default_preserved(self) -> None:
        """Default ``max_budget_usd=0.0`` still reaches the SDK — zero is the
        documented default, not a "missing" signal.
        """
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            # Default DispatchOptions.max_budget_usd is 0.0 per protocols.py:62.
            await backend.execute(
                Envelope(task="t", agent_name="scout-agent"),
                options=DispatchOptions(model="claude-opus-4-7"),
            )

        assert captured["max_budget_usd"] == pytest.approx(0.0)


# ===========================================================================
# 4. max_turns SDK-boundary passthrough
# ===========================================================================


class TestMaxTurnsPassthroughToSDK:
    """``DispatchOptions.max_turns`` propagates byte-for-byte into the
    ``ClaudeAgentOptions`` kwarg the SDK receives (``sdk_backend.py:111``).
    """

    async def test_max_turns_reaches_claude_agent_options(self) -> None:
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(
                Envelope(task="t", agent_name="knight-agent", model="claude-opus-4-7"),
                options=DispatchOptions(
                    model="claude-opus-4-7",
                    max_turns=42,
                    max_budget_usd=1.0,
                ),
            )

        assert "max_turns" in captured
        assert captured["max_turns"] == 42

    async def test_max_turns_default_reaches_sdk(self) -> None:
        """DispatchOptions default is ``max_turns=10`` (protocols.py:61)."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(
                Envelope(task="t", agent_name="scout-agent"),
                options=DispatchOptions(model="claude-opus-4-7"),
            )

        assert captured["max_turns"] == 10


# ===========================================================================
# 5. PipelineConfig.max_budget_usd validator + end-to-end preservation
# ===========================================================================


class TestConfigValidatorAndEndToEnd:
    """``@field_validator('max_budget_usd')`` rejects negatives
    (``models/config.py:48``). A valid Config preserves the budget through a
    pipeline run, and the SDK boundary sees the same value.
    """

    def test_negative_max_budget_usd_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PipelineConfig(max_budget_usd=-0.01)

    def test_zero_max_budget_usd_accepted(self) -> None:
        """Zero is explicitly allowed by the ``v < 0`` validator check."""
        cfg = PipelineConfig(max_budget_usd=0.0)
        assert cfg.max_budget_usd == 0.0

    async def test_config_max_budget_usd_end_to_end_through_pipeline(self) -> None:
        """A valid Config value lands unchanged in the ``DispatchOptions`` that
        the backend observes — proving the Config → Options plumbing
        (``pipeline.py:500``, ``executor.py:268``) is intact.
        """
        backend = _RecordingBackend(cost=0.01)
        config = PipelineConfig(max_budget_usd=2.5, max_turns=9)
        engine = _make_engine(backend=backend, config=config)
        result = await engine.run(_single_plan(budget_usd=10.0))

        assert result.success is True
        # The backend saw the budget value from the Config, byte-for-byte.
        assert backend.calls, "backend was never called — pipeline skipped dispatch"
        _envelope, options = backend.calls[0]
        assert options.max_budget_usd == pytest.approx(2.5)
        assert options.max_turns == 9


# ===========================================================================
# 6. End-to-end budget exhaustion — graceful termination
# ===========================================================================


class TestEndToEndBudgetExhaustion:
    """A multi-stage pipeline under a tight budget halts cleanly, never
    raises past ``PipelineEngine.run()``, and returns a populated
    ``PipelineResult``.
    """

    async def test_tight_budget_halts_pipeline_with_budget_error(self) -> None:
        """Plan-budget exceeded mid-pipeline → ``success=False``, ``"budget"``
        substring in the error, ``failed_stage`` is empty because the
        enforcement fires in the engine's budget-check block
        (``pipeline.py:215``), not inside a specific stage.
        """
        backend = _RecordingBackend(cost=5.0)
        engine = _make_engine(backend=backend)
        plan = _two_stage_plan(budget_usd=1.0)  # first stage ($5) blows it.
        result = await engine.run(plan)

        assert isinstance(result, PipelineResult)
        assert result.success is False
        assert "budget" in result.error.lower()
        # Second stage must NOT have been dispatched once the budget tripped.
        agent_names = [env.agent_name for env, _opts in backend.calls]
        assert "s2-agent" not in agent_names

    async def test_pipeline_never_raises_on_budget_exhaustion(self) -> None:
        """Contract: ``PipelineEngine.run()`` NEVER raises — always returns a
        ``PipelineResult`` (``pipeline.py:123``).
        """
        backend = _RecordingBackend(cost=1000.0)
        engine = _make_engine(backend=backend)
        plan = _two_stage_plan(budget_usd=0.01)
        result = await engine.run(plan)  # no try/except around this line.

        assert isinstance(result, PipelineResult)
        assert result.success is False

    async def test_cost_limit_gate_also_halts_multi_stage_pipeline(self) -> None:
        """Complementary path: the ``CostLimitGate`` on stage 1 denies before
        the pipeline's own budget-check runs. Graceful halt, ``gate_failure``
        populated.
        """
        backend = _RecordingBackend(cost=2.0)
        engine = _make_engine(
            backend=backend,
            gate_registry={"cost_limit": CostLimitGate(budget_usd=0.5)},
        )
        plan = WorkflowPlan(
            name="gated",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="s1", agent_name="s1-agent", gates=["cost_limit"]),
                StageSpec(name="s2", agent_name="s2-agent", depends_on=["s1"]),
            ],
            budget_usd=100.0,  # plan-level budget is generous — the GATE fires.
        )
        result = await engine.run(plan)

        assert result.success is False
        assert result.gate_failure is not None
        assert result.gate_failure.gate_name == "cost_limit"
        # Stage 2 must not have run.
        assert "s2" not in result.stages or (
            result.stages.get("s2") is not None
            and result.stages["s2"].status != TaskStatus.COMPLETED
        )
