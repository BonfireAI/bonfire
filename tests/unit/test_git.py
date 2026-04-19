"""Tests for bonfire.git — PathGuard, GitWorkflow, WorktreeManager, WorktreeContext.

Conservative Knight (BON-343): mirrors the established coverage of the private
reference implementation. Covers:

- ``PathGuard.contains_absolute_paths`` / ``find_absolute_paths`` / ``make_relative``
- ``GitWorkflow`` branch, commit, log, and error operations
- ``WorktreeInfo`` frozen dataclass shape
- ``WorktreeManager`` create / list / remove / cleanup / cleanup_all
- ``WorktreeContext`` async context manager cleanup semantics

No engine↔git cross-wiring is asserted here — that wiring is a separate concern
and is deliberately omitted from the public v0.1 transfer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bonfire.git.path_guard import PathGuard
from bonfire.git.workflow import GitWorkflow
from bonfire.git.worktree import WorktreeContext, WorktreeInfo, WorktreeManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""

    def _run(*cmd: str) -> None:
        subprocess.run(cmd, cwd=str(tmp_path), check=True, capture_output=True)

    _run("git", "init", "-b", "main")
    _run("git", "config", "user.email", "test@test.com")
    _run("git", "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("# test\n")
    _run("git", "add", ".")
    _run("git", "commit", "-m", "initial")
    return tmp_path


@pytest.fixture()
def git_workflow(tmp_git_repo: Path) -> GitWorkflow:
    return GitWorkflow(repo_path=tmp_git_repo)


@pytest.fixture()
def worktree_mgr(tmp_git_repo: Path) -> WorktreeManager:
    return WorktreeManager(repo_path=tmp_git_repo)


# ===========================================================================
# PathGuard.contains_absolute_paths
# ===========================================================================


class TestContainsAbsolutePaths:
    """PathGuard.contains_absolute_paths detects absolute paths in text."""

    def test_detects_home_path(self):
        text = "Edit the file at /home/user/project/main.py"
        assert PathGuard.contains_absolute_paths(text) is True

    def test_detects_tmp_path(self):
        text = "Write output to /tmp/results.json"
        assert PathGuard.contains_absolute_paths(text) is True

    def test_detects_var_path(self):
        text = "Log file is at /var/log/bonfire.log"
        assert PathGuard.contains_absolute_paths(text) is True

    def test_detects_etc_path(self):
        text = "Read config from /etc/bonfire/config.toml"
        assert PathGuard.contains_absolute_paths(text) is True

    def test_detects_windows_path(self):
        text = r"Open C:\Users\dev\project\main.py"
        assert PathGuard.contains_absolute_paths(text) is True

    def test_detects_windows_drive_d(self):
        text = r"Stored at D:\repos\bonfire\src\main.py"
        assert PathGuard.contains_absolute_paths(text) is True

    def test_no_false_positive_on_relative_paths(self):
        text = "Edit src/bonfire/main.py and tests/unit/test_main.py"
        assert PathGuard.contains_absolute_paths(text) is False

    def test_no_false_positive_on_plain_text(self):
        text = "This is a regular prompt with no paths at all."
        assert PathGuard.contains_absolute_paths(text) is False

    def test_empty_string(self):
        text = ""
        assert PathGuard.contains_absolute_paths(text) is False

    def test_detects_path_in_multiline_text(self):
        text = (
            "## Task\n\n"
            "Implement the feature.\n\n"
            "## Files\n\n"
            "- /home/user/workspace/project/src/bonfire/engine/executor.py\n"
            "- src/bonfire/models/envelope.py\n"
        )
        assert PathGuard.contains_absolute_paths(text) is True

    def test_no_false_positive_on_url(self):
        """URLs like https://example.com/path should not trigger detection."""
        text = "See https://docs.python.org/3/library/pathlib.html"
        assert PathGuard.contains_absolute_paths(text) is False


# ===========================================================================
# PathGuard.find_absolute_paths
# ===========================================================================


class TestFindAbsolutePaths:
    """PathGuard.find_absolute_paths returns all absolute paths found in text."""

    def test_returns_empty_list_for_no_paths(self):
        text = "No absolute paths here, just src/bonfire/main.py"
        result = PathGuard.find_absolute_paths(text)
        assert result == []

    def test_finds_single_unix_path(self):
        text = "Edit /home/user/project/main.py please"
        result = PathGuard.find_absolute_paths(text)
        assert result == ["/home/user/project/main.py"]

    def test_finds_multiple_unix_paths(self):
        text = "Read /etc/bonfire/config.toml and write to /tmp/output.json"
        result = PathGuard.find_absolute_paths(text)
        assert len(result) == 2
        assert "/etc/bonfire/config.toml" in result
        assert "/tmp/output.json" in result

    def test_finds_windows_path(self):
        text = r"Open C:\Users\dev\project\main.py"
        result = PathGuard.find_absolute_paths(text)
        assert len(result) == 1
        assert r"C:\Users\dev\project\main.py" in result

    def test_finds_paths_in_multiline(self):
        text = (
            "Files:\n"
            "- /home/user/workspace/project/src/main.py\n"
            "- /var/log/bonfire.log\n"
            "- src/bonfire/other.py\n"
        )
        result = PathGuard.find_absolute_paths(text)
        assert len(result) == 2

    def test_empty_string_returns_empty(self):
        assert PathGuard.find_absolute_paths("") == []


