"""Canonical RED — ``bonfire.engine.executor.StageExecutor`` (BON-334).

Synthesized from Knight-A orchestration + Knight-B contract fidelity.

StageExecutor is where a stage actually runs. A sloppy executor:
    - Raises exceptions up to the pipeline (must never raise — C19).
    - Runs infinite retry loops.
    - Loses track of iterations.
    - Does not emit the right events.
    - Leaks state between parallel stages.

Sage decisions:
    D3: No ``compiler`` kwarg. Public v0.1 omits it entirely. Future waves
        may re-introduce it via a dedicated ticket.
    D4: ``vault_advisor`` is optional and defaults to None. When None, no
        pre-dispatch vault check is performed.
    D11: Public ``PipelineConfig`` has NO ``dispatch_timeout_seconds`` field.
        The backend-dispatch path MUST NOT read it from config. Warrior
        passes ``timeout_seconds=None`` (or omits it) to
        ``execute_with_retry`` — this test suite does not assert the exact
        value but does NOT require a timeout be sourced from config.
    D13: ``max_iterations`` semantics — exactly ``spec.max_iterations``
        attempts on persistent failure (not "at least").

Contract locked (executor):
    1. Importable from both ``bonfire.engine.executor`` and ``bonfire.engine``.
    2. Constructor is fully kw-only with: backend, bus, config, handlers?,
       context_builder?, vault_advisor?, project_root?. NO ``compiler``.
    3. ``execute_single(*, stage, prior_results, total_cost, plan, session_id)``
       is async, kw-only, returns Envelope, NEVER raises.
    4. ``execute_parallel(*, stages, prior_results, total_cost, plan, session_id)``
       is async, kw-only, returns dict[str, Envelope] via TaskGroup.
    5. Handler route dispatches to handlers[stage.handler_name].
    6. Unknown handler → Envelope(status=FAILED, error.error_type="config"),
       never raises.
    7. Backend route goes through execute_with_retry with DispatchOptions.
    8. Iteration: exactly spec.max_iterations attempts on persistent failure,
       stops early on first success.
    9. Events: StageStarted (always), StageCompleted (success),
       StageFailed (exhausted failures).
   10. Events carry the caller-supplied session_id.
   11. ContextBuilder invoked with ``budget_remaining_usd = max(0, budget - cost)``.
   12. Never-raise discipline across backend, handler, and context builder.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from bonfire.dispatch.result import DispatchResult
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    StageCompleted,
    StageFailed,
    StageStarted,
)
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _MockBackend:
    """Default-OK backend with configurable per-agent failures."""

    def __init__(
        self,
        *,
        fail_agents: set[str] | None = None,
        cost: float = 0.01,
    ) -> None:
        self.fail_agents = fail_agents or set()
        self.cost = cost
        self.calls: list[tuple[Envelope, DispatchOptions]] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append((envelope, options))
        if envelope.agent_name in self.fail_agents:
            return envelope.with_error(
                ErrorDetail(error_type="agent", message=f"{envelope.agent_name} failed")
            )
        return envelope.with_result(f"result from {envelope.agent_name}", cost_usd=self.cost)

    async def health_check(self) -> bool:
        return True


class _MockHandler:
    """Stub handler that marks the envelope as handled or failed."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list[tuple[StageSpec, Envelope, dict[str, str]]] = []

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        self.calls.append((stage, envelope, prior_results))
        if self._fail:
            return envelope.with_error(ErrorDetail(error_type="handler", message="handler failed"))
        return envelope.with_result(f"handled by {stage.handler_name}", cost_usd=0.001)


