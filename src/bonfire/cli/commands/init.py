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


def _has_legacy_tools_section(toml_path: Path) -> bool:
    """Return True iff ``toml_path`` contains a top-level ``[bonfire.tools]`` section.

    Best-effort, non-strict: a substring scan on the file body. The W8.G
    migration demoted the tools table to ``.bonfire/tools.local.toml``;
    a pre-migration ``bonfire.toml`` that still carries the section is
    silently orphaned by :func:`bonfire.onboard.config_generator.load_tools_config`
    (no warning, no mutation — pinned by ``test_tools_section_is_local.py``).
    ``bonfire init`` surfaces a one-line nudge so the operator knows to
    move it; the file itself is NEVER modified by this detection.
    Symlinks are NOT followed (parallel to the symlink-rejection branch
    below) so a planted symlink can't side-channel the check.
    """
    if not toml_path.is_file() or toml_path.is_symlink():
        return False
    try:
        body = toml_path.read_text(encoding="utf-8")
    except OSError:
        return False
    # Match the section header at line start (TOML section syntax). Plain
    # substring is enough — a sub-table like ``[bonfire.tools.subkey]``
    # also signals the legacy shape and merits the same nudge.
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("[bonfire.tools]") or stripped.startswith("[bonfire.tools."):
            return True
    return False


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

    # Per-artefact existence detection for idempotent stdout.
    # Capture each artefact's pre-existence state BEFORE any creation so
    # the success block can report ``Created:`` vs ``Already present:``
    # truthfully per artefact, not per directory. The W9 Lane B
    # reconciliation pin (every artefact name appears in stdout) is
    # preserved — only the verb prefix changes.
    toml_path = target / "bonfire.toml"
    bonfire_dir = target / ".bonfire"
    agents_dir = target / "agents"
    gitignore_path = target / ".gitignore"

    toml_pre_existed = toml_path.exists() or toml_path.is_symlink()
    bonfire_dir_pre_existed = bonfire_dir.exists()
    agents_dir_pre_existed = agents_dir.exists()
    gitignore_pre_existed = gitignore_path.exists() or gitignore_path.is_symlink()
    # Pre-existing .gitignore may or may not already carry our line; the
    # ``_ensure_gitignore_entry`` helper is idempotent. Detect the line's
    # pre-existence so the success message reports the truthful state of
    # the entry, not just the file.
    gitignore_line_pre_existed = False
    if gitignore_path.is_file() and not gitignore_path.is_symlink():
        try:
            existing_lines = [ln.strip() for ln in gitignore_path.read_text().splitlines()]
            gitignore_line_pre_existed = _GITIGNORE_LINE in existing_lines
        except OSError:
            gitignore_line_pre_existed = False

    # Legacy ``[bonfire.tools]`` migration nudge. Emit BEFORE
    # the artefact-creation block so the operator sees the warning even
    # when the rest of init is a no-op (re-run case). The file itself is
    # NEVER modified by this detection — ``load_tools_config``'s "silent
    # orphan" reader contract stays intact.
    if toml_pre_existed and _has_legacy_tools_section(toml_path):
        typer.echo(
            f"Warning: {toml_path} contains a legacy [bonfire.tools] section. "
            "Move it to .bonfire/tools.local.toml — the operator-local file "
            "the W8.G migration introduced. The main bonfire.toml stays "
            "project-portable; the local file holds per-machine state. "
            "(bonfire init does not auto-move; edit by hand.)",
            err=True,
        )

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

    bonfire_dir.mkdir(exist_ok=True)
    agents_dir.mkdir(exist_ok=True)

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
    #
    # Per-artefact verb prefix. ``Created:`` when the artefact
    # was created this run; ``Already present:`` when it pre-existed.
    # The artefact-name part of each line is preserved verbatim so the
    # W9 Lane B reconciliation pin (substring search for artefact names
    # in stdout) keeps passing.
    typer.echo(f"Initialized Bonfire project in {target}")

    def _verb(pre_existed: bool) -> str:
        return "Already present" if pre_existed else "Created"

    typer.echo(f"  - {_verb(toml_pre_existed)}: bonfire.toml (project config)")
    typer.echo(f"  - {_verb(bonfire_dir_pre_existed)}: .bonfire/ (per-project state directory)")
    typer.echo(
        f"  - {_verb(agents_dir_pre_existed)}: agents/ "
        "(role-local prompt + identity-block overrides)"
    )
    # The .gitignore entry is reported per-entry, not per-file, because
    # the file may pre-exist with unrelated user content while the entry
    # is freshly appended. Reporting "Already present" only when BOTH the
    # file and the line existed before this run keeps the truth honest.
    gitignore_entry_pre_existed = gitignore_pre_existed and gitignore_line_pre_existed
    typer.echo(f"  - {_verb(gitignore_entry_pre_existed)}: .gitignore entry: {_GITIGNORE_LINE}")
    raise typer.Exit(0)
