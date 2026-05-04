# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Vault Seed Scanner — Reel 6.

Identifies key project documents that should be prioritised for vault
ingestion and estimates project size.  All operations are synchronous
filesystem calls (pathlib) wrapped in an async interface.

Scanner interface::

    async def scan(project_path: Path, emit: ScanCallback) -> int

"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ScanCallback, ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scan"]

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
        content = pyproject.read_text()
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
    """Estimate total file count and rough LOC."""
    file_count = 0
    code_bytes = 0

    for item in project_path.rglob("*"):
        # Skip excluded directory trees.
        parts = item.parts
        if any(part in _EXCLUDED_DIRS for part in parts):
            continue
        if not item.is_file():
            continue

        file_count += 1

        if item.suffix in _CODE_EXTENSIONS:
            with contextlib.suppress(OSError):
                code_bytes += item.stat().st_size

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
