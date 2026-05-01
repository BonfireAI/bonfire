# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""CLI Toolchain Scanner — Reel 2.

Detects installed CLI tools, extracts versions via async subprocess,
and checks capabilities for select tools (gh auth, docker daemon).
"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ScanCallback, ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scan"]

TOOLS: list[str] = [
    "git",
    "python3",
    "pip",
    "uv",
    "node",
    "npm",
    "docker",
    "gh",
    "claude",
    "ruff",
    "eslint",
    "prettier",
    "black",
    "mypy",
    "pyright",
    "make",
    "cmake",
    "cargo",
    "go",
    "java",
    "terraform",
    "kubectl",
    "tmux",
    "jq",
]

_VERSION_RE = re.compile(r"\d+\.\d+[\.\d]*")
_VERSION_TIMEOUT = 5.0
_CAPABILITY_TIMEOUT = 2.0
_PANEL = "cli_toolchain"

# Capability checks: tool_name -> (args, success_detail, timeout)
_CAPABILITY_CHECKS: dict[str, tuple[list[str], str, float]] = {
    "gh": (["gh", "auth", "status"], "authenticated", _CAPABILITY_TIMEOUT),
    "docker": (["docker", "info"], "daemon running", _CAPABILITY_TIMEOUT),
}


async def _get_version(tool: str) -> str:
    """Run ``<tool> --version`` and extract a version string.

    Returns the parsed version (e.g. ``"3.12.3"``) or ``"installed"`` if
    version extraction fails for any reason.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            tool,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_VERSION_TIMEOUT,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return "installed"
    except OSError:
        return "installed"

    # Some tools print version to stderr (e.g. java).
    output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
    match = _VERSION_RE.search(output)
    return match.group(0) if match else "installed"


async def _check_capability(tool: str) -> str:
    """Run a capability check for a tool. Returns detail string or empty."""
    spec = _CAPABILITY_CHECKS.get(tool)
    if spec is None:
        return ""

    args, success_detail, timeout = spec
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ""
    except OSError:
        return ""

    return success_detail if proc.returncode == 0 else ""


async def _detect_tool(tool: str) -> ScanUpdate | None:
    """Detect a single tool: check existence, version, capabilities."""
    if shutil.which(tool) is None:
        return None

    version = await _get_version(tool)
    detail = await _check_capability(tool)

    return ScanUpdate(
        panel=_PANEL,
        label=tool,
        value=version,
        detail=detail,
    )


async def scan(project_path: Path, emit: ScanCallback) -> int:
    """Scan for CLI tools, emit ScanUpdate events. Return item count."""
    results = await asyncio.gather(*[_detect_tool(tool) for tool in TOOLS])

    count = 0
    for result in results:
        if result is not None:
            await emit(result)
            count += 1

    return count
