# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Init command — scaffold a new Bonfire project."""

from __future__ import annotations

from pathlib import Path

import typer

from bonfire._safe_write import safe_write_text

# ``.bonfire/`` carries operator-local state (e.g. the per-machine
# ``tools.local.toml`` written by ``bonfire scan``). The directory
# pattern ``/.bonfire/`` covers every current and future operator-local
# artefact under that directory in one entry, which is the simplest
# sufficient cover per W8.G and matches the Knight contract's accepted
# pattern set. Anchoring with a leading slash is intentional: it pins
# the pattern to the project root so a deeply-nested directory named
# ``.bonfire`` elsewhere in the tree is not accidentally excluded.
_GITIGNORE_LINE = ".bonfire/"


def _ensure_gitignore_entry(target: Path, line: str) -> None:
    """Append ``line`` to ``target/.gitignore`` iff not already present.

    Idempotent: re-running ``bonfire init`` MUST NOT duplicate the
    ``.bonfire/`` entry (the no-duplicate canary pins this). The
    presence check matches a stripped/non-comment line against the
    requested entry; existing comments and blank lines are preserved.
    Creates ``.gitignore`` if absent.

    Uses :func:`safe_write_text` (W7.M) when creating the file fresh;
    when appending we use Python's regular text I/O because we must
    preserve any existing user content (``safe_write_text`` is a
    create-or-overwrite primitive, not an append primitive). The
    append path checks ``is_symlink`` first so a planted symlink at
    ``.gitignore`` does not become an arbitrary-write primitive via
    the append.
    """
    gitignore_path = target / ".gitignore"

    if gitignore_path.is_symlink():
        # Defensive parallel to the bonfire.toml symlink branch above:
        # refuse to follow a symlinked .gitignore. The error is
        # advisory — the operator can remove the symlink and re-run.
        typer.echo(
            f".gitignore at {gitignore_path} is a symlink. Refusing to "
            "follow or overwrite a symlinked .gitignore. Remove the "
            "symlink and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)

    if not gitignore_path.exists():
        # Fresh file — create with the entry and a brief header so a
        # future contributor reading ``.gitignore`` understands why
        # ``.bonfire/`` is excluded.
        body = f"# Bonfire — operator-local state (do not commit).\n{line}\n"
        safe_write_text(gitignore_path, body)
        return

    existing = gitignore_path.read_text()
    existing_lines = [ln.strip() for ln in existing.splitlines()]
    if line in existing_lines:
        # Already covered — idempotent no-op.
        return

    # Append on a fresh line. Ensure exactly one trailing newline before
    # the new line so we don't accumulate blank lines on repeat runs.
    suffix = "" if existing.endswith("\n") else "\n"
    gitignore_path.write_text(existing + suffix + f"{line}\n")


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

    # W8.G — seed .gitignore so ``.bonfire/tools.local.toml`` (and any
    # future operator-local file under ``.bonfire/``) is never staged
    # for commit. Idempotent: re-running ``bonfire init`` does not
    # duplicate the entry.
    _ensure_gitignore_entry(target, _GITIGNORE_LINE)

    typer.echo(f"Initialized Bonfire project in {target}")
    raise typer.Exit(0)
