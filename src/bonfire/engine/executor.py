"""StageExecutor -- stage execution with strategy-based dispatch.

Separates stage execution from the pipeline loop into a reusable, testable
class. Supports single and parallel execution with iteration, handler
dispatch, context building, and event emission.

``execute_with_retry`` is imported at module scope so canonical tests can
patch ``bonfire.engine.executor.execute_with_retry``.

Sage decisions enforced here:
    D3: No ``compiler`` kwarg -- passing it raises ``TypeError``.
    D4: ``vault_advisor`` is optional; defaults to ``None``.
    D6: ``budget_remaining_usd`` clamped at zero (``max(0, ...)``).
    D11: ``PipelineConfig`` has no ``dispatch_timeout_seconds``; pass
         ``timeout_seconds=None`` to ``execute_with_retry``.
    D13: ``max_iterations`` = exactly N attempts (``range(N)``).

C19: ``execute_single`` never raises -- exceptions become failed Envelopes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from bonfire.agent.tiers import (
    resolve_model_for_role,  # noqa: F401 -- preserved for monkeypatch sites
)
from bonfire.dispatch.runner import execute_with_retry
from bonfire.engine.context import ContextBuilder
from bonfire.engine.factory import load_settings_or_default
from bonfire.engine.model_resolver import resolve_dispatch_model
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import StageCompleted, StageFailed, StageStarted
from bonfire.protocols import DispatchOptions

if TYPE_CHECKING:
    from bonfire.dispatch.tool_policy import ToolPolicy
    from bonfire.engine.advisor import VaultAdvisor
    from bonfire.events.bus import EventBus
    from bonfire.models.config import BonfireSettings, PipelineConfig
    from bonfire.models.plan import StageSpec, WorkflowPlan
    from bonfire.protocols import StageHandler


@runtime_checkable
class _ContextBuilderLike(Protocol):
    """Structural type for anything with an async ``build(**kwargs) -> str``."""

    async def build(self, **kwargs: Any) -> str: ...


class StageExecutor:
    """Execute pipeline stages with iteration, retry, and event emission.

    Decoupled from ``PipelineEngine`` so it can be tested, reused, and
    composed independently. Never raises -- all exceptions become failed
    Envelopes (C19).
    """

    __slots__ = (
        "_backend",
        "_bus",
        "_config",
        "_context_builder",
        "_handlers",
        "_project_root",
        "_settings",
        "_tool_policy",
        "_vault_advisor",
    )

    def __init__(
        self,
        *,
        backend: Any,
        bus: EventBus,
        config: PipelineConfig,
        handlers: dict[str, StageHandler] | None = None,
        context_builder: _ContextBuilderLike | None = None,
        vault_advisor: VaultAdvisor | None = None,
        project_root: Any | None = None,
        tool_policy: ToolPolicy | None = None,
        settings: BonfireSettings | None = None,
    ) -> None:
        self._backend = backend
        self._bus = bus
        self._config = config
        self._handlers = handlers or {}
        self._context_builder: _ContextBuilderLike = context_builder or ContextBuilder()
        self._vault_advisor = vault_advisor
        self._project_root = project_root
        self._tool_policy = tool_policy
        # Per cluster-351 Sage memo §G.2 -- the settings=None branch routes
        # through the engine factory so load failures emit a warning rather
        # than propagate a raw pydantic ValidationError from a constructor.
        self._settings = settings if settings is not None else load_settings_or_default()

    # -- Public API -----------------------------------------------------------

    async def execute_single(
        self,
        *,
        stage: StageSpec,
        prior_results: dict[str, Any],
        total_cost: float,
        plan: WorkflowPlan,
        session_id: str,
    ) -> Envelope:
        """Execute a single stage with iteration support. Never raises (C19)."""
        try:
            return await self._execute_single_inner(
                stage=stage,
                prior_results=prior_results,
                total_cost=total_cost,
                plan=plan,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail_envelope(
                stage=stage,
                message=f"{type(exc).__name__}: {exc}",
            )

    async def execute_parallel(
        self,
        *,
        stages: list[StageSpec],
        prior_results: dict[str, Any],
        total_cost: float,
        plan: WorkflowPlan,
        session_id: str,
    ) -> dict[str, Envelope]:
        """Run stages concurrently via TaskGroup, returning name -> Envelope."""
        results: dict[str, Envelope] = {}

        async with asyncio.TaskGroup() as tg:
            tasks: dict[str, asyncio.Task[Envelope]] = {}
            for stage in stages:
                task = tg.create_task(
                    self.execute_single(
                        stage=stage,
                        prior_results=prior_results,
                        total_cost=total_cost,
                        plan=plan,
                        session_id=session_id,
                    )
                )
                tasks[stage.name] = task

        for name, task in tasks.items():
            results[name] = task.result()

        return results

    # -- Internal execution ---------------------------------------------------

    async def _execute_single_inner(
        self,
        *,
        stage: StageSpec,
        prior_results: dict[str, Any],
        total_cost: float,
        plan: WorkflowPlan,
        session_id: str,
    ) -> Envelope:
        """Core loop: emit start, iterate, emit completion or failure."""
        await self._emit(
            StageStarted(
                session_id=session_id,
                sequence=0,
                stage_name=stage.name,
                agent_name=stage.agent_name,
            )
        )

        last_envelope: Envelope | None = None

        # Query vault advisor before dispatch (advisory, never blocking).
        known_issues = ""
        if self._vault_advisor is not None:
            known_issues = await self._vault_advisor.check(stage)

        for _iteration in range(stage.max_iterations):
            # Build context
            context = await self._context_builder.build(
                stage=stage,
                prior_results=prior_results,
                budget_remaining_usd=max(0, plan.budget_usd - total_cost),
                task=plan.task_description,
                known_issues=known_issues,
            )

            task_prompt = context

            envelope = Envelope(
                envelope_id=session_id,
                task=task_prompt,
                context=context,
                agent_name=stage.agent_name,
                model=stage.model_override or "",
                metadata={"role": stage.role} if stage.role else {},
            )

            # Dispatch: handler or backend
            last_envelope = await self._dispatch(stage, envelope, prior_results)

            if last_envelope.status != TaskStatus.FAILED:
                await self._emit(
                    StageCompleted(
                        session_id=session_id,
                        sequence=0,
                        stage_name=stage.name,
                        agent_name=stage.agent_name,
                        duration_seconds=0.0,
                        cost_usd=last_envelope.cost_usd,
                    )
                )
                return last_envelope

        # All iterations exhausted
        if last_envelope is None:
            # Defensive: max_iterations == 0 (shouldn't happen, but never raise)
            return self._fail_envelope(stage=stage, message="no iterations executed")
        await self._emit(
            StageFailed(
                session_id=session_id,
                sequence=0,
                stage_name=stage.name,
                agent_name=stage.agent_name,
                error_message=(
                    last_envelope.error.message if last_envelope.error else "exhausted iterations"
                ),
            )
        )
        return last_envelope

    async def _dispatch(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, Any],
    ) -> Envelope:
        """Route to handler or backend. Raises on unknown handler (caught by caller)."""
        if stage.handler_name is not None:
            return await self._dispatch_handler(stage, envelope, prior_results)
        return await self._dispatch_backend(stage, envelope)

    async def _dispatch_handler(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, Any],
    ) -> Envelope:
        """Execute via named handler. Fails gracefully on unknown handler."""
        handler = self._handlers.get(stage.handler_name)  # type: ignore[arg-type]
        if handler is None:
            return envelope.with_error(
                ErrorDetail(
                    error_type="config",
                    message=f"Unknown handler: {stage.handler_name}",
                )
            )
        # Convert prior_results to dict[str, str] for handler interface.
        prior_str = {
            k: v.result if isinstance(v, Envelope) else str(v) for k, v in prior_results.items()
        }
        return await handler.handle(stage, envelope, prior_str)

    async def _dispatch_backend(self, stage: StageSpec, envelope: Envelope) -> Envelope:
        """Execute via backend through execute_with_retry."""
        if self._tool_policy is None or not stage.role:
            role_tools: list[str] = []
        else:
            role_tools = self._tool_policy.tools_for(stage.role)
        # Per cluster-351 Sage memo §F.2 item 1 -- the inline 3-tier ``or``
        # chain is replaced with the engine-side seam ``resolve_dispatch_model``.
        # Precedence: ``envelope.model`` (built at executor.py:196 from
        # ``stage.model_override or ""``) -> ``resolve_model_for_role(...)`` ->
        # ``self._config.model``. The same helper handles the pipeline +
        # wizard call sites so the three engines share a single contract.
        options = DispatchOptions(
            model=resolve_dispatch_model(
                explicit_override=envelope.model,
                role=stage.role,
                settings=self._settings,
                config=self._config,
            ),
            max_turns=self._config.max_turns,
            max_budget_usd=self._config.max_budget_usd,
            cwd=str(self._project_root) if self._project_root else "",
            tools=role_tools,
            role=stage.role,
        )
        result = await execute_with_retry(
            self._backend,
            envelope,
            options,
            max_retries=0,
            timeout_seconds=None,
            event_bus=self._bus,
        )
        return result.envelope

    # -- Helpers --------------------------------------------------------------

    async def _emit(self, event: Any) -> None:
        """Emit event on the bus."""
        await self._bus.emit(event)

    @staticmethod
    def _fail_envelope(*, stage: StageSpec, message: str) -> Envelope:
        """Create a failed Envelope from an exception -- C19 safety net."""
        return Envelope(
            task=stage.name,
            agent_name=stage.agent_name,
        ).with_error(ErrorDetail(error_type="executor", message=message))
