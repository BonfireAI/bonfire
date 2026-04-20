"""Git integration — branch management, commit flow, worktree isolation."""

from bonfire.git.path_guard import IsolationViolation, PathGuard, PathGuardError
from bonfire.git.workflow import GitWorkflow
from bonfire.git.worktree import WorktreeContext, WorktreeInfo, WorktreeManager

__all__ = [
    "GitWorkflow",
    "IsolationViolation",
    "PathGuard",
    "PathGuardError",
    "WorktreeContext",
    "WorktreeInfo",
    "WorktreeManager",
]
