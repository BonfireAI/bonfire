# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Vault Seed Scanner — Reel 6.

Identifies key project documents that should be prioritised for vault
ingestion and estimates project size.  All operations are synchronous
filesystem calls (pathlib) wrapped in an async interface.

Scanner interface::

    async def scan(project_path: Path, emit: ScanCallback) -> int

Safety rails:

  * ``_scan_project_size`` walks the tree without following symlinks
    so a symlink loop (``a/x -> a/``) or a ``/``-rooted symlink cannot
    drive the scanner off into the filesystem at large. On POSIX it
    uses :func:`os.fwalk` (file-descriptor-based, immune to mid-walk
    path-component swaps); on Windows it falls back to :func:`os.walk`
    because ``os.fwalk`` is documented as Unix-only.
  * The walk also enforces a hard cap on directory + file entries
    visited (:data:`_SCAN_ENTRY_CAP`); if reached, the scanner logs a
    WARN and returns the count gathered so far rather than continuing
    forever.
  * ``_scan_test_config`` reads ``pyproject.toml`` through
    :func:`bonfire._safe_read.safe_read_text` so a multi-GB or
    ``/dev/zero``-symlinked file does not hang the scan.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from typing import TYPE_CHECKING

from bonfire._safe_read import safe_read_text
from bonfire.onboard.protocol import ScanCallback, ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scan"]

_log = logging.getLogger(__name__)

PANEL = "vault_seed"

# Directories to exclude from project size estimation.
_EXCLUDED_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__"})

# Config files to check for existence.
_CONFIG_FILES = (
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "tsconfig.json",
    "Makefile",
)

# Standalone test-config files to check for existence.
_TEST_CONFIG_FILES = (
    "pytest.ini",
    "jest.config.js",
    "jest.config.ts",
    ".mocharc.yml",
    ".mocharc.yaml",
)

# Key directories to check for existence.
_KEY_DIRS = ("src", "lib", "tests", "docs", "app")

# Extensions considered for rough LOC estimation.
_CODE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".rs", ".go"})

# Average bytes per line for rough LOC estimation.
_BYTES_PER_LINE = 40

# Hard cap on (file + directory) entries visited by ``_scan_project_size``.
# A malicious symlink loop combined with ``follow_symlinks=False`` already
# blocks infinite recursion, but a project with millions of legitimate
# files (or millions of empty subdirectories) would still be a DoS
# vector for the size estimator. The cap counts both files AND
# subdirectories per iteration so a pathological tree of all-empty
# nested directories cannot walk unbounded. 50k entries covers every
# plausible real project; beyond that we WARN + early-return.
_SCAN_ENTRY_CAP = 50_000

# Cap on the pyproject.toml byte-read in _scan_test_config — we only
# read the file to search for "[tool.pytest" so 1 MiB is generous.
_PYPROJECT_READ_MAX_BYTES = 1 * 1024 * 1024
_PYPROJECT_READ_MAX_BYTES_ENV = "BONFIRE_VAULT_SEED_PYPROJECT_MAX_BYTES"


async def scan(project_path: Path, emit: ScanCallback) -> int:
    """Scan for vault-worthy documents and project metadata.

    Returns the total number of items emitted.
    """
    count = 0

    count += await _scan_key_documents(project_path, emit)
    count += await _scan_architecture_docs(project_path, emit)
    count += await _scan_config_files(project_path, emit)
    count += await _scan_test_config(project_path, emit)
    count += await _scan_ci_config(project_path, emit)
    count += await _scan_key_directories(project_path, emit)
    count += await _scan_project_size(project_path, emit)

    return count


# ---------------------------------------------------------------------------
# Sub-scanners
# ---------------------------------------------------------------------------


async def _scan_key_documents(project_path: Path, emit: ScanCallback) -> int:
    """Detect CLAUDE.md and README.md."""
    count = 0

    # CLAUDE.md — root or .claude/
    if (project_path / "CLAUDE.md").is_file() or (project_path / ".claude" / "CLAUDE.md").is_file():
        await emit(ScanUpdate(panel=PANEL, label="CLAUDE.md", value="found"))
        count += 1

    # README.md
    if (project_path / "README.md").is_file():
        await emit(ScanUpdate(panel=PANEL, label="README.md", value="found"))
        count += 1

    return count


