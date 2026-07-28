# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Init command — scaffold a new Bonfire project.

``bonfire init`` is the first command a stranger runs, so every failure
it can hit is a first-impression failure. Two rules govern this module:

1. **No traceback ever reaches the operator.** Every filesystem
   operation here touches a path the operator controls — a read-only
   directory, a full disk, a planted symlink, a directory sitting where
   a file belongs. Each one is refused with a typed, actionable message
   and exit code 1.
2. **A refusal is never reported as a success.** The success block
   below claims artefacts exist in the shape Bonfire will later read
   them in; a path that cannot hold that shape is refused *before* the
   claim, never absorbed into an ``Already present:`` line.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from bonfire._safe_read import safe_read_capped_text
from bonfire._safe_write import safe_append_text, safe_write_text

# Hard byte cap on operator-controlled config reads in ``bonfire init``.
# ``.gitignore`` + ``bonfire.toml`` are kilobytes at most in legitimate
# use; 1 MiB is comfortably beyond any honest payload while bounding the
# damage from a planted oversized file. Centralised here so the 3 read
# sites stay consistent.
_INIT_READ_MAX_BYTES: int = 1 * 1024 * 1024

# ``.bonfire/`` carries a MIX of operator-local state (the per-machine
# ``tools.local.toml`` written by ``bonfire scan``) AND artefacts that
# ARE committable: ``.bonfire/sessions`` (handoff history),
# ``.bonfire/context.json`` (project config), ``.bonfire/vault``
# (knowledge backend seed), ``.bonfire/costs.jsonl`` (cost ledger, when
# operator opts in to commit). A broad ``.bonfire/`` ignore would
# silently exclude those committable sub-paths and break workflows that
# depend on them landing in git. The narrower entry names the single
# operator-local file the W8.G work introduced so other sub-paths under
# ``.bonfire/`` remain stageable by default — a contract pinned by the
# gitignore-narrowness test in ``test_tools_section_is_local.py``. The
# operator can still add broader patterns to ``.gitignore`` by hand if
# they want; ``bonfire init`` does not assume that policy.
_GITIGNORE_LINE = ".bonfire/tools.local.toml"


# ---------------------------------------------------------------------------
# Typed refusals — no operator-controlled failure reaches the terminal as
# a Python traceback.
# ---------------------------------------------------------------------------


def _refuse(message: str) -> NoReturn:
    """Emit *message* on stderr and exit 1.

    The single refusal shape for this command. Callers pass a message
    that names the path, the condition, and what the operator can do
    about it; nothing here ever raises past Typer.
    """
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _require_regular_file_slot(path: Path, label: str) -> None:
    """Refuse when *path* exists as something other than a regular file.

    ``Path.exists()`` answers "is there something here", not "is there a
    file here". A directory named ``bonfire.toml`` satisfies the
    existence check, so the write is skipped and the success block
    reports the config as ``Already present:`` — a project that no
    Bonfire command can actually read, announced as ready.

    Symlinks are deliberately NOT handled here: they have their own
    refusal branches (with their own message naming the symlink case)
    and folding them into this one would blur an attempted attack into
    a housekeeping problem.
    """
    if path.is_symlink():
        return
    if path.exists() and not path.is_file():
        _refuse(
            f"Error: {label} at {path} exists and is not a regular file. "
            f"bonfire init writes {label} as a regular file and Bonfire reads "
            "it back as one. Remove or rename what is there and re-run."
        )


def _require_directory_slot(path: Path, label: str) -> None:
    """Refuse when *path* exists as something other than a directory.

    Covers a regular file, a FIFO, and a symlink to any of those. A
    symlink pointing at a real directory is left alone — that is a
    working layout, and ``mkdir(exist_ok=True)`` is a no-op on it. A
    dangling symlink is refused: ``mkdir`` raises ``FileExistsError``
    on it, which is exactly the traceback this guard exists to prevent.
    """
    if path.is_symlink() and not path.exists():
        _refuse(
            f"Error: {label} at {path} is a symlink pointing at nothing. "
            "Remove the symlink and re-run."
        )
    if path.exists() and not path.is_dir():
        _refuse(
            f"Error: {label} at {path} exists and is not a directory. "
            "Remove or rename what is there and re-run."
        )


