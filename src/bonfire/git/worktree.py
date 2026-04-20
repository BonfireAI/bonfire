"""WorktreeManager + WorktreeContext — async worktree lifecycle management.

Worktrees are created under ``.bonfire-worktrees/`` inside the repository.
The context manager guarantees cleanup on exit even when an exception is
raised inside the ``async with`` body.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.git.workflow import _run_git, _validate_ref_name

if TYPE_CHECKING:
    from types import TracebackType

WORKTREE_DIR = ".bonfire-worktrees"


@dataclass(frozen=True)
class WorktreeInfo:
    """Immutable snapshot of a git worktree."""

    path: Path
    branch: str


class WorktreeManager:
    """Manage git worktrees for parallel agent isolation."""

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path

    # ------------------------------------------------------------------
    # Worktree operations
    # ------------------------------------------------------------------

    async def create(self, branch: str) -> WorktreeInfo:
        """Create a new worktree for *branch* under ``.bonfire-worktrees/``.

        The worktree path is always relative to the repo root — enforced
        to avoid absolute-path isolation leaks.

        Raises ValueError if *branch* starts with ``-``.
        """
        _validate_ref_name(branch)
        # Sanitize branch name for directory (replace / with -)
        dir_name = branch.replace("/", "-")
        wt_path = self._repo / WORKTREE_DIR / dir_name
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        await _run_git(self._repo, "worktree", "add", "-b", branch, str(wt_path))

        return WorktreeInfo(path=wt_path, branch=branch)

    async def list(self) -> list[WorktreeInfo]:
        """List all worktrees. Returns WorktreeInfo for each."""
        raw = await _run_git(self._repo, "worktree", "list", "--porcelain")
        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_branch: str = ""

        for line in raw.splitlines():
            if line.startswith("worktree "):
                current_path = Path(line.split(" ", 1)[1])
            elif line.startswith("branch "):
                ref = line.split(" ", 1)[1]
                # refs/heads/bonfire/foo -> bonfire/foo
                current_branch = ref.removeprefix("refs/heads/")
            elif line == "" and current_path is not None:
                worktrees.append(WorktreeInfo(path=current_path, branch=current_branch or "HEAD"))
                current_path = None
                current_branch = ""

        # Handle last entry (porcelain output may not end with blank line)
        if current_path is not None:
            worktrees.append(WorktreeInfo(path=current_path, branch=current_branch or "HEAD"))

        return worktrees

    async def remove(self, path: Path) -> None:
        """Remove a worktree at *path*. Raises RuntimeError if not found."""
        if not path.exists():
            raise RuntimeError(f"Worktree path does not exist: {path}")
        await _run_git(self._repo, "worktree", "remove", str(path), "--force")
        # Clean up remnants if git didn't fully remove
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    async def cleanup(self, branch: str) -> None:
        """Remove a worktree by branch name."""
        active = await self.list()
        match = [wt for wt in active if wt.branch == branch]
        if not match:
            raise RuntimeError(f"No worktree for branch '{branch}'")

        wt = match[0]
        await self.remove(wt.path)

        # Also remove the branch
        with contextlib.suppress(RuntimeError):
            await _run_git(self._repo, "branch", "-D", branch)

    async def cleanup_all(self) -> None:
        """Remove all bonfire-managed worktrees."""
        active = await self.list()
        for wt in active:
            if wt.branch.startswith("bonfire/"):
                await self.cleanup(wt.branch)


class WorktreeContext:
    """Async context manager: creates worktree on enter, cleans up on exit.

    Usage::

        mgr = WorktreeManager(repo_path)
        async with WorktreeContext(mgr, "bonfire/my-feature") as info:
            # info.path is the worktree directory
            ...
        # worktree is automatically removed after the block
    """

    def __init__(self, manager: WorktreeManager, branch: str) -> None:
        self._mgr = manager
        self._branch = branch
        self._info: WorktreeInfo | None = None

    async def __aenter__(self) -> WorktreeInfo:
        self._info = await self._mgr.create(self._branch)
        return self._info

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._info is not None:
            await self._mgr.cleanup(self._branch)
