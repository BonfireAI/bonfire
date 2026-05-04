# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""GitWorkflow — async subprocess wrappers for common git operations.

Auto-prefixes branch names with ``bonfire/`` unless already prefixed. All
ref-accepting operations validate against dash-prefixed names to prevent git
flag injection. Filename arguments are passed after a ``--`` separator for
the same reason.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

BRANCH_PREFIX = "bonfire/"


def _validate_ref_name(name: str) -> None:
    """Reject ref names that could be interpreted as git flags.

    Raises ValueError if *name* starts with ``-`` (could be parsed as a
    git option).
    """
    if name.startswith("-"):
        raise ValueError(
            f"Invalid ref name '{name}': must not start with '-' "
            "(could be interpreted as a git flag)"
        )


async def _run_git(repo_path: Path, *args: str) -> str:
    """Run a git command and return stdout. Raise RuntimeError on failure."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(repo_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"git command failed (exit {proc.returncode}): "
            f"git {' '.join(args)}\n{stderr.decode().strip()}"
        )
    return stdout.decode().strip()


class GitWorkflow:
    """Thin async wrapper around the git CLI."""

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    async def current_branch(self) -> str:
        """Return the name of the current branch."""
        return await _run_git(self._repo, "rev-parse", "--abbrev-ref", "HEAD")

    async def rev_parse(self, ref: str) -> str:
        """Return the full 40-character SHA the given ref resolves to.

        Pure passthrough to ``git rev-parse <ref>`` with the ref-flag guard
        applied. Raises ``ValueError`` if the ref starts with ``-`` (flag
        injection); raises ``RuntimeError`` if ``git`` returns non-zero
        (unknown ref, malformed repo, etc.).
        """
        _validate_ref_name(ref)
        return await _run_git(self._repo, "rev-parse", ref)

    async def create_branch(
        self, name: str, *, base: str | None = None, checkout: bool = True
    ) -> None:
        """Create a new branch, optionally checking it out (default: yes).

        Auto-prefixes with ``bonfire/`` unless already prefixed.
        Raises ValueError if the name could be interpreted as a git flag.
        """
        _validate_ref_name(name)
        if not name.startswith(BRANCH_PREFIX):
            name = f"{BRANCH_PREFIX}{name}"

        if checkout:
            cmd: list[str] = ["checkout", "-b", name]
            if base is not None:
                cmd.append(base)
            await _run_git(self._repo, *cmd)
        else:
            cmd = ["branch", name]
            if base is not None:
                cmd.append(base)
            await _run_git(self._repo, *cmd)

    async def checkout(self, name: str) -> None:
        """Switch to an existing branch.

        Raises ValueError if *name* starts with ``-``.
        """
        _validate_ref_name(name)
        await _run_git(self._repo, "checkout", name)

    async def list_branches(self) -> list[str]:
        """Return a list of local branch names."""
        raw = await _run_git(self._repo, "branch", "--format=%(refname:short)")
        return [b for b in raw.splitlines() if b]

    async def delete_branch(self, name: str, *, force: bool = False) -> None:
        """Delete a local branch. Raises RuntimeError if it's the current branch.

        Raises ValueError if *name* starts with ``-``.
        """
        _validate_ref_name(name)
        current = await self.current_branch()
        if name == current:
            raise RuntimeError(f"Cannot delete '{name}': it is the current branch.")
        flag = "-D" if force else "-d"
        await _run_git(self._repo, "branch", flag, name)

    # ------------------------------------------------------------------
    # Staging & commit
    # ------------------------------------------------------------------

    async def has_uncommitted_changes(self) -> bool:
        """Return True if the working tree or index has uncommitted changes."""
        status = await _run_git(self._repo, "status", "--porcelain")
        return len(status) > 0

    async def add(self, paths: list[str] | None = None) -> None:
        """Stage files. If *paths* is omitted, stages everything (``git add -A``).

        Uses ``--`` separator before paths to prevent flag injection from
        filenames starting with ``-``.
        """
        if paths:
            await _run_git(self._repo, "add", "--", *paths)
        else:
            await _run_git(self._repo, "add", "-A")

    async def commit(self, message: str, *, paths: list[str] | None = None) -> str:
        """Stage (optionally) and commit. Returns the full SHA.

        If *paths* is given, those paths are staged before committing.
        Raises RuntimeError when there is nothing to commit.
        """
        if paths:
            await _run_git(self._repo, "add", "--", *paths)

        # Check for staged changes
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--cached",
            "--quiet",
            cwd=str(self._repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            raise RuntimeError("Nothing to commit — no staged changes.")

        await _run_git(self._repo, "commit", "-m", message)
        sha = await _run_git(self._repo, "rev-parse", "HEAD")
        return sha

    # ------------------------------------------------------------------
    # Status, diff & log
    # ------------------------------------------------------------------

    async def status(self) -> str:
        """Return the output of ``git status --short``."""
        return await _run_git(self._repo, "status", "--short")

    async def diff(self, *, staged: bool = False) -> str:
        """Return the diff output. Use *staged=True* for ``--cached``."""
        cmd = ["diff"]
        if staged:
            cmd.append("--cached")
        return await _run_git(self._repo, *cmd)

    async def log(self, *, n: int = 10) -> list[str]:
        """Return the last *n* one-line log entries.

        Raises ValueError if *n* is not a positive integer.
        """
        if n < 1:
            raise ValueError(f"log count must be positive, got {n}")
        raw = await _run_git(self._repo, "log", f"-{n}", "--oneline")
        return [line for line in raw.splitlines() if line]

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    async def push(self, *, remote: str = "origin", branch: str | None = None) -> None:
        """Push current branch. Never force-pushes."""
        if branch is None:
            branch = await self.current_branch()
        await _run_git(self._repo, "push", remote, branch)
