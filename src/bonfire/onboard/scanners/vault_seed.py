# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Vault Seed Scanner — Reel 6.

Identifies key project documents that should be prioritised for vault
ingestion and estimates project size.  All operations are synchronous
filesystem calls (pathlib) wrapped in an async interface.

Scanner interface::

    async def scan(project_path: Path, emit: ScanCallback) -> int

Safety rails:

  * ``_scan_project_size`` walks the tree via :func:`os.fwalk` with
    ``followlinks=False`` so a symlink loop (``a/x -> a/``) or a
    ``/``-rooted symlink cannot drive the scanner off into the
    filesystem at large.
  * The walk also enforces a hard cap on entries visited
    (:data:`_SCAN_ENTRY_CAP`); if reached, the scanner logs a WARN and
    returns the count gathered so far rather than continuing forever.
  * ``_scan_test_config`` reads ``pyproject.toml`` through
    :func:`bonfire._safe_read.safe_read_text` so a multi-GB or
    ``/dev/zero``-symlinked file does not hang the scan.
"""

from __future__ import annotations

import contextlib
import logging
import os
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
# A malicious symlink loop combined with ``followlinks=False`` already
# blocks infinite recursion, but a project with millions of legitimate
# files would still be a DoS vector for the size estimator. 50k entries
# covers every plausible real project; beyond that we WARN + early-return.
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

    Uses :func:`os.fwalk` with ``followlinks=False`` so a symlink loop
    (``project/x -> project/``) or a symlink to ``/`` cannot drive the
    scanner off the project tree. Enforces a hard entry cap
    (:data:`_SCAN_ENTRY_CAP`); on cap, emits a WARNING and returns the
    partial estimate rather than raising.
    """
    file_count = 0
    code_bytes = 0
    entries_seen = 0
    cap_hit = False

    # ``os.fwalk`` returns ``(dirpath, dirnames, filenames, dirfd)``.
    # ``follow_symlinks=False`` (default in CPython) is what guards
    # against symlink-loop walks; we set it explicitly here as a
    # defensive lock so a future refactor that flips the default does
    # not silently re-introduce the DoS surface. Note that ``os.fwalk``
    # uses ``follow_symlinks`` (matching ``os.stat``); ``os.walk`` uses
    # ``followlinks`` — the names differ across the stdlib.
    top = os.fspath(project_path)
    walker = os.fwalk(top, follow_symlinks=False)

    for _dirpath, dirnames, filenames, dirfd in walker:
        # In-place prune of excluded subdirectories before descent. This
        # is the canonical ``os.walk`` / ``os.fwalk`` pattern; mutating
        # ``dirnames`` stops recursion into the pruned names. Combined
        # with the top-down walk this ensures we never visit a file
        # under any of ``_EXCLUDED_DIRS``.
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]

        for fname in filenames:
            entries_seen += 1
            if entries_seen > _SCAN_ENTRY_CAP:
                cap_hit = True
                break

            file_count += 1

            # Code-extension byte sampling for LOC estimation.
            # ``os.path.splitext`` matches Path.suffix's behaviour.
            ext = os.path.splitext(fname)[1]
            if ext in _CODE_EXTENSIONS:
                with contextlib.suppress(OSError):
                    # fstat against the directory fd to avoid following
                    # any symlinks the filename itself may point to.
                    st = os.stat(fname, dir_fd=dirfd, follow_symlinks=False)
                    # Only count regular files; symlinks-to-files report
                    # the link's own (small) size with follow_symlinks=
                    # False, which still gives a sane sample.
                    code_bytes += st.st_size

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
