# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost CLI commands — bonfire cost [summary|session|agents|export]."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from bonfire.cost.analyzer import CostAnalyzer
from bonfire.models.events import _validate_session_id

cost_app = typer.Typer(name="cost", help="View build cost analytics.")


def _get_analyzer() -> CostAnalyzer:
    """Build analyzer from env override or default path."""
    env_path = os.environ.get("BONFIRE_COST_LEDGER_PATH")
    if env_path:
        return CostAnalyzer(ledger_path=Path(env_path))
    return CostAnalyzer()


@cost_app.callback(invoke_without_command=True)
def cost_summary(ctx: typer.Context) -> None:
    """Show cumulative cost and recent sessions."""
    if ctx.invoked_subcommand is not None:
        return

    analyzer = _get_analyzer()
    total = analyzer.cumulative_cost()
    sessions = analyzer.all_sessions()

    typer.echo(f"Built by Bonfire for ${total:.2f}")
    typer.echo("")

    if not sessions:
        typer.echo("No sessions recorded yet.")
        return

    recent = sessions[:5]
    typer.echo("Last sessions:")
    for s in recent:
        typer.echo(
            f"  {s.session_id}  ${s.total_cost_usd:.2f}  "
            f"{s.duration_seconds:.1f}s  {s.stages_completed} stages"
        )


@cost_app.command("session")
def cost_session(
    session_id: str = typer.Argument(..., help="Session ID to inspect"),
) -> None:
    """Show per-agent cost breakdown for a session."""
    # Fire the session_id format validator at the CLI boundary,
    # BEFORE building the analyzer / opening the ledger file. The
    # validator is the same one that pins ``BonfireEvent.session_id`` so
    # the accept/reject set stays consistent across the codebase
    # (alphanumerics + ``_`` + ``-``, 1-64 chars). Path-traversal /
    # newline-injection shapes never reach the analyzer or touch disk.
    # The empty string is rejected explicitly here because (unlike the
    # ``BonfireEvent`` model where empty is the outside-session
    # sentinel) ``cost session`` has no use for the empty form.
    if not session_id:
        typer.echo("Error: session_id must be non-empty.", err=True)
        raise typer.Exit(2)
    try:
        _validate_session_id(session_id)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc

    analyzer = _get_analyzer()
    session = analyzer.session_cost(session_id)

    if session is None:
        typer.echo(f"Session '{session_id}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(
        f"Session {session.session_id} -- ${session.total_cost_usd:.2f} "
        f"({session.duration_seconds:.1f}s)"
    )
    typer.echo("")
    for d in session.dispatches:
        typer.echo(f"  {d.agent_name:<25} ${d.cost_usd:.2f}  {d.duration_seconds:.1f}s")


@cost_app.command("agents")
def cost_agents() -> None:
    """Show cumulative per-agent costs."""
    analyzer = _get_analyzer()
    agents = analyzer.agent_costs()

    if not agents:
        typer.echo("No agent costs recorded yet.")
        return

    typer.echo("Agent costs (cumulative):")
    for a in agents:
        dispatch_word = "dispatch" if a.dispatch_count == 1 else "dispatches"
        typer.echo(
            f"  {a.agent_name:<25} ${a.total_cost_usd:.2f}  "
            f"{a.dispatch_count} {dispatch_word}  ${a.avg_cost_usd:.2f} avg"
        )


@cost_app.command("export")
def cost_export() -> None:
    """Export full ledger as JSON array to stdout."""
    analyzer = _get_analyzer()
    records = analyzer.all_records()
    typer.echo(json.dumps([r.model_dump() for r in records], indent=2))