# ===========================================================================
# PathGuard.make_relative
# ===========================================================================


class TestMakeRelative:
    """PathGuard.make_relative converts absolute paths to project-relative."""

    def test_strips_project_root(self, tmp_path: Path):
        project_root = tmp_path / "proj"
        project_root.mkdir()
        (project_root / "src").mkdir()
        (project_root / "src" / "main.py").write_text("")
        absolute = str(project_root / "src" / "main.py")
        result = PathGuard.make_relative(absolute, project_root)
        assert result == "src/main.py"

    def test_path_outside_project_raises(self, tmp_path: Path):
        project_root = tmp_path / "proj"
        project_root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        (other / "main.py").write_text("")
        absolute = str(other / "main.py")
        with pytest.raises(ValueError, match="outside.*project"):
            PathGuard.make_relative(absolute, project_root)

    def test_root_returns_dot(self, tmp_path: Path):
        project_root = tmp_path / "proj"
        project_root.mkdir()
        absolute = str(project_root)
        result = PathGuard.make_relative(absolute, project_root)
        assert result == "."

    def test_trailing_slash_handled(self, tmp_path: Path):
        project_root = tmp_path / "proj"
        project_root.mkdir()
        (project_root / "src").mkdir()
        absolute = str(project_root / "src") + "/"
        result = PathGuard.make_relative(absolute, project_root)
        assert result == "src"


# ===========================================================================
# GitWorkflow — branch operations
# ===========================================================================


