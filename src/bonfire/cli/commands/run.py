# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Run command — drive a prompt through a workflow plan and the engine.

The minimal build driver: a prompt becomes a workflow plan, the plan runs
through the live :class:`~bonfire.engine.pipeline.PipelineEngine`, and the
result is rendered cleanly (success + cost, or the typed failure). The
process exits non-zero on failure so the verb composes in scripts and CI.

Dependency-injection seam
-------------------------
``_run`` accepts a ``build_engine`` factory that returns a wired
``PipelineEngine``. The public Typer command passes the real default
(:func:`_default_engine`, which wires the Claude Agent SDK backend). Unit
tests pass a factory returning an engine wired to a fake backend, so the
driver's plan-selection / rendering / exit-code logic is exercised with
zero network.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

import typer

from bonfire.workflow.registry import get_default_registry

if TYPE_CHECKING:
    from bonfire.engine.pipeline import PipelineEngine, PipelineResult
    from bonfire.models.plan import WorkflowPlan

#: Default workflow selected when the caller does not pass ``--workflow``.
_DEFAULT_WORKFLOW = "standard_build"


class _EngineFactory(Protocol):
    """Callable that builds a wired :class:`PipelineEngine` from a plan.

    The plan is passed so a factory may size the backend / settings to the
    plan's budget; the default factory ignores it. Keeping the plan in the
    signature lets the seam stay stable as wiring grows.
    """

    def __call__(self, plan: WorkflowPlan) -> PipelineEngine: ...


def _default_engine(plan: WorkflowPlan) -> PipelineEngine:
    """Wire a :class:`PipelineEngine` around the live SDK backend.

    This is the real-network path, and it is what a user gets. The wiring
    itself lives in :mod:`bonfire.engine.composition` so that it can be
    called by tests directly rather than only through an injected factory:
    a composition root nothing exercises is a composition root nothing
    catches, and this one previously shipped without ``handlers=``,
    ``gate_registry=``, ``tool_policy=`` or ``project_root=``.

    Raises:
        WiringError: If the plan names a handler or gate the built-in
            registries cannot supply. Raised before anything is dispatched.
    """
    from bonfire.engine.composition import build_default_engine

    return build_default_engine(plan)


def _select_plan(prompt: str, *, budget: float | None, workflow: str) -> WorkflowPlan:
    """Build the workflow plan for *prompt*, stamping task + budget.

    Raises:
        KeyError: If *workflow* is not a registered workflow name. The
            registry's error message lists the available names.
    """
    registry = get_default_registry()
    plan = registry.get(workflow)()
    updates: dict[str, object] = {"task_description": prompt}
    if budget is not None:
        updates["budget_usd"] = budget
    return plan.model_copy(update=updates)


def _render(result: PipelineResult) -> None:
    """Print a clean summary of *result* and exit non-zero on failure."""
    if result.success:
        typer.echo(f"Run succeeded (session {result.session_id}).")
        typer.echo(f"  Cost: ${result.total_cost_usd:.2f}")
        raise typer.Exit(0)

    typer.echo(f"Run failed (session {result.session_id}).", err=True)
    if result.failed_stage:
        typer.echo(f"  Stage: {result.failed_stage}", err=True)
    if result.gate_failure is not None:
        gate = result.gate_failure
        typer.echo(f"  Gate:  {gate.gate_name} — {gate.message}", err=True)
    if result.error:
        typer.echo(f"  Error: {result.error}", err=True)
    typer.echo(f"  Cost:  ${result.total_cost_usd:.2f}", err=True)
    raise typer.Exit(1)


def _run(
    prompt: str,
    *,
    budget: float | None = None,
    workflow: str = _DEFAULT_WORKFLOW,
    build_engine: _EngineFactory = _default_engine,
) -> None:
    """Core driver — selects a plan, runs the engine, renders the result.

    The ``build_engine`` seam is the unit-test injection point: pass a
    factory returning an engine wired to a fake backend to run with no
    network.

    Raises:
        typer.Exit: Always — code 0 on success, 1 on failure, 2 on an
            unknown ``--workflow`` name or a plan the engine cannot be
            wired for.
    """
    from bonfire.engine.composition import WiringError

    try:
        plan = _select_plan(prompt, budget=budget, workflow=workflow)
    except KeyError as exc:
        # ``KeyError`` str() wraps its message in quotes; strip them.
        typer.echo(str(exc).strip("\"'"), err=True)
        raise typer.Exit(2) from None

    # A plan naming an unregistered handler or gate is a configuration
    # problem, not a run failure: nothing was dispatched and nothing was
    # billed, so it exits 2 alongside the unknown-workflow case rather than
    # 1. Without this the two omissions fail asymmetrically — a missing
    # handler as a mid-run stage error, a missing gate not at all.
    try:
        engine = build_engine(plan)
    except WiringError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None

    result = asyncio.run(engine.run(plan))
    _render(result)


def run(
    prompt: str = typer.Argument(..., help="The task for the build pipeline to perform."),
    budget: float | None = typer.Option(
        None,
        "--budget",
        "-b",
        help="Maximum spend in USD for this run. Defaults to the plan's budget.",
    ),
    workflow: str = typer.Option(
        _DEFAULT_WORKFLOW,
        "--workflow",
        "-w",
        help="Workflow plan to run. Use a name from the built-in registry.",
    ),
) -> None:
    """Drive a prompt through a workflow plan and the pipeline engine."""
    _run(prompt, budget=budget, workflow=workflow)