def _write_or_refuse(path: Path, body: str, *, label: str) -> None:
    """``safe_write_text`` with every failure turned into a typed refusal.

    ``FileExistsError`` carries the helper's own operator-facing message
    (it names the symlink case explicitly), so it is passed through
    verbatim. Every other ``OSError`` — a read-only directory, a full
    disk, a revoked permission — becomes a message naming the path and
    the underlying condition instead of a traceback.
    """
    try:
        safe_write_text(path, body)
    except FileExistsError as exc:
        _refuse(f"Error: {exc}")
    except OSError as exc:
        _refuse(
            f"Error: could not write {label} at {path}: {exc}. "
            "Check that the directory exists and is writable, then re-run."
        )


def _append_or_refuse(path: Path, body: str, *, label: str) -> None:
    """``safe_append_text`` with every failure turned into a typed refusal."""
    try:
        safe_append_text(path, body)
    except FileExistsError as exc:
        _refuse(f"Error: {exc}")
    except OSError as exc:
        _refuse(
            f"Error: could not append to {label} at {path}: {exc}. "
            "Check that the file is writable, then re-run."
        )


def _read_or_refuse(path: Path, label: str) -> str:
    """``safe_read_capped_text`` with every failure turned into a typed refusal.

    Used where the read's outcome decides what gets written. The
    cosmetic pre-existence read in :func:`init` deliberately does NOT
    use this: there, an unreadable file changes only which verb is
    printed, and refusing the whole command over it would be a worse
    answer than the one the write path is about to give anyway.
    """
    try:
        return safe_read_capped_text(path, max_bytes=_INIT_READ_MAX_BYTES)
    except FileExistsError as exc:
        _refuse(f"Error: {exc}")
    except ValueError as exc:
        _refuse(f"Error: refusing to rewrite {label} at {path}: {exc}")
    except OSError as exc:
        _refuse(
            f"Error: could not read {label} at {path}: {exc}. "
            "Check the file's permissions and re-run."
        )


def _make_directory_or_refuse(path: Path, label: str) -> None:
    """``mkdir(exist_ok=True)`` with every failure turned into a typed refusal."""
    try:
        path.mkdir(exist_ok=True)
    except OSError as exc:
        _refuse(
            f"Error: could not create {label} at {path}: {exc}. "
            "Check that the parent directory is writable, then re-run."
        )


# ---------------------------------------------------------------------------
# .gitignore seeding
# ---------------------------------------------------------------------------


