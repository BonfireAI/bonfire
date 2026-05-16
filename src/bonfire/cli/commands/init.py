# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Init command — scaffold a new Bonfire project."""

from __future__ import annotations

from pathlib import Path

import typer

from bonfire._safe_write import safe_write_text


def init(
    project_dir: str = typer.Argument(".", help="Directory to initialize."),
) -> None:
    """Initialize a new Bonfire project."""
    target = Path(project_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    toml_path = target / "bonfire.toml"
    # ``Path.exists()`` follows symlinks, so a dangling symlink at
    # ``bonfire.toml -> ~/.ssh/authorized_keys`` returns False and the
    # write_text below would open the attacker-controlled symlink target
    # in write+truncate mode — an arbitrary-write primitive. The
    # ``safe_write_text`` helper refuses any symlink at the target path
    # (and uses O_NOFOLLOW defense-in-depth against the TOCTOU race).
    # When the path is a non-symlink regular file we leave it untouched
    # (idempotent ``bonfire init`` behavior); the existence check uses
    # the symlink-aware predicate so the symlink case is never silently
    # treated as "already exists, skip write".
    if toml_path.is_symlink():
        typer.echo(
            f"bonfire.toml at {toml_path} is a symlink. Refusing to follow "
            "or overwrite a symlinked config. Remove the symlink and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)
    if not toml_path.exists():
        safe_write_text(toml_path, "[bonfire]\n")

    (target / ".bonfire").mkdir(exist_ok=True)
    (target / "agents").mkdir(exist_ok=True)

    typer.echo(f"Initialized Bonfire project in {target}")
    raise typer.Exit(0)
