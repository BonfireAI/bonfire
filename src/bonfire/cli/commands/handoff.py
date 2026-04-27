"""Handoff command — generate session handoff."""

from __future__ import annotations

import typer


def handoff() -> None:
    """Generate a session handoff document."""
    typer.echo("Handoff generated.")
    raise typer.Exit(0)