class _EventCollector:
    """Collects events emitted on a bus."""

    def __init__(self) -> None:
        self.events: list[BonfireEvent] = []

    async def __call__(self, event: BonfireEvent) -> None:
        self.events.append(event)

    def of_type(self, cls: type) -> list[BonfireEvent]:
        return [e for e in self.events if isinstance(e, cls)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stage(
    name: str = "scout",
    agent_name: str | None = None,
    *,
    handler_name: str | None = None,
    max_iterations: int = 1,
    parallel_group: str | None = None,
) -> StageSpec:
    return StageSpec(
        name=name,
        agent_name=agent_name if agent_name is not None else f"{name}-agent",
        handler_name=handler_name,
        max_iterations=max_iterations,
        parallel_group=parallel_group,
    )


def _plan(*stages: StageSpec, budget: float = 10.0) -> WorkflowPlan:
    return WorkflowPlan(
        name="executor-test",
        workflow_type=WorkflowType.STANDARD,
        stages=list(stages),
        budget_usd=budget,
    )


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def config() -> PipelineConfig:
    return PipelineConfig()


@pytest.fixture()
def collector(bus: EventBus) -> _EventCollector:
    c = _EventCollector()
    bus.subscribe_all(c)
    return c


# ===========================================================================
# 1. Imports
# ===========================================================================


class TestImports:
    """StageExecutor is importable from both canonical paths."""

    def test_import_from_module(self) -> None:
        from bonfire.engine.executor import StageExecutor

        assert StageExecutor is not None

    def test_import_from_engine_package(self) -> None:
        from bonfire.engine import StageExecutor

        assert StageExecutor is not None


# ===========================================================================
# 2. Constructor — kw-only, documented dep set (Sage D3 drops compiler)
# ===========================================================================


class TestConstructor:
    """Constructor is kw-only with the v0.1 dep set (no compiler — Sage D3)."""

    def test_constructor_is_keyword_only(self) -> None:
        from bonfire.engine.executor import StageExecutor

        sig = inspect.signature(StageExecutor.__init__)
        params = list(sig.parameters.values())[1:]  # skip self
        assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in params)

    def test_accepts_backend_bus_config(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        assert ex is not None

    def test_accepts_handlers_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, handlers={})
        assert ex is not None

    def test_accepts_context_builder_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.context import ContextBuilder
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            context_builder=ContextBuilder(),
        )
        assert ex is not None

    def test_accepts_vault_advisor_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        """Sage D4 — vault_advisor is optional; None is accepted."""
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, vault_advisor=None)
        assert ex is not None

    def test_accepts_project_root_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, project_root="/tmp/proj")
        assert ex is not None

    def test_rejects_compiler_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        """Sage D3 — ``compiler`` kwarg is NOT accepted in v0.1."""
        from bonfire.engine.executor import StageExecutor

        with pytest.raises(TypeError):
            StageExecutor(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                compiler=object(),  # type: ignore[call-arg]
            )


# ===========================================================================
# 3. execute_single — signature
# ===========================================================================


class TestExecuteSingleSignature:
    """execute_single: async, kw-only, all documented params present."""

    def test_is_async(self) -> None:
        from bonfire.engine.executor import StageExecutor

        assert inspect.iscoroutinefunction(StageExecutor.execute_single)

    def test_is_keyword_only(self) -> None:
        from bonfire.engine.executor import StageExecutor

        sig = inspect.signature(StageExecutor.execute_single)
        params = list(sig.parameters.values())[1:]  # skip self
        assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in params)

    @pytest.mark.parametrize(
        "param_name",
        ["stage", "prior_results", "total_cost", "plan", "session_id"],
    )
    def test_required_params(self, param_name: str) -> None:
        from bonfire.engine.executor import StageExecutor

        sig = inspect.signature(StageExecutor.execute_single)
        assert param_name in sig.parameters


# ===========================================================================
# 4. execute_single — basic success and failure
# ===========================================================================


class TestExecuteSingle:
    """execute_single returns an Envelope for every outcome."""

    async def test_returns_envelope_on_success(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage()
        plan = _plan(stage)
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="s1"
        )
        assert isinstance(result, Envelope)
        assert result.status == TaskStatus.COMPLETED

    async def test_result_has_non_empty_string(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage()
        plan = _plan(stage)
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="s1"
        )
        assert result.result != ""

    async def test_failed_backend_returns_failed_envelope(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend(fail_agents={"scout-agent"})
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage()
        plan = _plan(stage)
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="s1"
        )
        assert result.status == TaskStatus.FAILED


# ===========================================================================
# 5. Handler dispatch
# ===========================================================================


