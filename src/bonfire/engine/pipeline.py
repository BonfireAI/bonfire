"""Pipeline execution engine -- the heart of Bonfire.

Executes a WorkflowPlan as a DAG of stages using TopologicalSorter.
Features: parallel groups via TaskGroup, gate evaluation, bounce-back,
iteration/retry, budget enforcement, event emission, resume from checkpoint.

``PipelineEngine.run()`` NEVER raises -- always returns a PipelineResult.

Sage decisions enforced:
    D3: No ``compiler`` kwarg -- passing it raises ``TypeError``.
    D5: A raising gate is caught by the pipeline's outer try/except.
    D6: ``budget_remaining_usd`` clamped at zero.
    D7: Single bounce -- target runs, original re-runs, gates re-evaluate
        ONCE, then halt regardless of second outcome.
    D8: PipelineResult has exactly 8 fields (frozen).
    D11: ``PipelineConfig`` has no ``dispatch_timeout_seconds``; pass
         ``timeout_seconds=None`` to ``execute_with_retry``.
"""

from __future__ import annotations

import asyncio
import time
from graphlib import TopologicalSorter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from bonfire.dispatch.runner import execute_with_retry
from bonfire.engine import factory
from bonfire.engine.context import ContextBuilder
from bonfire.engine.executor import (
    StageExecutor,  # noqa: F401 -- public re-export for patch/discover
)
from bonfire.engine.model_resolver import resolve_dispatch_model
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    QualityBypassed,
    QualityFailed,
    QualityPassed,
    StageCompleted,
    StageFailed,
    StageSkipped,
    StageStarted,
)
from bonfire.models.plan import GateContext, GateResult, StageSpec, WorkflowPlan
from bonfire.protocols import DispatchOptions

if TYPE_CHECKING:
    from bonfire.dispatch.tool_policy import ToolPolicy
    from bonfire.events.bus import EventBus
    from bonfire.models.config import BonfireSettings, PipelineConfig
    from bonfire.protocols import AgentBackend, QualityGate, StageHandler


# ---------------------------------------------------------------------------
# PipelineResult -- frozen Pydantic model
# ---------------------------------------------------------------------------


class PipelineResult(BaseModel):
    """Immutable result of a full pipeline run."""

    model_config = ConfigDict(frozen=True)

    success: bool
    session_id: str
    stages: dict[str, Envelope] = Field(default_factory=dict)
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str = ""
    failed_stage: str = ""
    gate_failure: GateResult | None = None


# ---------------------------------------------------------------------------
# PipelineEngine
# ---------------------------------------------------------------------------


