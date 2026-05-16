# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

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

    Known limitation: budget enforcement is group-boundary, not mid-group.
    A long-running stage inside a parallel group cannot be cancelled when
    the budget is exceeded mid-execution; the watchdog only fires between
    groups. Future enhancement: cancellation-aware budget watchdog.
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
        """Execute a workflow plan. NEVER raises -- returns PipelineResult.

        Outer-exception branch (everything not caught by an inner per-stage
        try/except) emits :class:`PipelineFailed` BEFORE returning the
        failed result. Wave 11 Lane D closes the bus-vs-``PipelineResult``
        parity gap on this halt branch: without the emit, every observer
        subscribed to ``PipelineFailed`` (``CostLedgerConsumer``,
        ``DisplayConsumer``, ``XPConsumer``) silently missed the halt;
        the persisted ledger had no row, the CLI showed nothing, and the
        XP calculator never penalized the run.
        """
        sid = session_id or uuid4().hex[:12]
        start = time.monotonic()
        # Pre-seed the completed dict so the outer-exception branch can
        # report ``stages_completed = len(seen_so_far)``. The dict is
        # passed by reference into ``_run_inner`` which mutates it as
        # stages finish, so by the time the outer ``except`` catches an
        # exception the count reflects every stage that completed before
        # the halt fired.
        stages_seen: dict[str, Envelope] = dict(completed or {})
        try:
            return await self._run_inner(plan, sid, stages_seen, start, initial_envelope)
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            error_msg = str(exc)
            # Best-effort total_cost reconstruction from whatever stages
            # the inner loop managed to populate before the exception
            # fired. ``sum(env.cost_usd for env in stages_seen.values())``
            # matches the engine accumulator on the success path.
            total_cost = sum(env.cost_usd for env in stages_seen.values())
            await self._emit(
                PipelineFailed(
                    session_id=sid,
                    sequence=0,
                    failed_stage="",
                    error_message=error_msg,
                    total_cost_usd=total_cost,
                    # Sentinel: outer-exception halts cannot name a
                    # specific bounce-target handler. ``__outer__`` is
                    # distinct from ``None`` (which the schema uses for
                    # non-bounce halt branches) and from a real handler
                    # name (which the bounce-target branch sets).
                    # Operators reading the bus can grep for ``__outer__``
                    # to distinguish outer-exception halts from every
                    # other halt shape.
                    failed_handler="__outer__",
                    duration_seconds=duration,
                    stages_completed=len(stages_seen),
                )
            )
            return PipelineResult(
                success=False,
                session_id=sid,
                stages=stages_seen,
                total_cost_usd=total_cost,
                error=error_msg,
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
        """The real pipeline execution logic.

        The caller (``run``) passes a mutable ``completed`` dict that
        this method MUTATES in place as stages finish. On the
        outer-exception path (an unexpected raise here), ``run``'s
        ``except`` branch reads the same dict to populate
        ``PipelineFailed.stages_completed`` and reconstruct
        ``total_cost_usd``. Re-binding to a fresh ``dict(completed)``
        would orphan the outer's view; mutate-in-place is load-bearing.
        """
        stages_done: dict[str, Envelope] = completed
        # Resume path: pre-completed stages already incurred cost in their
        # original run. Seed total_cost from them so budget accounting and
        # result.total_cost_usd reflect the full pipeline spend, not just the
        # post-resume tail.
        total_cost = sum(env.cost_usd for env in stages_done.values())
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
                            total_cost_usd=total_cost,
                            duration_seconds=duration,
                            stages_completed=len(stages_done),
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

        # Accumulate ALL sibling costs and record ALL envelopes BEFORE
        # short-circuiting on any failure. Otherwise, when one parallel
        # sibling FAILS, later siblings (in dict-iteration order) silently
        # lose both their envelope (not added to stages_done) AND their
        # cost (not added to total_cost). The asyncio.TaskGroup above
        # already awaited every sibling to completion -- there is no work
        # to cancel here, only accounting to record.
        first_failed: tuple[str, Envelope] | None = None
        for sname, env in results.items():
            stages_done[sname] = env
            total_cost += env.cost_usd
            if first_failed is None and env.status == TaskStatus.FAILED:
                first_failed = (sname, env)

        if first_failed is not None:
            sname, env = first_failed
            duration = time.monotonic() - start
            error_msg = env.error.message if env.error else "stage failed"
            await self._emit(
                PipelineFailed(
                    session_id=session_id,
                    sequence=0,
                    failed_stage=sname,
                    error_message=error_msg,
                    total_cost_usd=total_cost,
                    duration_seconds=duration,
                    stages_completed=len(stages_done),
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
                    total_cost_usd=total_cost,
                    duration_seconds=duration,
                    stages_completed=len(stages_done),
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
        # Iterations 0..N-1 of a stage's max_iterations may each fail with
        # a real cost charged by the backend. Without this accumulator,
        # only the FINAL envelope's cost_usd survives -- intermediate
        # failed-iteration spend leaks out of total_cost_usd entirely. We
        # track the sum here and stamp the cumulative value onto the
        # returned envelope so the caller's ``total_cost += env.cost_usd``
        # sees every dollar this stage actually cost.
        cumulative_iteration_cost: float = 0.0

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
            cumulative_iteration_cost += result_env.cost_usd

            if result_env.status != TaskStatus.FAILED:
                # Stamp the cumulative cost (sum of every iteration this
                # stage attempted) onto the returned envelope so the
                # caller's ``total_cost += env.cost_usd`` captures every
                # dollar, not just the successful iteration's slice.
                final_env = result_env.model_copy(update={"cost_usd": cumulative_iteration_cost})
                await self._emit(
                    StageCompleted(
                        session_id=session_id,
                        sequence=0,
                        stage_name=spec.name,
                        agent_name=spec.agent_name,
                        duration_seconds=0.0,
                        cost_usd=final_env.cost_usd,
                    )
                )
                return final_env

        # All iterations exhausted -- return final failed envelope with
        # the cumulative iteration cost stamped on so the budget watchdog
        # sees every dollar burned by the exhausted retries.
        if last_envelope is None:
            last_envelope = Envelope(
                task=spec.name or "<unnamed>", agent_name=spec.agent_name
            ).with_error(ErrorDetail(error_type="executor", message="no iterations executed"))
        final_failed = last_envelope.model_copy(update={"cost_usd": cumulative_iteration_cost})
        await self._emit(
            StageFailed(
                session_id=session_id,
                sequence=0,
                stage_name=spec.name,
                agent_name=spec.agent_name,
                error_message=(
                    final_failed.error.message if final_failed.error else "exhausted iterations"
                ),
            )
        )
        return final_failed

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
    ) -> tuple[Envelope | None, float, str | None]:
        """Execute bounce-back: run target stage, then re-run original.

        Returns ``(retry_envelope, cost_delta, failed_handler)``.

        On success, ``retry_envelope`` is the retried original's
        envelope, ``cost_delta`` is the FULL cost added by the bounce
        (bounce-target cost + retry cost), and ``failed_handler`` is
        ``None`` (no halt). The caller must credit ``cost_delta`` to its
        running total so budget accounting includes the bounce target.

        On every failure branch (no target configured, target lookup
        miss, bounce-target failed, retry failed, second gate failure)
        returns ``(None, cost_delta, failed_handler)`` where
        ``cost_delta`` reflects every dollar the bounce path actually
        burned before halting. ``failed_handler`` names the bounce
        TARGET when the target's own execution failed (so the emitted
        ``PipelineFailed`` event can identify which handler died);
        ``None`` on every other branch (no bounce attempted, retry
        failed on the original, second-gate failure — in those cases
        ``failed_stage`` already names the original stage that broke
        the contract).

        Earlier versions returned ``(None, cost_delta)`` and the
        bounce-target's identity was lost from the event stream;
        threading ``failed_handler`` upward closes the H4 naming gap.
        """
        target_name = spec.on_gate_failure
        if not target_name:
            return None, 0.0, None

        target_spec = stage_map.get(target_name)
        if not target_spec:
            return None, 0.0, None

        # Execute bounce target.
        bounce_env = await self._execute_stage(
            target_spec,
            completed,
            total_cost,
            plan,
            session_id,
            initial_envelope,
        )
        bounce_cost = bounce_env.cost_usd
        # If the bounce target is a stage already in ``completed``
        # (typical: bounce target is the DAG-init stage whose work the
        # original stage's gate flagged), the replacement quietly drops
        # the prior envelope's cost from
        # ``sum(env.cost_usd for env in completed.values())``. The
        # resume-from-checkpoint path reads that sum as the seed total
        # (engine/pipeline.py:165). Stamp the bounce-target envelope
        # with the combined cost so the sum-of-stages invariant matches
        # the engine accumulator. H6.
        prior_target_env = completed.get(target_name)
        if prior_target_env is not None:
            bounce_env = bounce_env.model_copy(
                update={"cost_usd": prior_target_env.cost_usd + bounce_cost}
            )
        completed[target_name] = bounce_env
        total_cost += bounce_cost

        if bounce_env.status == TaskStatus.FAILED:
            # Bounce target itself failed -- the dollars it spent still
            # left the wallet; surface them to the caller so budget
            # accounting reflects the partial spend. Surface the
            # bounce-target name so the emitted ``PipelineFailed`` can
            # identify which handler died (H4).
            return None, bounce_cost, target_name

        # Re-execute the original stage.
        retry_env = await self._execute_stage(
            spec,
            completed,
            total_cost,
            plan,
            session_id,
            initial_envelope,
        )
        retry_cost = retry_env.cost_usd

        if retry_env.status == TaskStatus.FAILED:
            # The bounce target SUCCEEDED; the original's retry failed.
            # ``failed_stage`` already names the original; no
            # ``failed_handler`` distinction to make on this branch.
            return None, bounce_cost + retry_cost, None

        # Re-evaluate gates on the retried result (ONCE -- Sage D7).
        passed, _second_failure = await self._evaluate_gates(
            spec, retry_env, completed, total_cost, session_id
        )
        if not passed:
            # Second gate failure -- halt (no infinite loops). Still
            # credit the bounce-target + retry cost to the caller. The
            # bounce TARGET succeeded; the original's retried result
            # failed the gate — ``failed_stage`` (the original) already
            # carries operator context.
            return None, bounce_cost + retry_cost, None

        return retry_env, bounce_cost + retry_cost, None

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

        # Try bounce-back if configured. ``_handle_bounce`` now ALWAYS
        # returns a (retry_envelope_or_none, cost_delta, failed_handler)
        # tuple so the bounce-target's spend lands in the running total
        # regardless of whether the bounce succeeded, and the bounce
        # target's identity reaches the emitted ``PipelineFailed`` on
        # bounce-target halt branches.
        bounce_cost_delta = 0.0
        failed_handler: str | None = None
        if spec.on_gate_failure:
            retry_env, bounce_cost_delta, failed_handler = await self._handle_bounce(
                plan,
                spec,
                gate_failure,
                stages_done,
                total_cost,
                session_id,
                stage_map,
                initial_envelope,
            )
            if retry_env is not None:
                # Stamp ``retry_env`` with the combined cost of the
                # original (already in ``stages_done`` at this point —
                # the caller wrote it before invoking us) PLUS the
                # retry. Replacing ``stages_done[spec.name] = retry_env``
                # without this stamp drops the original's cost from
                # ``sum(env.cost_usd for env in stages_done.values())``,
                # which the resume-from-checkpoint path reads as the
                # seed total_cost (engine/pipeline.py:165). H6.
                original_env = stages_done.get(spec.name)
                if original_env is not None:
                    retry_env = retry_env.model_copy(
                        update={"cost_usd": original_env.cost_usd + retry_env.cost_usd}
                    )
                stages_done[spec.name] = retry_env
                return None, bounce_cost_delta

        # Gate failure -- halt pipeline. Credit any cost the bounce
        # path burned before halting so PipelineResult.total_cost_usd
        # (and the PipelineFailed event's total_cost_usd) reflect every
        # dollar that left the wallet.
        total_cost += bounce_cost_delta
        duration = time.monotonic() - start
        await self._emit(
            PipelineFailed(
                session_id=session_id,
                sequence=0,
                failed_stage=stage_name,
                error_message=gate_failure.message,
                total_cost_usd=total_cost,
                failed_handler=failed_handler,
                duration_seconds=duration,
                stages_completed=len(stages_done),
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
