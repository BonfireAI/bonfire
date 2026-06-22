# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Install-skill command — copy the bundled Claude Code skill to a user-writable location.

Bonfire ships as an opinion package for Claude Code. The ``bonfire-ai``
wheel bundles a Claude Code skill at ``bonfire/skill/SKILL.md``;
``bonfire install-skill`` copies it to a user-writable target
(defaulting to ``~/.claude/skills/bonfire/``) so the user can invoke
``/bonfire scan`` from inside a Claude Code session.

Design choices, in order of contract weight:

1. **Copy, not symlink.** A symlink would chain the installed skill
   to the wheel's site-packages location — a routine ``pip install -U``
   silently replaces the user's content. Copies are stable: the user
   can edit the installed file, and the next package upgrade does not
   silently rewrite their edits.

2. **Refuse-to-overwrite divergent content.** Idempotent re-install
   against byte-identical content is a silent no-op (exit 0). Re-install
   against divergent content (user-edited OR earlier-bonfire-version
   bundle content) refuses with exit 1, naming ``--force`` as the
   escape hatch. This prevents the trap where a user edits their
   skill, runs ``pip install -U bonfire-ai`` and then re-installs out
   of muscle memory, and loses their edits with no warning.

3. **All filesystem writes via ``_safe_write``.** Mirrors the
   ``init.py`` symlink-rejection + O_NOFOLLOW + O_EXCL defense
   pattern. The target file is operator-controlled; a planted symlink
   at ``~/.claude/skills/bonfire/SKILL.md -> ~/.ssh/authorized_keys``
   would otherwise be an arbitrary-write primitive.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import typer

from bonfire._safe_read import safe_read_capped_text
from bonfire._safe_write import safe_write_text

# Hard byte cap on the existing-target divergence read. The bundled
# SKILL.md is single-digit kilobytes; 1 MiB is comfortably beyond any
# honest payload while bounding the damage from a planted oversized
# file at the target. Symmetric with the cap in ``init.py``.
_INSTALL_SKILL_READ_MAX_BYTES: int = 1 * 1024 * 1024

# Default install location. ``~/.claude/skills/<name>/`` is the
# convention every other skill on this machine follows
# (candyfactory-constable, candyfactory-prophet, linear, ...). The
# tilde is expanded via ``Path.expanduser`` so ``$HOME`` resolution is
# explicit and platform-portable.
_DEFAULT_TARGET = "~/.claude/skills/bonfire/"


def _bundled_skill_files() -> dict[str, bytes]:
    """Enumerate every file the bundled skill ships.

    Returns a mapping ``{relative_path: bytes}`` so the copy loop can
    recreate the full skill directory shape at the target. v1.0.0
    ships a single ``SKILL.md`` (no companion files); enumerating via
    the resource walker keeps the code shape ready for the v1.x
    expansion to multi-file skills (per the candyfactory-prophet
    precedent of ``critic.md``, ``voice.md``, ``platforms/*.md``)
    without a second refactor.
    """
    root = importlib.resources.files("bonfire.skill")
    files: dict[str, bytes] = {}
    for entry in root.iterdir():
        # iterdir yields Traversable entries — we only ship flat
        # files in v1.0.0, but guard against accidentally including
        # __pycache__ or other non-file artefacts that could appear
        # if the package layout evolves.
        if not entry.is_file():
            continue
        name = entry.name
        # __init__.py is a packaging artefact (if present); never
        # ship it as part of the skill content.
        if name == "__init__.py":
            continue
        files[name] = entry.read_bytes()
    return files