def _ensure_gitignore_entry(target: Path, line: str) -> None:
    """Append ``line`` to ``target/.gitignore`` iff not already present.

    Idempotent: re-running ``bonfire init`` MUST NOT duplicate an entry
    (the no-duplicate canary pins this). The presence check matches a
    stripped/non-comment line against the requested entry; existing
    comments and blank lines are preserved. Creates ``.gitignore`` if
    absent.

    Uses :func:`safe_write_text` (W7.M) when creating the file fresh
    and :func:`safe_append_text` (W7.M append helper) when extending
    an existing ``.gitignore``. ``safe_append_text`` carries the
    ``O_NOFOLLOW`` defense-in-depth guard that closes the TOCTOU
    window a race-planted symlink could otherwise slip through
    between the ``is_symlink()`` pre-check and the append.
    """
    gitignore_path = target / ".gitignore"

    if gitignore_path.is_symlink():
        # Defensive parallel to the bonfire.toml symlink branch below:
        # refuse to follow a symlinked .gitignore. The error is
        # advisory — the operator can remove the symlink and re-run.
        typer.echo(
            f".gitignore at {gitignore_path} is a symlink. Refusing to "
            "follow or overwrite a symlinked .gitignore. Remove the "
            "symlink and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Existence is not shape: a DIRECTORY named ``.gitignore`` satisfies
    # ``exists()`` and then fails at read time deep inside the safe-read
    # helper. Refuse it here, by name.
    _require_regular_file_slot(gitignore_path, ".gitignore")

    if not gitignore_path.exists():
        # Fresh file — create with the entry and a brief header so a
        # future contributor reading ``.gitignore`` understands why the
        # operator-local file is excluded.
        body = f"# Bonfire — operator-local state (do not commit).\n{line}\n"
        _write_or_refuse(gitignore_path, body, label=".gitignore")
        return

    # W11 M2: route through ``safe_read_capped_text`` so the read uses
    # ``O_NOFOLLOW`` defense-in-depth against a race-planted symlink
    # between the ``is_symlink`` pre-check above and this read.
    existing = _read_or_refuse(gitignore_path, ".gitignore")
    if line in [ln.strip() for ln in existing.splitlines()]:
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
    # through to an attacker-controlled target.
    suffix = "" if existing.endswith("\n") else "\n"
    _append_or_refuse(gitignore_path, suffix + f"{line}\n", label=".gitignore")


def _existing_gitignore_entries(gitignore_path: Path) -> set[str]:
    """Return the seeded entries already present in ``.gitignore``.

    Cosmetic: the result decides ``Created:`` vs ``Already present:`` in
    the success block, nothing else. An unreadable or oversized file
    yields the empty set rather than a refusal — the write path that
    follows will produce the real, typed error for the same condition.
    """
    if not gitignore_path.is_file() or gitignore_path.is_symlink():
        return set()
    try:
        body = safe_read_capped_text(gitignore_path, max_bytes=_INIT_READ_MAX_BYTES)
    except (OSError, ValueError):
        return set()
    return {ln.strip() for ln in body.splitlines()} & {_GITIGNORE_LINE}


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
        # W11 M2: route through ``safe_read_capped_text`` so the read uses
        # ``O_NOFOLLOW`` defense-in-depth against a race-planted symlink
        # between the ``is_symlink`` pre-check above and this read. The
        # cap-exceeded branch (``ValueError``) is treated identically to
        # an unreadable file — the legacy-detection nudge is best-effort
        # and MUST NOT crash ``bonfire init``.
        body = safe_read_capped_text(toml_path, max_bytes=_INIT_READ_MAX_BYTES)
    except (OSError, ValueError):
        return False
    # Match the section header at line start (TOML section syntax). Plain
    # substring is enough — a sub-table like ``[bonfire.tools.subkey]``
    # also signals the legacy shape and merits the same nudge.
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("[bonfire.tools]") or stripped.startswith("[bonfire.tools."):
            return True
    return False


# ---------------------------------------------------------------------------
# Target preparation + reporting
# ---------------------------------------------------------------------------


def _prepare_target_dir(project_dir: str) -> Path:
    """Resolve *project_dir* and make sure it is a usable directory.

    ``target.mkdir(parents=True, exist_ok=True)`` raises a raw
    ``FileExistsError`` when ``target`` already exists as a non-directory
    (regular file, symlink to a file, FIFO, etc.), and a raw
    ``PermissionError`` when a parent is not writable. Both become
    typed refusals here. ``Path.exists`` follows symlinks, so a
    symlink-to-regular-file is also caught.
    """
    target = Path(project_dir).resolve()

    if target.exists() and not target.is_dir():
        _refuse(
            f"Error: target path {target} exists and is not a directory. "
            "Remove it or choose a different path and re-run."
        )

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Defense-in-depth for permission errors and exotic FS conditions
        # (read-only mount, ENOSPC, ELOOP from a symlink cycle in a parent,
        # etc.). The exact OSError subclass varies by platform; the
        # operator-facing message stays uniform.
        _refuse(f"Error: could not create directory {target}: {exc}")
    return target


def _report(target: Path, pre_existed: dict[str, bool], seeded_before: set[str]) -> None:
    """Print the per-artefact summary.

    W9 Lane B (release-gate-5: every documented surface accurate) —
    enumerate every artefact ``bonfire init`` creates or touches. README
    Quick Start enumerated only the subset (``bonfire.toml`` +
    ``.bonfire/``) and the prior success message hid the rest: the
    ``agents/`` scaffold the prompt compiler reads from, and the
    operator-local-state line appended to ``.gitignore``. A README
    reconciliation test pins this list against the README so the two
    cannot drift.

    Per-artefact verb prefix: ``Created:`` when the artefact was created
    this run, ``Already present:`` when it pre-existed. The artefact-name
    part of each line is preserved verbatim so the W9 Lane B
    reconciliation pin (substring search for artefact names in stdout)
    keeps passing. Every line printed here describes a path this command
    has already confirmed exists in the shape it claims.
    """

    def _verb(existed: bool) -> str:
        return "Already present" if existed else "Created"

    typer.echo(f"Initialized Bonfire project in {target}")
    typer.echo(f"  - {_verb(pre_existed['toml'])}: bonfire.toml (project config)")
    typer.echo(f"  - {_verb(pre_existed['bonfire_dir'])}: .bonfire/ (per-project state directory)")
    typer.echo(
        f"  - {_verb(pre_existed['agents_dir'])}: agents/ "
        "(role-local prompt + identity-block overrides)"
    )
    # The .gitignore entry is reported per-entry, not per-file, because
    # the file may pre-exist with unrelated user content while the entry
    # is freshly appended. Reporting "Already present" only when BOTH the
    # file and the line existed before this run keeps the truth honest.
    entry_existed = pre_existed["gitignore"] and _GITIGNORE_LINE in seeded_before
    typer.echo(f"  - {_verb(entry_existed)}: .gitignore entry: {_GITIGNORE_LINE}")


def init(
    project_dir: str = typer.Argument(".", help="Directory to initialize."),
) -> None:
    """Initialize a new Bonfire project."""
    target = _prepare_target_dir(project_dir)

    toml_path = target / "bonfire.toml"
    bonfire_dir = target / ".bonfire"
    agents_dir = target / "agents"
    gitignore_path = target / ".gitignore"

    # Shape gate, before anything is written: every artefact slot must be
    # able to hold the shape Bonfire will later read it in. Existence is
    # not shape — this is what keeps a directory named ``bonfire.toml``
    # from being skipped by the writer and then announced as a config.
    _require_regular_file_slot(toml_path, "bonfire.toml")
    _require_regular_file_slot(gitignore_path, ".gitignore")
    _require_directory_slot(bonfire_dir, ".bonfire/")
    _require_directory_slot(agents_dir, "agents/")

    # Per-artefact existence detection for idempotent stdout. Captured
    # BEFORE any creation so the success block can report ``Created:`` vs
    # ``Already present:`` truthfully per artefact, not per directory.
    pre_existed = {
        "toml": toml_path.exists() or toml_path.is_symlink(),
        "bonfire_dir": bonfire_dir.exists(),
        "agents_dir": agents_dir.exists(),
        "gitignore": gitignore_path.exists() or gitignore_path.is_symlink(),
    }
    seeded_before = _existing_gitignore_entries(gitignore_path)

    # Legacy ``[bonfire.tools]`` migration nudge. Emit BEFORE the
    # artefact-creation block so the operator sees the warning even when
    # the rest of init is a no-op (re-run case). The file itself is NEVER
    # modified by this detection — ``load_tools_config``'s "silent orphan"
    # reader contract stays intact.
    if pre_existed["toml"] and _has_legacy_tools_section(toml_path):
        typer.echo(
            f"Warning: {toml_path} contains a legacy [bonfire.tools] section. "
            "Move it to .bonfire/tools.local.toml — the operator-local file "
            "the W8.G migration introduced. The main bonfire.toml stays "
            "project-portable; the local file holds per-machine state. "
            "(bonfire init does not auto-move; edit by hand.)",
            err=True,
        )

    # ``Path.exists()`` follows symlinks, so a dangling symlink at
    # ``bonfire.toml -> ~/.ssh/authorized_keys`` returns False and a write
    # would open the attacker-controlled symlink target in write+truncate
    # mode — an arbitrary-write primitive. ``safe_write_text`` refuses any
    # symlink at the target path (and uses O_NOFOLLOW defense-in-depth
    # against the TOCTOU race). When the path is a non-symlink regular
    # file we leave it untouched (idempotent ``bonfire init`` behavior).
    if toml_path.is_symlink():
        typer.echo(
            f"bonfire.toml at {toml_path} is a symlink. Refusing to follow "
            "or overwrite a symlinked config. Remove the symlink and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)
    if not toml_path.exists():
        _write_or_refuse(toml_path, "[bonfire]\n", label="bonfire.toml")

    _make_directory_or_refuse(bonfire_dir, ".bonfire/")
    _make_directory_or_refuse(agents_dir, "agents/")

    # W8.G — seed .gitignore so ``.bonfire/tools.local.toml`` (and any
    # future operator-local file under ``.bonfire/``) is never staged
    # for commit. Idempotent: re-running ``bonfire init`` does not
    # duplicate the entry.
    _ensure_gitignore_entry(target, _GITIGNORE_LINE)

    _report(target, pre_existed, seeded_before)
    raise typer.Exit(0)
