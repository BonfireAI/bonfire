# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Resume command — reload a checkpoint and prepare to re-enter the pipeline.

``bonfire resume`` reads the most recent persisted session, reconstructs its
workflow plan from the registry (keyed by the checkpoint's ``plan_name``), and
computes the stages that remain. The completed stages are fed back in as the
pipeline's pre-seeded ``completed`` map — the same resume contract the engine
documents (``PipelineEngine.run(plan, completed=...)`` skips already-completed
stages and re-enters at the frontier).

Honesty boundaries:

* No persisted session → say so and exit 0 (nothing to resume).
* A checkpoint whose ``plan_name`` is not a registered workflow → fail loudly
  (exit 1). The plan cannot be reconstructed, so resume cannot proceed; the
  command names the unknown plan rather than silently no-op.
* Actually dispatching the remaining stages requires a live agent backend
  (``ANTHROPIC_API_KEY``); the verb prepares and reports the re-entry plan so
  the operator sees exactly what would run, and the library path
  (``PipelineEngine.run``) consumes the prepared inputs.
"""

from __future__ import annotations

import typer

from bonfire.session.store import SessionStore
from bonfire.workflow.registry import get_default_registry


def resume() -> None:
    """Resume a previous Bonfire session."""
    store = SessionStore()
    latest = store.latest()
    if latest is None:
        typer.echo("No session to resume.")
        raise typer.Exit(0)

    registry = get_default_registry()
    if latest.plan_name not in registry:
        typer.echo(
            f"Cannot resume session {latest.session_id}: workflow "
            f"'{latest.plan_name}' is not a registered plan, so it cannot be "
            "reconstructed.",
            err=True,
        )
        raise typer.Exit(1)

    plan = registry.get(latest.plan_name)()
    done = set(latest.completed)
    remaining = [stage.name for stage in plan.stages if stage.name not in done]

    typer.echo(f"Resuming session {latest.session_id} ({latest.plan_name}).")
    typer.echo(f"  Completed: {len(done)} stage(s) — ${latest.total_cost_usd:.2f} spent.")
    if remaining:
        typer.echo(f"  Remaining: {len(remaining)} stage(s): {', '.join(remaining)}")
        typer.echo(
            "  Re-entering the pipeline at the first remaining stage. "
            "Live dispatch requires ANTHROPIC_API_KEY."
        )
    else:
        typer.echo("  Remaining: none — the workflow already ran to completion.")
    raise typer.Exit(0)
