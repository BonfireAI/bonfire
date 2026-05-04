# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Bonfire CLI — Typer application entry point."""

from __future__ import annotations

import typer

from bonfire import __version__
from bonfire.cli.commands.cost import cost_app
from bonfire.cli.commands.handoff import handoff
from bonfire.cli.commands.init import init
from bonfire.cli.commands.persona import persona_app
from bonfire.cli.commands.resume import resume
from bonfire.cli.commands.scan import scan
from bonfire.cli.commands.status import status

# Bonfire ships with Falcor as the companion persona; users can swap
# via `bonfire persona set <name>`. The `default` and `minimal` builtins
# remain available as user-selectable alternates.
_DEFAULT_PERSONA = "falcor"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"bonfire {__version__}")
        raise typer.Exit(0)


app = typer.Typer(
    name="bonfire",
    help="Bonfire — AI agent orchestration framework.",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    persona: str = typer.Option(
        _DEFAULT_PERSONA,
        "--persona",
        help="Persona for CLI output formatting.",
    ),
) -> None:
    """Bonfire — AI agent orchestration framework."""
    ctx.ensure_object(dict)
    ctx.obj["persona"] = persona


app.command("init")(init)
app.command("scan")(scan)
app.command("status")(status)
app.command("resume")(resume)
app.command("handoff")(handoff)
app.add_typer(persona_app, name="persona")
app.add_typer(cost_app, name="cost")