class PipelineEngine:
    """Executes a WorkflowPlan as a DAG with gates, bounces, and budget control.

    Constructor accepts all dependencies via keyword-only arguments.
    ``run()`` is the sole public method -- a never-raise shell around
    ``_run_inner()``.
    """

    def __init__(
        self,
        *,
        backend: AgentBackend,
        bus: EventBus,
        config: PipelineConfig,
        handlers: dict[str, StageHandler] | None = None,
        gate_registry: dict[str, QualityGate] | None = None,
        context_builder: ContextBuilder | None = None,
        project_root: Any | None = None,
        tool_policy: ToolPolicy | None = None,
        settings: BonfireSettings | None = None,
    ) -> None:
        self._backend = backend
        self._bus = bus
        self._config = config
        self._handlers = handlers or {}
        self._gates = gate_registry or {}
        self._context_builder = context_builder or ContextBuilder()
        self._project_root = project_root
        self._tool_policy = tool_policy
        self._settings = settings if settings is not None else factory.load_settings_or_default()

    # -- Public API ----------------------------------------------------------

    async def run(
        self,
        plan: WorkflowPlan,
        *,
        session_id: str | None = None,
        completed: dict[str, Envelope] | None = None,
        initial_envelope: Envelope | None = None,
    ) -> PipelineResult:
        """Execute a workflow plan. NEVER raises -- returns PipelineResult."""
        sid = session_id or uuid4().hex[:12]
        start = time.monotonic()
        try:
            return await self._run_inner(plan, sid, completed or {}, start, initial_envelope)
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            return PipelineResult(
                success=False,
                session_id=sid,
                error=str(exc),
                duration_seconds=duration,
            )

    # -- Core pipeline loop --------------------------------------------------

    async def _run_inner(
        self,
        plan: WorkflowPlan,
        session_id: str,
        completed: dict[str, Envelope],
        start: float,
        initial_envelope: Envelope | None = None,
    ) -> PipelineResult:
        """The real pipeline execution logic."""
        stages_done: dict[str, Envelope] = dict(completed)
        total_cost = 0.0
        stage_map = self._build_stage_map(plan)

        # Emit PipelineStarted
        await self._emit(
            PipelineStarted(
                session_id=session_id,
                sequence=0,
                plan_name=plan.name,
                budget_usd=plan.budget_usd,
            )
        )

        # Emit StageSkipped for pre-completed stages
        for name in completed:
            await self._emit(
                StageSkipped(
                    session_id=session_id,
                    sequence=0,
                    stage_name=name,
                    reason="pre-completed (resume)",
                )
            )

        # Build DAG -- skip already-completed stages
        skip = set(completed.keys())
        dag = self._build_dag(plan, skip)
        dag.prepare()

        while dag.is_active():
            ready = list(dag.get_ready())
            if not ready:
                break

            # Group by parallel_group for concurrent execution
            groups = self._group_stages(ready, stage_map)

            for group_stages in groups:
                if len(group_stages) > 1:
                    halt, total_cost = await self._run_parallel_group(
                        group_stages,
                        stage_map,
                        stages_done,
                        total_cost,
                        start,
                        session_id,
                        plan,
                        initial_envelope,
                    )
                    if halt is not None:
                        return halt
                else:
                    halt, total_cost = await self._run_single_stage_group(
                        group_stages[0],
                        stage_map,
                        stages_done,
                        total_cost,
                        start,
                        session_id,
                        plan,
                        initial_envelope,
                    )
                    if halt is not None:
                        return halt

                # Budget check after each group
                if total_cost > plan.budget_usd:
                    duration = time.monotonic() - start
                    error_msg = f"Budget exceeded: ${total_cost:.2f} > ${plan.budget_usd:.2f}"
                    await self._emit(
                        PipelineFailed(
                            session_id=session_id,
                            sequence=0,
                            failed_stage="",
                            error_message=error_msg,
                        )
                    )
                    return PipelineResult(
                        success=False,
                        session_id=session_id,
                        stages=stages_done,
                        total_cost_usd=total_cost,
                        duration_seconds=duration,
                        error=error_msg,
                    )

            # Mark all ready nodes as done in the DAG
            for name in ready:
                dag.done(name)

        # Success
        duration = time.monotonic() - start
        await self._emit(
            PipelineCompleted(
                session_id=session_id,
                sequence=0,
                total_cost_usd=total_cost,
                duration_seconds=duration,
                stages_completed=len(stages_done),
            )
        )
        return PipelineResult(
            success=True,
            session_id=session_id,
            stages=stages_done,
            total_cost_usd=total_cost,
            duration_seconds=duration,
        )

    # -- Parallel / single group dispatch ------------------------------------

    async def _run_parallel_group(
        self,
        group_stages: list[str],
        stage_map: dict[str, StageSpec],
        stages_done: dict[str, Envelope],
        total_cost: float,
        start: float,
        session_id: str,
        plan: WorkflowPlan,
        initial_envelope: Envelope | None,
    ) -> tuple[PipelineResult | None, float]:
        """Execute a parallel group via TaskGroup, then evaluate gates."""
        results: dict[str, Envelope] = {}
        async with asyncio.TaskGroup() as tg:
            for stage_name in group_stages:
                spec = stage_map[stage_name]

                async def _run_one(
                    s: StageSpec = spec,
                    sid: str = session_id,
                    tc: float = total_cost,
                    res: dict[str, Envelope] = results,
                    ie: Envelope | None = initial_envelope,
                ) -> None:
                    env = await self._execute_stage(s, stages_done, tc, plan, sid, ie)
                    res[s.name] = env

                tg.create_task(_run_one())

        # Check for failures in parallel group
        for sname, env in results.items():
            stages_done[sname] = env
            total_cost += env.cost_usd
            if env.status == TaskStatus.FAILED:
                duration = time.monotonic() - start
                error_msg = env.error.message if env.error else "stage failed"
                await self._emit(
                    PipelineFailed(
                        session_id=session_id,
                        sequence=0,
                        failed_stage=sname,
                        error_message=error_msg,
                    )
                )
                return (
                    PipelineResult(
                        success=False,
                        session_id=session_id,
                        stages=stages_done,
                        total_cost_usd=total_cost,
                        duration_seconds=duration,
                        error=error_msg,
                        failed_stage=sname,
                    ),
                    total_cost,
                )

        # Gate evaluation for parallel stages
        for sname, env in results.items():
            spec = stage_map[sname]
            halt, cost_delta = await self._handle_gate_result(
                spec,
                env,
                sname,
                stages_done,
                total_cost,
                start,
                session_id,
                plan,
                stage_map,
                initial_envelope,
            )
            total_cost += cost_delta
            if halt is not None:
                return halt, total_cost

        return None, total_cost

    async def _run_single_stage_group(
        self,
        stage_name: str,
        stage_map: dict[str, StageSpec],
        stages_done: dict[str, Envelope],
        total_cost: float,
        start: float,
        session_id: str,
        plan: WorkflowPlan,
        initial_envelope: Envelope | None,
    ) -> tuple[PipelineResult | None, float]:
        """Execute a single stage sequentially, then evaluate gates."""
        spec = stage_map[stage_name]

        env = await self._execute_stage(
            spec, stages_done, total_cost, plan, session_id, initial_envelope
        )
        stages_done[stage_name] = env
        total_cost += env.cost_usd

        if env.status == TaskStatus.FAILED:
            duration = time.monotonic() - start
            error_msg = env.error.message if env.error else "stage failed"
            await self._emit(
                PipelineFailed(
                    session_id=session_id,
                    sequence=0,
                    failed_stage=stage_name,
                    error_message=error_msg,
                )
            )
            return (
                PipelineResult(
                    success=False,
                    session_id=session_id,
                    stages=stages_done,
                    total_cost_usd=total_cost,
                    duration_seconds=duration,
                    error=error_msg,
                    failed_stage=stage_name,
                ),
                total_cost,
            )

        # Gate evaluation
        halt, cost_delta = await self._handle_gate_result(
            spec,
            env,
            stage_name,
            stages_done,
            total_cost,
            start,
            session_id,
            plan,
            stage_map,
            initial_envelope,
        )
        total_cost += cost_delta
        if halt is not None:
            return halt, total_cost

        return None, total_cost

    # -- Stage execution with iteration --------------------------------------

    async def _execute_stage(
        self,
        spec: StageSpec,
        completed: dict[str, Envelope],
        total_cost: float,
        plan: WorkflowPlan,
        session_id: str,
        initial_envelope: Envelope | None = None,
    ) -> Envelope:
        """Execute a single stage with iteration support.

        Tries up to spec.max_iterations times. On success, returns immediately.
        On failure after all iterations, returns the failed envelope.
        """
        await self._emit(
            StageStarted(
                session_id=session_id,
                sequence=0,
                stage_name=spec.name,
                agent_name=spec.agent_name,
            )
        )

        last_envelope: Envelope | None = None

        for _iteration in range(spec.max_iterations):
            # Build context
            context = await self._context_builder.build(
                stage=spec,
                prior_results=completed,
                budget_remaining_usd=max(0, plan.budget_usd - total_cost),
                task=plan.task_description,
            )

            task_prompt = context

            initial_meta: dict[str, Any] = (
                dict(initial_envelope.metadata) if initial_envelope is not None else {}
            )
            stage_role_meta: dict[str, Any] = {"role": spec.role} if spec.role else {}
            # Stage-level role OVERRIDES initial metadata on key collision.
            merged_metadata: dict[str, Any] = {**initial_meta, **stage_role_meta}

            envelope = Envelope(
                envelope_id=session_id,
                task=task_prompt,
                context=context,
                agent_name=spec.agent_name,
                model=spec.model_override or "",
                metadata=merged_metadata,
            )

            # Execute via handler or backend
            if spec.handler_name is not None:
                handler = self._handlers.get(spec.handler_name)
                if handler is None:
                    # Unknown handler -- fail gracefully
                    error_env = envelope.with_error(
                        ErrorDetail(
                            error_type="config",
                            message=f"Unknown handler: {spec.handler_name}",
                        )
                    )
                    await self._emit(
                        StageFailed(
                            session_id=session_id,
                            sequence=0,
                            stage_name=spec.name,
                            agent_name=spec.agent_name,
                            error_message=f"Unknown handler: {spec.handler_name}",
                        )
                    )
                    return error_env

                # Build prior_results as dict[str, str] for handler interface
                prior_str = {k: v.result for k, v in completed.items()}
                try:
                    result_env = await handler.handle(spec, envelope, prior_str)
                except Exception as exc:  # noqa: BLE001
                    result_env = envelope.with_error(
                        ErrorDetail(
                            error_type="handler",
                            message=f"{type(exc).__name__}: {exc}",
                        )
                    )
            else:
                # Use backend -- route through unified runner.
                # Pipeline iteration IS the only pipeline-layer retry, so we
                # pin max_retries=0; the runner handles per-attempt behavior
                # and emits Dispatch* events.
                if self._tool_policy is None or not spec.role:
                    role_tools: list[str] = []
                else:
                    role_tools = self._tool_policy.tools_for(spec.role)
                options = DispatchOptions(
                    model=resolve_dispatch_model(
                        explicit_override=spec.model_override,
                        role=spec.role,
                        settings=self._settings,
                        config=self._config,
                    ),
                    max_turns=self._config.max_turns,
                    max_budget_usd=self._config.max_budget_usd,
                    cwd=str(self._project_root) if self._project_root else "",
                    tools=role_tools,
                    role=spec.role,
                )
                dispatch_result = await execute_with_retry(
                    self._backend,
                    envelope,
                    options,
                    max_retries=0,
                    timeout_seconds=None,
                    event_bus=self._bus,
                )
                result_env = dispatch_result.envelope

            last_envelope = result_env

            if result_env.status != TaskStatus.FAILED:
                await self._emit(
                    StageCompleted(
                        session_id=session_id,
                        sequence=0,
                        stage_name=spec.name,
                        agent_name=spec.agent_name,
                        duration_seconds=0.0,
                        cost_usd=result_env.cost_usd,
                    )
                )
                return result_env

        # All iterations exhausted -- return final failed envelope
        if last_envelope is None:
            last_envelope = Envelope(
                task=spec.name or "<unnamed>", agent_name=spec.agent_name
            ).with_error(ErrorDetail(error_type="executor", message="no iterations executed"))
        await self._emit(
            StageFailed(
                session_id=session_id,
                sequence=0,
                stage_name=spec.name,
                agent_name=spec.agent_name,
                error_message=(
                    last_envelope.error.message if last_envelope.error else "exhausted iterations"
                ),
            )
        )
        return last_envelope

    # -- Gate evaluation chain -----------------------------------------------

    async def _evaluate_gates(
        self,
        spec: StageSpec,
        envelope: Envelope,
        completed: dict[str, Envelope],
        total_cost: float,
        session_id: str,
    ) -> tuple[bool, GateResult | None]:
        """Evaluate all gates for a stage. Returns (all_passed, first_failure)."""
        prior_str = {k: v.result for k, v in completed.items()}
        context = GateContext(pipeline_cost_usd=total_cost, prior_results=prior_str)

        for gate_name in spec.gates:
            gate = self._gates.get(gate_name)
            if gate is None:
                # Unknown gate -- bypass and continue
                await self._emit(
                    QualityBypassed(
                        session_id=session_id,
                        sequence=0,
                        gate_name=gate_name,
                        stage_name=spec.name,
                        reason=f"Gate '{gate_name}' not found in registry",
                    )
                )
                continue

            result = await gate.evaluate(envelope, context)

            if result.passed:
                await self._emit(
                    QualityPassed(
                        session_id=session_id,
                        sequence=0,
                        gate_name=gate_name,
                        stage_name=spec.name,
                    )
                )
            elif result.severity == "error":
                await self._emit(
                    QualityFailed(
                        session_id=session_id,
                        sequence=0,
                        gate_name=gate_name,
                        stage_name=spec.name,
                        severity=result.severity,
                        message=result.message,
                    )
                )
                return False, result
            else:
                # Warning -- log but continue
                await self._emit(
                    QualityFailed(
                        session_id=session_id,
                        sequence=0,
                        gate_name=gate_name,
                        stage_name=spec.name,
                        severity=result.severity,
                        message=result.message,
                    )
                )

        return True, None

    # -- Bounce-back logic ---------------------------------------------------

    async def _handle_bounce(
        self,
        plan: WorkflowPlan,
        spec: StageSpec,
        gate_result: GateResult,
        completed: dict[str, Envelope],
        total_cost: float,
        session_id: str,
        stage_map: dict[str, StageSpec],
        initial_envelope: Envelope | None = None,
    ) -> Envelope | None:
        """Execute bounce-back: run target stage, then re-run original.

        Returns the re-executed envelope if the second gate check passes.
        Returns None if the bounce fails or second gate check fails (Sage D7
        -- single bounce, no recursion).
        """
        target_name = spec.on_gate_failure
        if not target_name:
            return None

        target_spec = stage_map.get(target_name)
        if not target_spec:
            return None

        # Execute bounce target.
        bounce_env = await self._execute_stage(
            target_spec,
            completed,
            total_cost,
            plan,
            session_id,
            initial_envelope,
        )
        completed[target_name] = bounce_env
        total_cost += bounce_env.cost_usd

        if bounce_env.status == TaskStatus.FAILED:
            return None

        # Re-execute the original stage.
        retry_env = await self._execute_stage(
            spec,
            completed,
            total_cost,
            plan,
            session_id,
            initial_envelope,
        )

        if retry_env.status == TaskStatus.FAILED:
            return None

        # Re-evaluate gates on the retried result (ONCE -- Sage D7).
        passed, _second_failure = await self._evaluate_gates(
            spec, retry_env, completed, total_cost, session_id
        )
        if not passed:
            # Second gate failure -- halt (no infinite loops).
            return None

        return retry_env

    # -- Gate result handling (shared by parallel + sequential) ---------------

    async def _handle_gate_result(
        self,
        spec: StageSpec,
        env: Envelope,
        stage_name: str,
        stages_done: dict[str, Envelope],
        total_cost: float,
        start: float,
        session_id: str,
        plan: WorkflowPlan,
        stage_map: dict[str, StageSpec],
        initial_envelope: Envelope | None = None,
    ) -> tuple[PipelineResult | None, float]:
        """Evaluate gates for a completed stage, attempt bounce on failure.

        Returns ``(None, cost_delta)`` if gates pass -- caller must add
        ``cost_delta`` to its running total (non-zero when a bounce
        succeeded). Returns ``(PipelineResult, 0)`` if the pipeline should
        halt.
        """
        if not spec.gates:
            return None, 0.0

        passed, gate_failure = await self._evaluate_gates(
            spec, env, stages_done, total_cost, session_id
        )
        if passed or gate_failure is None:
            return None, 0.0

        # Try bounce-back if configured.
        if spec.on_gate_failure:
            bounced = await self._handle_bounce(
                plan,
                spec,
                gate_failure,
                stages_done,
                total_cost,
                session_id,
                stage_map,
                initial_envelope,
            )
            if bounced is not None:
                stages_done[spec.name] = bounced
                return None, bounced.cost_usd

        # Gate failure -- halt pipeline.
        duration = time.monotonic() - start
        await self._emit(
            PipelineFailed(
                session_id=session_id,
                sequence=0,
                failed_stage=stage_name,
                error_message=gate_failure.message,
            )
        )
        return (
            PipelineResult(
                success=False,
                session_id=session_id,
                stages=stages_done,
                total_cost_usd=total_cost,
                duration_seconds=duration,
                error=gate_failure.message,
                failed_stage=stage_name,
                gate_failure=gate_failure,
            ),
            0.0,
        )

    # -- Helpers -------------------------------------------------------------

    async def _emit(self, event: BonfireEvent) -> None:
        """Emit an event through the bus."""
        await self._bus.emit(event)

    @staticmethod
    def _build_stage_map(plan: WorkflowPlan) -> dict[str, StageSpec]:
        """Build a name->StageSpec lookup from a plan."""
        return {s.name: s for s in plan.stages}

    @staticmethod
    def _build_dag(plan: WorkflowPlan, skip: set[str]) -> TopologicalSorter[str]:
        """Build a TopologicalSorter from plan stages, skipping completed ones."""
        dag: TopologicalSorter[str] = TopologicalSorter()
        for stage in plan.stages:
            if stage.name in skip:
                continue
            # Filter deps to only non-skipped stages
            deps = [d for d in stage.depends_on if d not in skip]
            dag.add(stage.name, *deps)
        return dag

    @staticmethod
    def _group_stages(ready: list[str], stage_map: dict[str, StageSpec]) -> list[list[str]]:
        """Group ready stages by parallel_group.

        Stages with the same parallel_group run concurrently.
        Stages without a group each run as their own singleton group.
        """
        groups: dict[str | None, list[str]] = {}
        for name in ready:
            spec = stage_map[name]
            key = spec.parallel_group
            if key is None:
                # Each ungrouped stage is its own group
                groups[name] = [name]
            else:
                groups.setdefault(key, []).append(name)

        return list(groups.values())
