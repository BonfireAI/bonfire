# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Resume command — resume a previous session."""

from __future__ import annotations

import typer


def resume() -> None:
    """Resume a previous Bonfire session."""
    typer.echo("No session to resume.")
    raise typer.Exit(0)