def install_skill(
    target: str = typer.Option(
        _DEFAULT_TARGET,
        "--target",
        help=(
            "Directory to install the skill into. Defaults to "
            "~/.claude/skills/bonfire/. The directory is created if absent."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Overwrite an existing skill at the target even when its "
            "content diverges from the bundled version. Use this after "
            "intentionally editing the installed skill and wanting to "
            "reset to the shipped version."
        ),
    ),
) -> None:
    """Install the bundled Claude Code skill at the target directory."""
    # Resolve ``~`` so the rest of the command operates on an absolute path.
    # Resolve symlinks in the PARENT chain (not the target file itself —
    # the per-file symlink refusal lives in ``safe_write_text``).
    target_dir = Path(target).expanduser().resolve()

    # Inventory the bundled skill content up-front. If the wheel is
    # missing the skill (broken install, bad packaging), fail loudly
    # with a clear message rather than silently creating an empty
    # target directory.
    bundled = _bundled_skill_files()
    if not bundled:
        typer.echo(
            "Error: the bundled Bonfire skill is empty or missing. "
            "This indicates a broken bonfire-ai install — reinstall "
            "with `pip install --force-reinstall bonfire-ai`.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Per-file divergence + overwrite-policy decision, computed BEFORE
    # any write. Building the full plan first means we can refuse the
    # whole install cleanly when ANY file diverges, rather than
    # writing some files and then failing partway — which would
    # leave the target in a half-installed state the user can't
    # easily reason about.
    diverged: list[str] = []
    if target_dir.exists():
        for name, expected_bytes in bundled.items():
            installed_path = target_dir / name
            if not installed_path.exists():
                # Missing file at target — this is a fresh-install
                # write, not a divergence. Skip the policy check.
                continue
            if installed_path.is_symlink():
                # Defense-in-depth: a symlink at the install path is
                # refused at write time by ``safe_write_text``; surface
                # the same refusal here so the user gets one clean
                # message rather than a half-applied install.
                typer.echo(
                    f"Error: {installed_path} is a symlink. Refusing to "
                    "follow or overwrite a symlinked skill file. Remove "
                    "the symlink and re-run.",
                    err=True,
                )
                raise typer.Exit(code=1)
            try:
                on_disk = safe_read_capped_text(
                    installed_path, max_bytes=_INSTALL_SKILL_READ_MAX_BYTES
                )
            except (OSError, ValueError) as exc:
                typer.echo(
                    f"Error: could not read existing {installed_path}: {exc}",
                    err=True,
                )
                raise typer.Exit(code=1) from exc
            if on_disk.encode("utf-8") != expected_bytes:
                diverged.append(name)

    if diverged and not force:
        # Refuse-to-overwrite: name --force as the escape hatch.
        # Listing the divergent files (rather than just naming the
        # directory) gives the user something concrete to grep their
        # local edits against before deciding.
        file_list = ", ".join(sorted(diverged))
        typer.echo(
            f"Error: skill at {target_dir} differs from bundle "
            f"(divergent files: {file_list}). Pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Create the target directory if needed. ``parents=True`` so the
    # default ``~/.claude/skills/bonfire/`` works even when
    # ``~/.claude/skills/`` is itself absent on a fresh box.
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        typer.echo(
            f"Error: could not create target directory {target_dir}: {exc}",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    # Copy each bundled file. The byte-identical case (idempotent
    # re-install) is a silent skip — re-writing the file would touch
    # the mtime for no observable benefit and would defeat the
    # ``--force`` opt-in semantics (force is meaningful only when
    # something would otherwise change).
    written: list[str] = []
    for name, expected_bytes in bundled.items():
        installed_path = target_dir / name
        if installed_path.exists() and not installed_path.is_symlink():
            try:
                on_disk = installed_path.read_bytes()
            except OSError:
                on_disk = b""
            if on_disk == expected_bytes:
                # Idempotent silent skip: bytes already match.
                continue
        # Either the file is missing OR it diverges AND ``--force``
        # was passed (the no-force divergent path was already
        # rejected above). Route the write through ``safe_write_text``
        # with ``allow_existing=True`` so an existing regular file is
        # overwritten while a symlink is still refused at open(2).
        content = expected_bytes.decode("utf-8")
        try:
            safe_write_text(installed_path, content, allow_existing=True)
        except FileExistsError as exc:
            # ``safe_write_text`` raises FileExistsError with a
            # "symlink"-mentioning message when a symlink is detected.
            # Surface that to the operator with the same shape as the
            # pre-check branch above.
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        written.append(name)

    # Success reporting. Quiet on full no-op (idempotent re-install
    # with everything already in place), informative when something
    # actually happened.
    if written:
        verb = "Updated" if force and diverged else "Installed"
        typer.echo(f"{verb} Bonfire skill at {target_dir}")
        for name in written:
            typer.echo(f"  - {name}")
    else:
        typer.echo(f"Bonfire skill already up to date at {target_dir}")
