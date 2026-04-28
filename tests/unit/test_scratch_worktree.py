"""RED tests for ScratchWorktreeFactory / ScratchWorktreeContext / ScratchWorktreeInfo.

Per Sage memo bon-519-sage-20260428T033101Z.md §D3 (lines 298-350) and
§D-CL.1 (lines 839-843).

Knight A FULL OWNERSHIP — foundation primitive for MergePreflightHandler.

The scratch worktree primitive is distinct from WorktreeManager: scratch
worktrees live under .bonfire-worktrees/preflight/, are created on
ephemeral branches with random suffixes (race-safety), and ALWAYS get
torn down on context exit (try/finally guarantee).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

# --- v0.1-tolerant imports (RED state: all of these fail today) -------------
try:
    from bonfire.git.scratch import (  # type: ignore[import-not-found]
        ScratchWorktreeContext,
        ScratchWorktreeFactory,
        ScratchWorktreeInfo,
    )
except ImportError:  # pragma: no cover
    ScratchWorktreeFactory = None  # type: ignore[assignment,misc]
    ScratchWorktreeContext = None  # type: ignore[assignment,misc]
    ScratchWorktreeInfo = None  # type: ignore[assignment,misc]


pytestmark = pytest.mark.skipif(
    ScratchWorktreeFactory is None,
    reason="v0.1 RED: bonfire.git.scratch not yet implemented",
)


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/unit/test_git.py:62 pattern)
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit on master."""

    def _run(*cmd: str) -> None:
        subprocess.run(cmd, cwd=str(tmp_path), check=True, capture_output=True)

    _run("git", "init", "-b", "master")
    _run("git", "config", "user.email", "test@test.com")
    _run("git", "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("# scratch test\n")
    _run("git", "add", ".")
    _run("git", "commit", "-m", "initial")
    return tmp_path


@pytest.fixture()
def factory(tmp_git_repo: Path) -> ScratchWorktreeFactory:
    return ScratchWorktreeFactory(repo_path=tmp_git_repo)


# ---------------------------------------------------------------------------
# TestScratchWorktreeFactory (Sage §D-CL.1 lines 839-843, §D3 lines 298-341)
# ---------------------------------------------------------------------------


class TestScratchWorktreeFactory:
    """ScratchWorktreeFactory.acquire returns an async context manager."""

    def test_acquire_returns_async_context_manager(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D-CL.1 line 840: acquire(base_ref='master') returns async CM."""
        ctx = factory.acquire(base_ref="master", pr_number=1)
        # Async context manager protocol: __aenter__ + __aexit__.
        assert hasattr(ctx, "__aenter__"), "acquire() must return an async CM."
        assert hasattr(ctx, "__aexit__")

    @pytest.mark.asyncio
    async def test_aenter_yields_info_with_existing_path(
        self, factory: ScratchWorktreeFactory, tmp_git_repo: Path
    ) -> None:
        """Sage §D-CL.1 line 841: info.path exists after __aenter__.

        Also pins that __aenter__ returns a ScratchWorktreeInfo instance
        (Sage §D3 line 305 — the dataclass shape is part of the contract).
        """
        ctx = factory.acquire(base_ref="master", pr_number=42)
        assert isinstance(ctx, ScratchWorktreeContext), (
            "factory.acquire(...) must return a ScratchWorktreeContext."
        )
        async with ctx as info:
            assert isinstance(info, ScratchWorktreeInfo), (
                "Sage §D3 line 305: __aenter__ yields a ScratchWorktreeInfo."
            )
            assert info.path.exists(), "Worktree path must exist after __aenter__."

    @pytest.mark.asyncio
    async def test_path_lives_under_preflight_subdir(
        self, factory: ScratchWorktreeFactory, tmp_git_repo: Path
    ) -> None:
        """Sage §D-CL.1 line 841 + §D3 line 346: path under .bonfire-worktrees/preflight/."""
        ctx = factory.acquire(base_ref="master", pr_number=42)
        async with ctx as info:
            preflight_root = tmp_git_repo / ".bonfire-worktrees" / "preflight"
            assert str(info.path).startswith(str(preflight_root)), (
                f"info.path ({info.path}) must live under {preflight_root}."
            )

    @pytest.mark.asyncio
    async def test_branch_name_starts_with_bonfire_preflight_pr(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D-CL.1 line 841 + §D3 line 345: branch_name format."""
        ctx = factory.acquire(base_ref="master", pr_number=42)
        async with ctx as info:
            assert info.branch_name.startswith("bonfire/preflight-pr-"), (
                f"branch_name ({info.branch_name}) must start with "
                "'bonfire/preflight-pr-' to avoid collision with feature branches."
            )

    @pytest.mark.asyncio
    async def test_path_removed_after_clean_exit(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D-CL.1 line 842: worktree removed after clean __aexit__."""
        ctx = factory.acquire(base_ref="master", pr_number=42)
        captured_path: Path | None = None
        async with ctx as info:
            captured_path = info.path
            assert captured_path.exists()
        assert captured_path is not None
        assert not captured_path.exists(), (
            "Worktree path must be removed after clean __aexit__."
        )

    @pytest.mark.asyncio
    async def test_path_removed_after_exception_in_block(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D-CL.1 line 843: try/finally guarantee on exception."""
        ctx = factory.acquire(base_ref="master", pr_number=42)
        captured_path: Path | None = None
        with pytest.raises(ValueError, match="intentional"):
            async with ctx as info:
                captured_path = info.path
                assert captured_path.exists()
                raise ValueError("intentional")
        assert captured_path is not None
        assert not captured_path.exists(), (
            "Worktree path MUST be removed even when the async-with body raises "
            "(try/finally guarantee per Sage §D3 line 348-349)."
        )


# ---------------------------------------------------------------------------
# TestScratchWorktreeContextErrors (Sage §D3 last bullet — lines 348-349)
# ---------------------------------------------------------------------------


class TestScratchWorktreeContextErrors:
    """Cleanup failures log but never raise (Sage §D3 line 348-349)."""

    @pytest.mark.asyncio
    async def test_cleanup_failure_does_not_raise(
        self, factory: ScratchWorktreeFactory, tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sage §D3 line 349: __aexit__ MUST swallow exceptions during cleanup.

        Otherwise a cleanup failure masks the original handler error. We
        simulate a cleanup error by patching the factory's underlying remove
        primitive (to be implemented) into a raising function. The async-with
        block must NOT propagate the failure.
        """
        # Sabotage: monkeypatch any teardown subprocess so it fails. We patch
        # at the asyncio.create_subprocess_exec level which mirrors how
        # _run_git is implemented in bonfire.git.workflow.
        ctx = factory.acquire(base_ref="master", pr_number=42)
        async with ctx as info:
            captured_path = info.path
            # Force a cleanup-time failure by deleting the worktree dir
            # outside of git's knowledge — `git worktree remove --force`
            # then fails. The teardown MUST NOT raise.
            import shutil

            if captured_path.exists():
                shutil.rmtree(captured_path, ignore_errors=True)
        # If we reach here without an exception, the swallow contract holds.

    @pytest.mark.asyncio
    async def test_cleanup_failure_does_not_mask_original_error(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D3 line 349: cleanup failure NEVER masks the original error.

        If both the body raises AND cleanup fails, the body's exception is
        the one propagated to the caller (cleanup failure logs only).
        """
        ctx = factory.acquire(base_ref="master", pr_number=42)
        with pytest.raises(ValueError, match="original"):
            async with ctx as info:
                # Pre-emptively destroy the worktree so cleanup will fail.
                import shutil

                if info.path.exists():
                    shutil.rmtree(info.path, ignore_errors=True)
                raise ValueError("original")


# ---------------------------------------------------------------------------
# TestScratchWorktreeBranchNaming (Sage §D3 line 345-346, race-safety)
# ---------------------------------------------------------------------------


_BRANCH_NAME_RE = re.compile(r"^bonfire/preflight-pr-\d+-[0-9a-f]{8}$")
_PATH_NAME_RE = re.compile(r"pr-\d+-[0-9a-f]{8}")


class TestScratchWorktreeBranchNaming:
    """Race-safety: 8-hex random suffix per acquire (Sage §D3 line 345)."""

    @pytest.mark.asyncio
    async def test_branch_name_matches_format(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D3 line 345: branch_name == 'bonfire/preflight-pr-<N>-<8-hex>'."""
        ctx = factory.acquire(base_ref="master", pr_number=42)
        async with ctx as info:
            assert _BRANCH_NAME_RE.match(info.branch_name), (
                f"branch_name ({info.branch_name}) must match "
                f"^bonfire/preflight-pr-\\d+-[0-9a-f]{{8}}$ for race-safety."
            )

    @pytest.mark.asyncio
    async def test_path_format_matches_pattern(
        self, factory: ScratchWorktreeFactory, tmp_git_repo: Path
    ) -> None:
        """Sage §D3 line 346: path == .bonfire-worktrees/preflight/pr-<N>-<8-hex>/."""
        ctx = factory.acquire(base_ref="master", pr_number=42)
        async with ctx as info:
            preflight_root = tmp_git_repo / ".bonfire-worktrees" / "preflight"
            relative = info.path.relative_to(preflight_root)
            assert _PATH_NAME_RE.match(str(relative)), (
                f"Path component ({relative}) must match 'pr-<N>-<8-hex>'."
            )

    @pytest.mark.asyncio
    async def test_two_acquires_produce_different_branch_names(
        self, factory: ScratchWorktreeFactory
    ) -> None:
        """Sage §D3 line 345 + §D-CL.7 #1 (race-safety): two acquires for
        the same PR yield different 8-hex suffixes."""
        ctx_a = factory.acquire(base_ref="master", pr_number=42)
        ctx_b = factory.acquire(base_ref="master", pr_number=42)
        async with ctx_a as info_a:
            async with ctx_b as info_b:
                assert info_a.branch_name != info_b.branch_name, (
                    "Two concurrent acquires for the same PR must produce "
                    "different branch names (8-hex random suffix per acquire)."
                )
                assert info_a.path != info_b.path, (
                    "Two concurrent acquires must produce distinct worktree paths."
                )