class TestHandlerDispatch:
    """Stages with ``handler_name`` route to handlers, bypassing the backend."""

    async def test_handler_used_when_name_set(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        handler = _MockHandler()
        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config, handlers={"custom": handler})
        stage = _stage(handler_name="custom")
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert result.status == TaskStatus.COMPLETED
        assert len(handler.calls) == 1
        assert len(backend.calls) == 0  # backend NOT called when handler handles

    async def test_handler_receives_prior_results_as_strings(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        handler = _MockHandler()
        ex = StageExecutor(
            backend=_MockBackend(), bus=bus, config=config, handlers={"custom": handler}
        )
        prior = {"prev": Envelope(task="t", result="PRIOR_OUTPUT", status=TaskStatus.COMPLETED)}
        stage = _stage(handler_name="custom")
        await ex.execute_single(
            stage=stage,
            prior_results=prior,
            total_cost=0.0,
            plan=_plan(_stage(name="prev", agent_name="prev"), stage),
            session_id="s",
        )
        _, _, prior_str = handler.calls[0]
        assert "PRIOR_OUTPUT" in prior_str.get("prev", "")


# ===========================================================================
# 6. Unknown handler — fails gracefully with error_type="config"
# ===========================================================================


class TestUnknownHandler:
    """Unknown handler_name -> failed envelope, error_type='config', no raise."""

    async def test_unknown_handler_returns_config_error_envelope(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage(handler_name="does-not-exist")
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "config"
        assert "does-not-exist" in result.error.message

    async def test_unknown_handler_does_not_raise(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage(handler_name="ghost")
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert isinstance(result, Envelope)


# ===========================================================================
# 7. Iteration — exact attempt count (Sage D13)
# ===========================================================================


class TestIteration:
    """max_iterations bounds the retry count to EXACTLY that number (Sage D13)."""

    async def test_max_iterations_one_calls_backend_once(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage(max_iterations=1)
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert len(backend.calls) == 1

    async def test_persistent_failure_exhausts_exact_iterations(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Exactly spec.max_iterations attempts on persistent failure."""
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend(fail_agents={"scout-agent"})
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage(max_iterations=3)
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert result.status == TaskStatus.FAILED
        assert len(backend.calls) == 3

    async def test_success_on_retry_stops_iterating(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        call_count = 0

        class _FlakeyBackend:
            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return envelope.with_error(ErrorDetail(error_type="agent", message="transient"))
                return envelope.with_result("ok on retry", cost_usd=0.01)

            async def health_check(self) -> bool:
                return True

        ex = StageExecutor(backend=_FlakeyBackend(), bus=bus, config=config)
        stage = _stage(max_iterations=5)
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert result.status == TaskStatus.COMPLETED
        assert call_count == 2  # stopped right after success


# ===========================================================================
# 8. execute_parallel — concurrent, dict-keyed by stage name
# ===========================================================================


class TestExecuteParallelSignature:
    """execute_parallel: async, kw-only."""

    def test_is_async(self) -> None:
        from bonfire.engine.executor import StageExecutor

        assert inspect.iscoroutinefunction(StageExecutor.execute_parallel)

    def test_is_keyword_only(self) -> None:
        from bonfire.engine.executor import StageExecutor

        sig = inspect.signature(StageExecutor.execute_parallel)
        params = list(sig.parameters.values())[1:]
        assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in params)


class TestExecuteParallel:
    """execute_parallel runs stages concurrently via TaskGroup."""

    async def test_returns_dict_keyed_by_stage_name(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        s1 = _stage(name="alpha", agent_name="a", parallel_group="g")
        s2 = _stage(name="beta", agent_name="b", parallel_group="g")
        result = await ex.execute_parallel(
            stages=[s1, s2], prior_results={}, total_cost=0.0, plan=_plan(s1, s2), session_id="s"
        )
        assert isinstance(result, dict)
        assert set(result.keys()) == {"alpha", "beta"}
        assert all(isinstance(v, Envelope) for v in result.values())

    async def test_all_completed(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        s1 = _stage(name="alpha", agent_name="a", parallel_group="g")
        s2 = _stage(name="beta", agent_name="b", parallel_group="g")
        result = await ex.execute_parallel(
            stages=[s1, s2], prior_results={}, total_cost=0.0, plan=_plan(s1, s2), session_id="s"
        )
        assert result["alpha"].status == TaskStatus.COMPLETED
        assert result["beta"].status == TaskStatus.COMPLETED

    async def test_parallel_runs_concurrently_not_sequentially(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Parallel dispatch should not serialize awaitables."""
        from bonfire.engine.executor import StageExecutor

        class _SlowBackend:
            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                await asyncio.sleep(0.05)
                return envelope.with_result("done", cost_usd=0.0)

            async def health_check(self) -> bool:
                return True

        ex = StageExecutor(backend=_SlowBackend(), bus=bus, config=config)
        s1 = _stage(name="alpha", agent_name="a", parallel_group="g")
        s2 = _stage(name="beta", agent_name="b", parallel_group="g")

        start = time.monotonic()
        await ex.execute_parallel(
            stages=[s1, s2], prior_results={}, total_cost=0.0, plan=_plan(s1, s2), session_id="s"
        )
        elapsed = time.monotonic() - start
        # Sequential = ~0.1s; parallel should finish well under that.
        assert elapsed < 0.09


# ===========================================================================
# 9. Parallel failure handling — per-stage, never raised
# ===========================================================================


class TestParallelFailure:
    """Failures in a parallel group are captured per-stage, never raised."""

    async def test_one_failure_captured(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend(fail_agents={"b"})
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        s1 = _stage(name="good", agent_name="a", parallel_group="g")
        s2 = _stage(name="bad", agent_name="b", parallel_group="g")
        result = await ex.execute_parallel(
            stages=[s1, s2], prior_results={}, total_cost=0.0, plan=_plan(s1, s2), session_id="s"
        )
        assert result["bad"].status == TaskStatus.FAILED
        assert result["good"].status == TaskStatus.COMPLETED


# ===========================================================================
# 10. Event emission
# ===========================================================================


class TestEventEmission:
    """StageStarted / StageCompleted / StageFailed events emitted in shape."""

    async def test_stage_started_emitted(
        self, bus: EventBus, config: PipelineConfig, collector: _EventCollector
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage()
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        started = collector.of_type(StageStarted)
        assert len(started) == 1
        assert started[0].stage_name == "scout"
        assert started[0].agent_name == "scout-agent"

    async def test_stage_completed_emitted_on_success(
        self, bus: EventBus, config: PipelineConfig, collector: _EventCollector
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage()
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        completed = collector.of_type(StageCompleted)
        assert len(completed) == 1
        assert completed[0].stage_name == "scout"

    async def test_stage_failed_emitted_on_exhaustion(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _MockBackend(fail_agents={"scout-agent"})
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage(max_iterations=1)
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        failed = collector.of_type(StageFailed)
        assert len(failed) == 1

    async def test_stage_completed_includes_cost(
        self, bus: EventBus, config: PipelineConfig, collector: _EventCollector
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage()
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        completed = collector.of_type(StageCompleted)
        assert completed[0].cost_usd >= 0.0

    async def test_stage_failed_has_error_message(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        collector = _EventCollector()
        bus.subscribe_all(collector)
        backend = _MockBackend(fail_agents={"scout-agent"})
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage()
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert collector.of_type(StageFailed)[0].error_message != ""

    async def test_events_carry_session_id(
        self, bus: EventBus, config: PipelineConfig, collector: _EventCollector
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        stage = _stage()
        await ex.execute_single(
            stage=stage,
            prior_results={},
            total_cost=0.0,
            plan=_plan(stage),
            session_id="sid-zz",
        )
        for e in collector.events:
            assert e.session_id == "sid-zz"


# ===========================================================================
# 11. Context building — budget arithmetic (Sage D6)
# ===========================================================================


class TestContextBuilding:
    """ContextBuilder is invoked with ``budget_remaining_usd = max(0, budget-cost)``."""

    async def test_context_builder_called(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.context import ContextBuilder
        from bonfire.engine.executor import StageExecutor

        builder = ContextBuilder()
        builder.build = AsyncMock(wraps=builder.build)  # type: ignore[method-assign]

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, context_builder=builder)
        stage = _stage()
        await ex.execute_single(
            stage=stage,
            prior_results={},
            total_cost=1.0,
            plan=_plan(stage, budget=5.0),
            session_id="s",
        )
        builder.build.assert_called_once()

    async def test_context_builder_receives_budget_remaining(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.context import ContextBuilder
        from bonfire.engine.executor import StageExecutor

        builder = ContextBuilder()
        builder.build = AsyncMock(wraps=builder.build)  # type: ignore[method-assign]

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, context_builder=builder)
        stage = _stage()
        await ex.execute_single(
            stage=stage,
            prior_results={},
            total_cost=3.0,
            plan=_plan(stage, budget=10.0),
            session_id="s",
        )
        kwargs = builder.build.call_args.kwargs
        assert kwargs["budget_remaining_usd"] == pytest.approx(7.0)

    async def test_budget_remaining_clamped_at_zero(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — budget_remaining_usd never goes negative."""
        from bonfire.engine.context import ContextBuilder
        from bonfire.engine.executor import StageExecutor

        builder = ContextBuilder()
        builder.build = AsyncMock(wraps=builder.build)  # type: ignore[method-assign]

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, context_builder=builder)
        stage = _stage()
        await ex.execute_single(
            stage=stage,
            prior_results={},
            total_cost=20.0,
            plan=_plan(stage, budget=5.0),
            session_id="s",
        )
        kwargs = builder.build.call_args.kwargs
        assert kwargs["budget_remaining_usd"] >= 0.0

    async def test_custom_context_builder_injected(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Injected context_builder replaces the default."""
        from bonfire.engine.executor import StageExecutor

        class _CustomBuilder:
            called = False

            async def build(self, **kwargs: Any) -> str:
                _CustomBuilder.called = True
                return "custom context"

        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            context_builder=_CustomBuilder(),  # type: ignore[arg-type]
        )
        stage = _stage()
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert _CustomBuilder.called


# ===========================================================================
# 12. Backend dispatch — goes through execute_with_retry with DispatchOptions
# ===========================================================================


class TestBackendDispatch:
    """Backend route goes through dispatch.runner.execute_with_retry (V1 261-281)."""

    async def test_backend_receives_dispatch_options_object(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage()
        await ex.execute_single(
            stage=stage,
            prior_results={},
            total_cost=0.0,
            plan=_plan(stage),
            session_id="s",
        )
        assert backend.calls
        _, options = backend.calls[0]
        assert isinstance(options, DispatchOptions)

    async def test_execute_with_retry_called(self, bus: EventBus, config: PipelineConfig) -> None:
        from bonfire.engine.executor import StageExecutor

        mock_result = DispatchResult(
            envelope=Envelope(task="t").with_result("ok", cost_usd=0.01),
            duration_seconds=0.1,
            retries=0,
            cost_usd=0.01,
        )
        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        with patch(
            "bonfire.engine.executor.execute_with_retry",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as spy:
            stage = _stage()
            await ex.execute_single(
                stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
            )
            spy.assert_called_once()

    async def test_execute_with_retry_receives_event_bus(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        mock_result = DispatchResult(
            envelope=Envelope(task="t").with_result("ok", cost_usd=0.01),
            duration_seconds=0.1,
            retries=0,
            cost_usd=0.01,
        )
        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        with patch(
            "bonfire.engine.executor.execute_with_retry",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as spy:
            stage = _stage()
            await ex.execute_single(
                stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
            )
            call_kwargs = spy.call_args.kwargs
            assert call_kwargs.get("event_bus") is bus


# ===========================================================================
# 13. Never-raise discipline (C19) — backend, handler, context builder
# ===========================================================================


class TestNeverRaises:
    """Every execute_single path returns an Envelope — no exceptions escape."""

    async def test_backend_exception_does_not_propagate(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        class _Exploding:
            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                raise RuntimeError("boom")

            async def health_check(self) -> bool:
                return True

        ex = StageExecutor(backend=_Exploding(), bus=bus, config=config)
        stage = _stage()
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert isinstance(result, Envelope)
        assert result.status == TaskStatus.FAILED

    async def test_handler_exception_does_not_propagate(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        class _ExplodingHandler:
            async def handle(
                self,
                stage: StageSpec,
                envelope: Envelope,
                prior_results: dict[str, str],
            ) -> Envelope:
                raise ValueError("handler explosion")

        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            handlers={"explode": _ExplodingHandler()},  # type: ignore[dict-item]
        )
        stage = _stage(handler_name="explode")
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert isinstance(result, Envelope)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None

    async def test_context_builder_exception_does_not_propagate(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.executor import StageExecutor

        class _Exploding:
            async def build(self, **kwargs: Any) -> str:
                raise TypeError("ctx fail")

        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            context_builder=_Exploding(),  # type: ignore[arg-type]
        )
        stage = _stage()
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="s"
        )
        assert isinstance(result, Envelope)
        assert result.status == TaskStatus.FAILED

    async def test_execute_parallel_captures_exceptions_per_stage(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Parallel failures surface via the result dict, never raise up."""
        from bonfire.engine.executor import StageExecutor

        class _SelectivelyExploding:
            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                if envelope.agent_name == "b":
                    raise RuntimeError("b bombed")
                return envelope.with_result("ok", cost_usd=0.0)

            async def health_check(self) -> bool:
                return True

        ex = StageExecutor(backend=_SelectivelyExploding(), bus=bus, config=config)
        s1 = _stage(name="good", agent_name="a", parallel_group="g")
        s2 = _stage(name="bad", agent_name="b", parallel_group="g")
        result = await ex.execute_parallel(
            stages=[s1, s2], prior_results={}, total_cost=0.0, plan=_plan(s1, s2), session_id="s"
        )
        assert result["bad"].status == TaskStatus.FAILED
        assert result["good"].status == TaskStatus.COMPLETED
