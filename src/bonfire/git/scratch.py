# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Scratch worktree primitive for transient verification.

Distinct from :class:`~bonfire.git.worktree.WorktreeManager`: scratch
worktrees live under ``.bonfire-worktrees/preflight/``, are created on
ephemeral branches with an 8-hex random suffix (race-safety), and ALWAYS
get torn down on context exit (try/finally guarantee).

Contract:
    - Path format:   ``<repo>/.bonfire-worktrees/preflight/pr-<N>-<8-hex>/``
    - Branch format: ``bonfire/preflight-pr-<N>-<8-hex>``
    - Reuses ``_run_git`` from ``bonfire.git.workflow`` (no new subprocess).
    - Reuses ``WORKTREE_DIR`` from ``bonfire.git.worktree``.
    - ``__aexit__`` MUST swallow exceptions during cleanup (logs only).
      Otherwise a cleanup failure masks the original handler error.

This module is the v0.1 primitive for ``MergePreflightHandler``. It does
not depend on the handler module; the handler depends on it.
"""

from __future__ import annotations

import contextlib
import logging
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.git.workflow import _run_git
from bonfire.git.worktree import WORKTREE_DIR

if TYPE_CHECKING:
    from types import TracebackType

__all__ = [
    "PREFLIGHT_DIR_NAME",
    "ScratchWorktreeContext",
    "ScratchWorktreeFactory",
    "ScratchWorktreeInfo",
]

logger = logging.getLogger(__name__)

# Subdirectory under WORKTREE_DIR that holds preflight scratch worktrees.
# Sage §D3 line 346: ``<repo>/.bonfire-worktrees/preflight/pr-<N>-<8-hex>/``.
PREFLIGHT_DIR_NAME: str = "preflight"

_RANDOM_SUFFIX_BYTES: int = 4  # 4 bytes -> 8 hex chars
_NO_PR_NUMBER_TOKEN: str = "0"

# Allow-list regex for ``acquire(prefix=...)``. Hyphen + underscore +
# alphanumerics, 1-32 chars. Same allow-list shape used elsewhere for
# user-controlled identifiers that interpolate into file paths and git
# refs (see ``bonfire.models.events._validate_session_id``). Refuses
# every adversarial shape covered by the W11 M4 audit:
#   ``..`` / ``../foo`` / ``foo/../bar`` — parent-traversal
#   ``foo/bar`` / ``\\``                  — separators
#   ``-leading-dash``                     — git-flag injection
#   ``""``                                — empty
#   ``foo\x00bar`` / ``foo\nbar``         — null + control chars
#   ``foo bar``                           — space (shell-meaningful)
#   ``/abs``                              — leading separator
#   ``.`` / ``..foo``                     — dot segments / leading dot
_PREFIX_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def _validate_prefix(prefix: str) -> None:
    """Reject hostile ``ScratchWorktreeFactory.acquire(prefix=...)`` kwargs.

    The prefix is interpolated into two surfaces:

      * Branch name: ``bonfire/{prefix}-pr-<N>-<8hex>``
      * Filesystem path: ``<repo>/.bonfire-worktrees/{prefix}/pr-<N>-<8hex>/``

    Without validation, a hostile prefix lands the worktree (and its
    ephemeral branch) outside the ``.bonfire-worktrees/`` jail and
    smuggles git-flag-shaped tokens into later ``git`` calls. This
    validator enforces the allow-list shape ``^[a-zA-Z0-9_-]{1,32}$``
    which refuses every adversarial shape covered in the W11 M4
    contract: ``..``, ``/``, ``\\``, leading ``-``, leading ``.``,
    empty, null bytes, control chars, spaces, dots, and length
    overflow.

    Additionally rejects ``-leading-dash`` shapes that the regex above
    already catches but are called out explicitly here so the error
    message names the git-flag-injection concern (parallel to
    :func:`bonfire.git.workflow._validate_ref_name`).
    """
    if not _PREFIX_RE.match(prefix) or prefix.startswith("-"):
        # The leading-``-`` check is layered on top of the regex because
        # the allow-list permits ``-`` mid-token (``valid-prefix``) but
        # MUST refuse it at position 0 — a leading dash on the branch
        # name produces ``bonfire/-...`` which downstream ``git branch``
        # / ``git worktree`` calls interpret as a flag (mirrors the
        # explicit guard in :func:`bonfire.git.workflow._validate_ref_name`).
        msg = (
            f"invalid scratch worktree prefix {prefix!r}: must match "
            f"{_PREFIX_RE.pattern} AND not start with '-' (alphanumerics, "
            "'_', '-'; 1-32 chars; no leading dash). Rejected to prevent "
            "path-traversal escape from .bonfire-worktrees/, git-flag "
            "injection on branch names, and shell-meaningful smuggling "
            "into downstream subprocess calls."
        )
        raise ValueError(msg)


def _new_random_suffix() -> str:
    """Generate an 8-hex random suffix for race-safety (§D-CL.7 #1)."""
    return secrets.token_hex(_RANDOM_SUFFIX_BYTES)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScratchWorktreeInfo:
    """Immutable snapshot of an acquired scratch worktree.

    Per Sage §D3 lines 305-310. Mirrors :class:`WorktreeInfo` but adds
    ``base_sha`` and ``created_at`` for forensic inspection.
    """

    path: Path
    branch_name: str
    base_sha: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class ScratchWorktreeFactory:
    """Creates scratch worktrees for transient verification.

    Per Sage §D3 lines 312-329. The factory is stateless apart from
    ``repo_path``; each :py:meth:`acquire` returns a fresh async context
    manager with its own random branch suffix.
    """

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path

    def acquire(
        self,
        base_ref: str,
        *,
        pr_number: int | None = None,
        prefix: str = PREFLIGHT_DIR_NAME,
    ) -> ScratchWorktreeContext:
        """Return an async context manager for a scratch worktree.

        On ``__aenter__``: creates the worktree at
        ``<repo>/.bonfire-worktrees/<prefix>/pr-<N>-<8hex>/`` checked out
        on a new ephemeral branch ``bonfire/preflight-pr-<N>-<8hex>``.

        On ``__aexit__``: removes the worktree and deletes the ephemeral
        branch. NEVER raises.

        W11 M4: ``_validate_prefix`` rejects hostile ``prefix`` kwargs
        (path-traversal, separators, git-flag-shaped, control chars,
        empty) BEFORE the context is constructed so a malicious caller
        cannot land the worktree outside ``.bonfire-worktrees/`` or
        smuggle git flags into the ephemeral branch name.
        """
        _validate_prefix(prefix)
        return ScratchWorktreeContext(
            repo_path=self._repo,
            base_ref=base_ref,
            pr_number=pr_number,
            prefix=prefix,
        )


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class ScratchWorktreeContext:
    """Async CM: acquire on enter, GUARANTEED teardown on exit.

    Mirrors :class:`~bonfire.git.worktree.WorktreeContext` but writes under
    ``.bonfire-worktrees/preflight/`` and uses ephemeral branch names with
    an 8-hex random suffix.

    Sage §D3 lines 332-349. The teardown swallows cleanup exceptions
    (logs only) so a cleanup failure NEVER masks the original handler
    error -- mirrors :py:meth:`WorktreeManager.cleanup`.
    """

    def __init__(
        self,
        *,
        repo_path: Path,
        base_ref: str,
        pr_number: int | None,
        prefix: str,
    ) -> None:
        self._repo = repo_path
        self._base_ref = base_ref
        self._pr_number = pr_number
        self._prefix = prefix
        self._suffix = _new_random_suffix()
        self._info: ScratchWorktreeInfo | None = None

    # -- naming helpers ------------------------------------------------

    def _pr_token(self) -> str:
        """PR number token used in branch and dir names."""
        if self._pr_number is None:
            return _NO_PR_NUMBER_TOKEN
        return str(self._pr_number)

    def _branch_name(self) -> str:
        """``bonfire/preflight-pr-<N>-<8hex>`` (§D3 line 345)."""
        return f"bonfire/{self._prefix}-pr-{self._pr_token()}-{self._suffix}"

    def _worktree_path(self) -> Path:
        """``<repo>/.bonfire-worktrees/<prefix>/pr-<N>-<8hex>/`` (§D3 line 346)."""
        return self._repo / WORKTREE_DIR / self._prefix / f"pr-{self._pr_token()}-{self._suffix}"

    # -- async CM protocol --------------------------------------------

    async def __aenter__(self) -> ScratchWorktreeInfo:
        wt_path = self._worktree_path()
        branch = self._branch_name()
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        # Capture base SHA BEFORE moving HEAD so the snapshot is meaningful.
        base_sha = await _run_git(self._repo, "rev-parse", self._base_ref)

        # `git worktree add -b <branch> <path> <base_ref>`: creates the
        # ephemeral branch off base_ref AND checks it out at wt_path.
        await _run_git(
            self._repo,
            "worktree",
            "add",
            "-b",
            branch,
            str(wt_path),
            self._base_ref,
        )

        self._info = ScratchWorktreeInfo(
            path=wt_path,
            branch_name=branch,
            base_sha=base_sha,
        )
        return self._info

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Swallow all cleanup exceptions (Sage §D3 lines 348-349).

        Cleanup order (mirrors :py:meth:`WorktreeManager.cleanup`):
            1. ``git worktree remove --force <path>`` (best-effort)
            2. ``shutil.rmtree(path, ignore_errors=True)`` (best-effort)
            3. ``git branch -D <branch>`` (best-effort)

        A failure at any step is logged; control returns normally so the
        original async-with body exception (if any) propagates up.
        """
        info = self._info
        if info is None:
            return None

        # Step 1: best-effort `git worktree remove --force`.
        with contextlib.suppress(Exception):
            await _run_git(
                self._repo,
                "worktree",
                "remove",
                str(info.path),
                "--force",
            )

        # Step 2: best-effort filesystem cleanup if git did not remove it.
        if info.path.exists():
            try:
                shutil.rmtree(info.path, ignore_errors=True)
            except Exception:  # pragma: no cover - belt-and-suspenders
                logger.exception(
                    "scratch.cleanup_rmtree_failed path=%s",
                    info.path,
                )

        # Step 3: best-effort branch delete (§D3 line 348 idiom).
        with contextlib.suppress(Exception):
            await _run_git(self._repo, "branch", "-D", info.branch_name)

        return None
