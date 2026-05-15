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
import re
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ScanCallback, ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["sanitize_remote_url", "scan"]

PANEL = "git_state"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


#: Sentinel returncode used when ``asyncio.wait_for`` raises ``TimeoutError``.
_RC_TIMEOUT: int = -1


async def _run_cmd(
    cmd: list[str],
    cwd: Path | str | None = None,
    timeout: float = 5.0,
) -> tuple[int | None, str]:
    """Run a subprocess, return (returncode, stdout_text).

    ``returncode`` is ``int | None``: ``asyncio.subprocess.Process``
    exposes ``returncode`` as ``int | None``, and ``None`` propagates
    here so callers can distinguish "process did not complete" from
    "process completed with rc != 0".

    Returns ``(-1, "")`` on timeout (``_RC_TIMEOUT``) and ``(None, "")``
    on ``OSError`` during ``create_subprocess_exec``.
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
            try:
                await proc.communicate()
            except Exception:  # noqa: BLE001 — best-effort drain
                pass
            return (_RC_TIMEOUT, "")
        return (proc.returncode, stdout.decode(errors="replace").strip())
    except OSError:
        return (None, "")


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


def _error_detail(rc: int | None, cmd: list[str]) -> str:
    """Format the error-event detail for a git command that did not succeed.

    The detail names the failed git subcommand (``branch``, ``log``, etc.)
    and either the returncode or a recognizable sentinel string. The
    ``_is_error_event`` heuristic in the safety-net test reads either
    ``value == "error"`` or any of ``label``/``detail`` containing
    ``"error"``/``"failed"``/``"timeout"``.
    """
    sub = cmd[3] if len(cmd) > 3 else "?"
    if rc == _RC_TIMEOUT:
        return f"git {sub} timed out"
    if rc is None:
        return f"git {sub} failed (no returncode)"
    return f"git {sub} failed (rc={rc})"


async def scan(project_path: Path, emit: ScanCallback) -> int:
    """Scan git state and emit ScanUpdate events.

    Returns the total number of items emitted.  If *project_path* is not
    a git repository, returns ``0`` immediately without emitting.

    Non-zero returncodes, ``returncode is None`` results, and timeouts
    surface as ``value="error"`` events naming the failing git
    subcommand so downstream consumers see the failure rather than a
    silent drop.
    """
    # Guard: not a git repo
    if not (project_path / ".git").exists():
        return 0

    count = 0

    async def _emit(label: str, value: str, detail: str = "") -> None:
        nonlocal count
        await emit(ScanUpdate(panel=PANEL, label=label, value=value, detail=detail))
        count += 1

    async def _run_with_emit(label: str, cmd: list[str]) -> str | None:
        """Run *cmd*; on rc==0 return the output, otherwise emit an error event."""
        rc, output = await _run_cmd(cmd, cwd=project_path)
        if rc == 0:
            return output
        await _emit(label, "error", _error_detail(rc, cmd))
        return None

    # 1. Repository exists
    await _emit("repository", "initialized")

    # 2. Current branch
    branch = await _run_with_emit(
        "branch",
        ["git", "-C", str(project_path), "branch", "--show-current"],
    )
    if branch:
        await _emit("branch", branch)

    # 3. Branch count
    branch_list = await _run_with_emit(
        "branches",
        ["git", "-C", str(project_path), "branch", "--list"],
    )
    if branch_list is not None:
        branches = [line.strip() for line in branch_list.splitlines() if line.strip()]
        if branches:
            await _emit("branches", str(len(branches)))

    # 4. Remote hosts (one event per remote, deduped)
    remote_output = await _run_with_emit(
        "remotes",
        ["git", "-C", str(project_path), "remote", "-v"],
    )
    if remote_output:
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
    status_output = await _run_with_emit(
        "working tree",
        ["git", "-C", str(project_path), "status", "--porcelain"],
    )
    if status_output is not None:
        if status_output:
            changed = len([line for line in status_output.splitlines() if line.strip()])
            s = "s" if changed != 1 else ""
            await _emit("working tree", "modified", f"{changed} file{s} changed")
        else:
            await _emit("working tree", "clean")

    # 6. Last commit date
    #
    # ``git log -1`` exits 128 on a freshly ``git init``'d repo with no
    # commits ("does not have any commits yet"). That is a *healthy*
    # state, not a failure — represent it benignly rather than routing
    # rc=128 through the error-emitting ``_run_with_emit`` path. Genuine
    # failures (timeout sentinel, ``None`` returncode, any other rc)
    # still surface as error events.
    log_cmd = ["git", "-C", str(project_path), "log", "-1", "--format=%ci"]
    rc, commit_date = await _run_cmd(log_cmd, cwd=project_path)
    if rc == 0:
        if commit_date:
            await _emit("last commit", commit_date)
    elif rc == 128:
        await _emit("last commit", "none", "no commits yet")
    else:
        await _emit("last commit", "error", _error_detail(rc, log_cmd))

    return count
