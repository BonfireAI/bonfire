# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Init command — scaffold a new Bonfire project."""

from __future__ import annotations

from pathlib import Path

import typer

from bonfire._safe_write import safe_append_text, safe_write_text

# ``.bonfire/`` carries a MIX of operator-local state (the per-machine
# ``tools.local.toml`` written by ``bonfire scan``) AND artefacts that
# ARE committable: ``.bonfire/sessions`` (handoff history),
# ``.bonfire/context.json`` (project config), ``.bonfire/vault``
# (knowledge backend seed), ``.bonfire/costs.jsonl`` (cost ledger, when
# operator opts in to commit). A broad ``.bonfire/`` ignore would
# silently exclude those committable sub-paths and break workflows that
# depend on them landing in git. The narrower entry names the single
# operator-local file the W8.G work introduced so other sub-paths under
# ``.bonfire/`` remain stageable by default. The operator can still add
# broader patterns to ``.gitignore`` by hand if they want; ``bonfire
# init`` does not assume that policy.
_GITIGNORE_LINE = ".bonfire/tools.local.toml"


def _ensure_gitignore_entry(target: Path, line: str) -> None:
    """Append ``line`` to ``target/.gitignore`` iff not already present.

    Idempotent: re-running ``bonfire init`` MUST NOT duplicate the
    operator-local entry (the no-duplicate canary pins this). The
    presence check matches a stripped/non-comment line against the
    requested entry; existing comments and blank lines are preserved.
    Creates ``.gitignore`` if absent.

    Uses :func:`safe_write_text` (W7.M) when creating the file fresh
    and :func:`safe_append_text` (W7.M append helper) when extending
    an existing ``.gitignore``. ``safe_append_text`` carries the
    ``O_NOFOLLOW`` defense-in-depth guard that closes the TOCTOU
    window a race-planted symlink could otherwise slip through
    between the ``is_symlink()`` pre-check and the append.
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
        # future contributor reading ``.gitignore`` understands why the
        # operator-local file is excluded.
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
    # Doc-acceptance: this read-modify-write is not protected against a
    # concurrent ``bonfire init`` racing in the same project root. Two
    # processes interleaving here could each see the same pre-image and
    # both append, producing a duplicate entry. ``bonfire init`` is a
    # one-shot operator command; the race window is small and the
    # failure mode is benign (a duplicate line). Not worth ``fcntl.flock``
    # complexity in v0.1.
    #
    # Route the append through ``safe_append_text`` (not raw
    # ``Path.write_text``) so the W7.M ``O_NOFOLLOW`` defense closes
    # the TOCTOU window between the ``is_symlink()`` pre-check above
    # and the on-disk write — a race-planted symlink at ``.gitignore``
    # is refused at ``open(2)`` time by the kernel rather than slipping
    # through to an attacker-controlled target. The append helper
    # creates the file on first call if absent, so even a benign race
    # where the file disappears between the existence check and the
    # append still produces correct on-disk state without leaking the
    # write through a symlink.
    suffix = "" if existing.endswith("\n") else "\n"
    safe_append_text(gitignore_path, suffix + f"{line}\n")


def init(
    project_dir: str = typer.Argument(".", help="Directory to initialize."),
) -> None:
    """Initialize a new Bonfire project."""
    target = Path(project_dir).resolve()

    # ``target.mkdir(parents=True, exist_ok=True)`` raises a raw
    # ``FileExistsError`` when ``target`` already exists as a non-directory
    # (regular file, symlink to a file, FIFO, etc.). Every other
    # operator-controlled write path in this command emits a tailored
    # ``typer.echo(..., err=True)`` + ``raise typer.Exit(code=1)`` (see the
    # symlink branches at ``bonfire.toml`` and ``.gitignore`` below).
    # Mirror that pattern here so the operator gets an actionable message
    # instead of a Python traceback. ``Path.exists`` follows symlinks, so
    # a symlink-to-regular-file is also caught.
    if target.exists() and not target.is_dir():
        typer.echo(
            f"Error: target path {target} exists and is not a directory. "
            "Remove it or choose a different path and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Defense-in-depth for permission errors and exotic FS conditions
        # (read-only mount, ENOSPC, ELOOP from a symlink cycle in a parent,
        # etc.). The exact OSError subclass varies by platform; the
        # operator-facing message stays uniform.
        typer.echo(
            f"Error: could not create directory {target}: {exc}",
            err=True,
        )
        raise typer.Exit(code=1) from exc

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

    # W9 Lane B (release-gate-5: every documented surface accurate) —
    # enumerate every artefact ``bonfire init`` creates or touches.
    # README Quick Start enumerated only the subset (``bonfire.toml`` +
    # ``.bonfire/``) and the prior success message hid the rest: the
    # ``agents/`` scaffold the prompt compiler reads from, and the
    # operator-local-state line appended to ``.gitignore``. A README
    # reconciliation test now pins this list against the README so the
    # two cannot drift.
    typer.echo(f"Initialized Bonfire project in {target}")
    typer.echo("Created:")
    typer.echo("  - bonfire.toml (project config)")
    typer.echo("  - .bonfire/ (per-project state directory)")
    typer.echo("  - agents/ (role-local prompt + identity-block overrides)")
    typer.echo(f"  - .gitignore entry: {_GITIGNORE_LINE}")
    raise typer.Exit(0)