async def _scan_architecture_docs(project_path: Path, emit: ScanCallback) -> int:
    """Count architecture and ADR documents."""
    docs_dir = project_path / "docs"
    if not docs_dir.is_dir():
        return 0

    files: list[Path] = []

    # docs/architecture* files
    files.extend(f for f in docs_dir.glob("architecture*") if f.is_file())

    # docs/adr/* files
    adr_dir = docs_dir / "adr"
    if adr_dir.is_dir():
        files.extend(f for f in adr_dir.iterdir() if f.is_file())

    if not files:
        return 0

    await emit(
        ScanUpdate(
            panel=PANEL,
            label="architecture docs",
            value=f"{len(files)} files",
        )
    )
    return 1


async def _scan_config_files(project_path: Path, emit: ScanCallback) -> int:
    """Detect project config files."""
    count = 0
    for name in _CONFIG_FILES:
        if (project_path / name).is_file():
            await emit(ScanUpdate(panel=PANEL, label="config", value=name))
            count += 1
    return count


async def _scan_test_config(project_path: Path, emit: ScanCallback) -> int:
    """Detect test configuration files and sections."""
    count = 0

    # Standalone test config files
    for name in _TEST_CONFIG_FILES:
        if (project_path / name).is_file():
            await emit(ScanUpdate(panel=PANEL, label="test config", value=name))
            count += 1

    # [tool.pytest] section in pyproject.toml
    pyproject = project_path / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = safe_read_text(
                pyproject,
                env_var=_PYPROJECT_READ_MAX_BYTES_ENV,
                default_bytes=_PYPROJECT_READ_MAX_BYTES,
            )
        except OSError:
            content = ""
        if "[tool.pytest" in content:
            await emit(
                ScanUpdate(
                    panel=PANEL,
                    label="test config",
                    value="pyproject.toml [tool.pytest]",
                )
            )
            count += 1

    return count


async def _scan_ci_config(project_path: Path, emit: ScanCallback) -> int:
    """Detect CI/CD configuration."""
    count = 0

    # GitHub Actions
    wf_dir = project_path / ".github" / "workflows"
    if wf_dir.is_dir():
        workflows = [f for f in wf_dir.iterdir() if f.is_file()]
        if workflows:
            n = len(workflows)
            detail = f"{n} workflow{'s' if n != 1 else ''}"
            await emit(
                ScanUpdate(
                    panel=PANEL,
                    label="CI",
                    value="GitHub Actions",
                    detail=detail,
                )
            )
            count += 1

    # GitLab CI
    if (project_path / ".gitlab-ci.yml").is_file():
        await emit(ScanUpdate(panel=PANEL, label="CI", value="GitLab CI"))
        count += 1

    # CircleCI
    if (project_path / ".circleci" / "config.yml").is_file():
        await emit(ScanUpdate(panel=PANEL, label="CI", value="CircleCI"))
        count += 1

    return count


async def _scan_key_directories(project_path: Path, emit: ScanCallback) -> int:
    """Detect key project directories."""
    count = 0
    for name in _KEY_DIRS:
        if (project_path / name).is_dir():
            await emit(ScanUpdate(panel=PANEL, label="directory", value=f"{name}/"))
            count += 1
    return count


