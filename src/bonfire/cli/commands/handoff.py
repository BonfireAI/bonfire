# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Handoff command — render a handoff document from the latest session."""

from __future__ import annotations

import typer

from bonfire.session.handoff_doc import render_handoff
from bonfire.session.store import SessionStore


def handoff() -> None:
    """Generate a session handoff document."""
    store = SessionStore()
    latest = store.latest()
    if latest is None:
        typer.echo("No session to hand off.")
        raise typer.Exit(0)

    typer.echo(render_handoff(latest))
    raise typer.Exit(0)
