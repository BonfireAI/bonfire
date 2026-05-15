# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Handoff command — generate session handoff."""

from __future__ import annotations

import typer


def handoff() -> None:
    """Generate a session handoff document."""
    typer.echo(
        "No session to hand off. "
        "(bonfire handoff is a v0.1 stub; full handoff generation is a follow-up.)"
    )
    raise typer.Exit(0)
