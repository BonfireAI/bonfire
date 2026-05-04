# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Init command — scaffold a new Bonfire project."""

from __future__ import annotations

from pathlib import Path

import typer


def init(
    project_dir: str = typer.Argument(".", help="Directory to initialize."),
) -> None:
    """Initialize a new Bonfire project."""
    target = Path(project_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    toml_path = target / "bonfire.toml"
    if not toml_path.exists():
        toml_path.write_text("[bonfire]\n")

    (target / ".bonfire").mkdir(exist_ok=True)
    (target / "agents").mkdir(exist_ok=True)

    typer.echo(f"Initialized Bonfire project in {target}")
    raise typer.Exit(0)
