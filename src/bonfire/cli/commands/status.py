# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Status command — report the most recent persisted session."""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from bonfire.session.store import SessionStore
from bonfire.workflow.registry import get_default_registry


def _stage_progress(plan_name: str, completed: int) -> str:
    """``"2 / 5 stages"`` when the plan is known, else ``"2 stages"``."""
    registry = get_default_registry()
    if plan_name in registry:
        total = len(registry.get(plan_name)().stages)
        return f"{completed} / {total} stages"
    return f"{completed} stages"


def status() -> None:
    """Show current Bonfire session status."""
    store = SessionStore()
    latest = store.latest()
    if latest is None:
        typer.echo("No active session.")
        raise typer.Exit(0)

    when = datetime.fromtimestamp(latest.timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    typer.echo(f"Session {latest.session_id}")
    typer.echo(f"  Workflow: {latest.plan_name}")
    typer.echo(f"  Stage:    {_stage_progress(latest.plan_name, len(latest.completed))}")
    typer.echo(f"  Cost:     ${latest.total_cost_usd:.2f}")
    typer.echo(f"  Saved:    {when}")
    raise typer.Exit(0)
