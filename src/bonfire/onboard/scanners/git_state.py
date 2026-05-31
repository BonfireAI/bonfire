# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Git State Scanner — Reel 4.

Detects git repo state, branches, remotes, uncommitted changes,
last commit date, and GitHub CLI authentication status.

Scanner interface::

    async def scan(project_path: Path, emit: ScanCallback) -> int

All git commands use ``asyncio.create_subprocess_exec`` with a
5-second timeout per command.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ScanCallback, ScanUpdate
from bonfire.timeouts import resolve_timeout

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["sanitize_remote_url", "scan"]

# Module logger. Failures in the git subprocesses are narrated at DEBUG so an
# operator can see why a git fact (branch, remotes, last-commit) went missing
# instead of staring at a silently empty panel. Matches the in-repo idiom in
# bonfire.onboard.scanners.mcp_servers (``_log = logging.getLogger(__name__)``).
_log = logging.getLogger(__name__)

PANEL = "git_state"

# Default per-command git timeout, resolved through the shared resolver
# (``DEFAULT_TIMEOUTS["git"] == 5.0``). Value is identical to the prior
# literal 5.0 — routing it through the resolver standardizes the source of
# truth without changing behavior.
_GIT_TIMEOUT: float = resolve_timeout("git")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_cmd(
    cmd: list[str],
    cwd: Path | str | None = None,
    timeout: float = _GIT_TIMEOUT,
) -> tuple[int, str]:
    """Run a subprocess, return (returncode, stdout_text).

    Returns ``(-1, "")`` on timeout or execution failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            # A hung subprocess: name the subcommand (not the cwd path) so the
            # missing git fact is traceable without leaking filesystem layout.
            _log.debug(
                "git_state: timeout after %.1fs running %r — returning sentinel",
                timeout,
                " ".join(cmd),
            )
            return (-1, "")
        return (proc.returncode, stdout.decode(errors="replace").strip())
    except OSError as exc:
        # The binary could not be launched (missing, not executable, etc.).
        # Narrate the subcommand and the underlying cause so the skipped git
        # fact is visible in the logs instead of vanishing silently.
        _log.debug(
            "git_state: OSError running %r: %s — returning sentinel",
            " ".join(cmd),
            exc,
        )
        return (-1, "")


def sanitize_remote_url(url: str) -> str:
    """Normalize a git remote URL to ``host/path`` format.

    Strips credentials, removes ``.git`` suffix, normalizes SSH to host/path.

    Handles:
    - ``https://user:token@github.com/org/repo.git``
    - ``http://token@github.com/org/repo.git``
    - ``git@github.com:org/repo.git``
    - ``ssh://git@github.com/org/repo.git``
    - ``https://github.com/org/repo.git``
    """
    # Remove credentials from HTTP(S) URLs and normalise to https
    url = re.sub(r"https?://[^@]+@", "https://", url)
    # Normalize ssh://git@host/path to host/path
    url = re.sub(r"ssh://[^@]+@", "", url)
    # Normalize git@host:path to host/path
    url = re.sub(r"^[^@]+@([^:]+):", r"\1/", url)
    # Strip protocol prefix
    url = re.sub(r"^https?://", "", url)
    # Remove .git suffix
    url = re.sub(r"\.git$", "", url)
    return url


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


async def scan(project_path: Path, emit: ScanCallback) -> int:
    """Scan git state and emit ScanUpdate events.

    Returns the total number of items emitted.  If *project_path* is not
    a git repository, returns ``0`` immediately without emitting.
    """
    # Guard: not a git repo
    if not (project_path / ".git").exists():
        return 0

    count = 0

    async def _emit(label: str, value: str, detail: str = "") -> None:
        nonlocal count
        await emit(ScanUpdate(panel=PANEL, label=label, value=value, detail=detail))
        count += 1

    # 1. Repository exists
    await _emit("repository", "initialized")

    # 2. Current branch
    rc, branch = await _run_cmd(
        ["git", "-C", str(project_path), "branch", "--show-current"],
        cwd=project_path,
    )
    if rc == 0 and branch:
        await _emit("branch", branch)

    # 3. Branch count
    rc, branch_list = await _run_cmd(
        ["git", "-C", str(project_path), "branch", "--list"],
        cwd=project_path,
    )
    if rc == 0:
        branches = [line.strip() for line in branch_list.splitlines() if line.strip()]
        if branches:
            await _emit("branches", str(len(branches)))

    # 4. Remote hosts (one event per remote, deduped)
    rc, remote_output = await _run_cmd(
        ["git", "-C", str(project_path), "remote", "-v"],
        cwd=project_path,
    )
    if rc == 0 and remote_output:
        seen_remotes: set[str] = set()
        for line in remote_output.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                url = parts[1]
                if name not in seen_remotes:
                    seen_remotes.add(name)
                    await _emit(name, sanitize_remote_url(url))

    # 5. Uncommitted changes
    rc, status_output = await _run_cmd(
        ["git", "-C", str(project_path), "status", "--porcelain"],
        cwd=project_path,
    )
    if rc == 0:
        if status_output:
            changed = len([line for line in status_output.splitlines() if line.strip()])
            s = "s" if changed != 1 else ""
            await _emit("working tree", "modified", f"{changed} file{s} changed")
        else:
            await _emit("working tree", "clean")

    # 6. Last commit date
    rc, commit_date = await _run_cmd(
        ["git", "-C", str(project_path), "log", "-1", "--format=%ci"],
        cwd=project_path,
    )
    if rc == 0 and commit_date:
        await _emit("last commit", commit_date)

    return count
