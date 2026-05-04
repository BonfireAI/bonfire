# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Status command — current session status."""

from __future__ import annotations

import typer


def status() -> None:
    """Show current Bonfire session status."""
    typer.echo("No active session.")
    raise typer.Exit(0)