async def _scan_project_size(project_path: Path, emit: ScanCallback) -> int:
    """Estimate total file count and rough LOC.

    Walks the tree without following symlinks so a symlink loop
    (``project/x -> project/``) or a symlink to ``/`` cannot drive the
    scanner off the project tree. Enforces a hard entry cap
    (:data:`_SCAN_ENTRY_CAP`) that counts BOTH files and subdirectories
    per iteration, so a pathological tree of all-empty nested
    directories cannot walk unbounded. On cap, emits a WARNING and
    returns the partial estimate rather than raising.

    Uses :func:`os.fwalk` on POSIX (file-descriptor-based, immune to
    mid-walk path-component swaps) and falls back to :func:`os.walk`
    on Windows where ``os.fwalk`` is unavailable. The two implementations
    enforce the same cap and the same exclusion-prune semantics; only
    the per-file ``stat`` resolution differs (via ``dir_fd`` on POSIX,
    via the joined absolute path on Windows).
    """
    file_count = 0
    code_bytes = 0
    entries_seen = 0
    cap_hit = False

    top = os.fspath(project_path)

    # Per-iteration walker that yields ``(dirpath, dirnames, filenames,
    # stat_one)`` where ``stat_one(fname) -> os.stat_result`` resolves
    # a single filename against the current directory WITHOUT following
    # symlinks. The stat closure abstracts the POSIX ``dir_fd`` /
    # Windows ``os.path.join`` difference so the cap + size loop below
    # is a single implementation.
    #
    # ``os.fwalk`` is documented Unix-only — missing on Windows, WASI,
    # and Emscripten — so we fall back to ``os.walk`` on Windows. Both
    # honour their respective follow-symlinks guards:
    #   * ``os.fwalk`` -> kwarg ``follow_symlinks`` (matches ``os.stat``)
    #   * ``os.walk``  -> kwarg ``followlinks``
    # Both are passed explicitly so a future refactor that flips the
    # default cannot silently re-introduce the DoS surface.
    if sys.platform == "win32":

        def _walker():  # type: ignore[no-redef]
            for dirpath, dirnames, filenames in os.walk(top, followlinks=False):

                def stat_one(fname: str, _dirpath: str = dirpath) -> os.stat_result:
                    return os.stat(
                        os.path.join(_dirpath, fname),
                        follow_symlinks=False,
                    )

                yield dirpath, dirnames, filenames, stat_one
    else:

        def _walker():
            for dirpath, dirnames, filenames, dirfd in os.fwalk(top, follow_symlinks=False):

                def stat_one(fname: str, _dirfd: int = dirfd) -> os.stat_result:
                    # fstat against the directory fd to avoid following
                    # any symlinks the filename itself may point to.
                    return os.stat(fname, dir_fd=_dirfd, follow_symlinks=False)

                yield dirpath, dirnames, filenames, stat_one

    for _dirpath, dirnames, filenames, stat_one in _walker():
        # In-place prune of excluded subdirectories before descent.
        # Mutating ``dirnames`` stops recursion into the pruned names.
        # Combined with the top-down walk this ensures we never visit
        # a file under any of ``_EXCLUDED_DIRS``.
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]

        # Count BOTH dirs and files toward the entry cap so a tree of
        # all-empty nested directories cannot walk unbounded. The
        # post-prune ``dirnames`` length is what we actually descend
        # into, so it is the right count for the cap budget.
        entries_seen += len(dirnames) + len(filenames)
        if entries_seen > _SCAN_ENTRY_CAP:
            cap_hit = True
            # Process as many files as the remaining cap budget allows
            # so the count is well-defined at the boundary rather than
            # dependent on dict-order or platform.
            overshoot = entries_seen - _SCAN_ENTRY_CAP
            budget_for_files = max(0, len(filenames) - overshoot)
            consumable = filenames[:budget_for_files]
        else:
            consumable = filenames

        for fname in consumable:
            file_count += 1
            ext = os.path.splitext(fname)[1]
            if ext in _CODE_EXTENSIONS:
                with contextlib.suppress(OSError):
                    # Only count regular files; symlinks-to-files
                    # report the link's own (small) size with
                    # ``follow_symlinks=False``, which still gives a
                    # sane sample.
                    code_bytes += stat_one(fname).st_size

        if cap_hit:
            break

    if cap_hit:
        _log.warning(
            "vault_seed project-size scan hit entry cap (%d entries); "
            "returning partial result for %s",
            _SCAN_ENTRY_CAP,
            project_path,
        )

    loc_estimate = code_bytes // _BYTES_PER_LINE if code_bytes else 0

    detail = f"~{loc_estimate} LOC estimated" if loc_estimate else "no code files"

    await emit(
        ScanUpdate(
            panel=PANEL,
            label="project size",
            value=f"~{file_count} files",
            detail=detail,
        )
    )
    return 1