class TestGitWorkflowBranch:
    async def test_current_branch(self, git_workflow: GitWorkflow) -> None:
        branch = await git_workflow.current_branch()
        assert branch == "main"

    async def test_create_branch(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("bonfire/test-feature")
        branch = await git_workflow.current_branch()
        assert branch == "bonfire/test-feature"

    async def test_create_branch_auto_prefix(self, git_workflow: GitWorkflow) -> None:
        """Branches without bonfire/ prefix get it added automatically."""
        await git_workflow.create_branch("my-feature")
        branch = await git_workflow.current_branch()
        assert branch == "bonfire/my-feature"

    async def test_create_branch_already_prefixed(self, git_workflow: GitWorkflow) -> None:
        """Branches already prefixed with bonfire/ are not double-prefixed."""
        await git_workflow.create_branch("bonfire/already-prefixed")
        branch = await git_workflow.current_branch()
        assert branch == "bonfire/already-prefixed"

    async def test_create_branch_no_checkout(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("other", checkout=False)
        branch = await git_workflow.current_branch()
        assert branch == "main"  # stayed on main

    async def test_create_branch_from_base(self, git_workflow: GitWorkflow) -> None:
        """Can create branch from a specific base."""
        base = await git_workflow.current_branch()
        await git_workflow.create_branch("bonfire/from-base", base=base)
        branch = await git_workflow.current_branch()
        assert branch == "bonfire/from-base"

    async def test_checkout(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("x", checkout=False)
        await git_workflow.checkout("bonfire/x")
        branch = await git_workflow.current_branch()
        assert branch == "bonfire/x"

    async def test_list_branches(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("a", checkout=False)
        branches = await git_workflow.list_branches()
        assert "main" in branches
        assert "bonfire/a" in branches

    async def test_delete_branch(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("del", checkout=False)
        await git_workflow.delete_branch("bonfire/del")
        branches = await git_workflow.list_branches()
        assert "bonfire/del" not in branches

    async def test_delete_current_branch_raises(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(RuntimeError, match="Cannot delete.*current"):
            await git_workflow.delete_branch("main")


# ===========================================================================
# GitWorkflow — commit operations
# ===========================================================================


class TestGitWorkflowCommit:
    async def test_commit_with_paths(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("hello\n")
        sha = await git_workflow.commit("add new file", paths=["new.txt"])
        assert len(sha) == 40  # full SHA

    async def test_commit_staged(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "staged.txt").write_text("staged\n")
        await git_workflow.add(["staged.txt"])
        sha = await git_workflow.commit("commit staged")
        assert len(sha) == 40

    async def test_commit_nothing_staged_raises(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(RuntimeError, match="[Nn]othing"):
            await git_workflow.commit("empty commit")

    async def test_add_all(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "a.txt").write_text("a\n")
        (tmp_git_repo / "b.txt").write_text("b\n")
        await git_workflow.add()  # no paths = add all
        sha = await git_workflow.commit("add all")
        assert len(sha) == 40

    async def test_has_uncommitted_changes_clean(self, git_workflow: GitWorkflow) -> None:
        assert await git_workflow.has_uncommitted_changes() is False

    async def test_has_uncommitted_changes_dirty(
        self, git_workflow: GitWorkflow, tmp_git_repo: Path
    ) -> None:
        (tmp_git_repo / "dirty.txt").write_text("dirty\n")
        assert await git_workflow.has_uncommitted_changes() is True

    async def test_status(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "dirty.txt").write_text("dirty\n")
        status = await git_workflow.status()
        assert "dirty.txt" in status

    async def test_diff(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        readme = tmp_git_repo / "README.md"
        readme.write_text("# changed\n")
        diff = await git_workflow.diff()
        assert "changed" in diff


# ===========================================================================
# GitWorkflow — log
# ===========================================================================


class TestGitWorkflowLog:
    async def test_log(self, git_workflow: GitWorkflow) -> None:
        entries = await git_workflow.log(n=1)
        assert len(entries) == 1
        assert "initial" in entries[0]

    async def test_log_default_limit(self, git_workflow: GitWorkflow) -> None:
        entries = await git_workflow.log()
        assert len(entries) >= 1


# ===========================================================================
# GitWorkflow — error handling
# ===========================================================================


class TestGitWorkflowErrors:
    async def test_bad_git_command_raises(self, tmp_git_repo: Path) -> None:
        from bonfire.git.workflow import _run_git

        with pytest.raises(RuntimeError):
            await _run_git(tmp_git_repo, "not-a-real-command")

    async def test_non_repo_raises(self, tmp_path: Path) -> None:
        wf = GitWorkflow(repo_path=tmp_path)
        with pytest.raises(RuntimeError):
            await wf.current_branch()

    async def test_push_no_remote_raises(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(RuntimeError):
            await git_workflow.push()


# ===========================================================================
# WorktreeInfo model
# ===========================================================================


class TestWorktreeInfo:
    def test_frozen(self) -> None:
        info = WorktreeInfo(path=Path("/tmp/wt"), branch="bonfire/x")
        with pytest.raises(AttributeError):  # frozen dataclass
            info.path = Path("/other")  # type: ignore[misc]

    def test_fields(self) -> None:
        info = WorktreeInfo(path=Path("/tmp/wt"), branch="bonfire/x")
        assert info.path == Path("/tmp/wt")
        assert info.branch == "bonfire/x"


# ===========================================================================
# WorktreeManager
# ===========================================================================


class TestWorktreeManager:
    async def test_create_worktree(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        info = await worktree_mgr.create("bonfire/wt-test")
        assert info.branch == "bonfire/wt-test"
        assert info.path.exists()
        assert ".bonfire-worktrees" in str(info.path)

    async def test_worktree_path_under_repo(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        """Worktree paths must be relative to repo root (inside repo tree)."""
        info = await worktree_mgr.create("bonfire/rel-test")
        assert str(info.path).startswith(str(tmp_git_repo))

    async def test_list_worktrees(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        await worktree_mgr.create("bonfire/list-test")
        worktrees = await worktree_mgr.list()
        # At least 2: main repo + the new worktree
        assert len(worktrees) >= 2

    async def test_remove_worktree(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        info = await worktree_mgr.create("bonfire/rm-test")
        wt_path = info.path
        assert wt_path.exists()
        await worktree_mgr.remove(wt_path)
        assert not wt_path.exists()

    async def test_remove_nonexistent_raises(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        fake = tmp_git_repo / "nonexistent"
        with pytest.raises(RuntimeError):
            await worktree_mgr.remove(fake)

    async def test_cleanup_by_branch(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        info = await worktree_mgr.create("bonfire/clean-test")
        wt_path = info.path
        assert wt_path.exists()
        await worktree_mgr.cleanup("bonfire/clean-test")
        assert not wt_path.exists()

    async def test_cleanup_nonexistent_raises(self, worktree_mgr: WorktreeManager) -> None:
        with pytest.raises(RuntimeError, match="No worktree"):
            await worktree_mgr.cleanup("bonfire/does-not-exist")

    async def test_cleanup_all(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        await worktree_mgr.create("bonfire/all-1")
        await worktree_mgr.create("bonfire/all-2")
        await worktree_mgr.cleanup_all()
        active = await worktree_mgr.list()
        bonfire_branches = [wt.branch for wt in active if wt.branch.startswith("bonfire/")]
        assert len(bonfire_branches) == 0


# ===========================================================================
# WorktreeContext
# ===========================================================================


class TestWorktreeContext:
    async def test_context_creates_and_cleans(self, worktree_mgr: WorktreeManager) -> None:
        async with WorktreeContext(worktree_mgr, "bonfire/ctx-test") as info:
            assert info.path.exists()
            assert info.branch == "bonfire/ctx-test"
        # After exit, worktree should be cleaned up
        assert not info.path.exists()

    async def test_context_cleans_on_exception(self, worktree_mgr: WorktreeManager) -> None:
        with pytest.raises(ValueError, match="intentional"):
            async with WorktreeContext(worktree_mgr, "bonfire/ctx-err") as info:
                wt_path = info.path
                raise ValueError("intentional")
        assert not wt_path.exists()
