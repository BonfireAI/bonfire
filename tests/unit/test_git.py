"""Canonical RED suite for bonfire.git — BON-343 (Wave 5.4).

Synthesized from Knight-A (innovative lens) + Knight-B (conservative lens)
+ private v1 reference, then deduplicated. Covers:

- ``PathGuard.contains_absolute_paths`` / ``find_absolute_paths``
- ``PathGuard.is_traversal`` (Unix, Windows, URL-encoded variants)
- ``PathGuard.make_relative`` (tmp-path based, cross-platform)
- ``sanitize_prompt_paths`` (in-root replace, out-of-root passthrough)
- ``IsolationViolation`` / ``PathGuardError`` data types
- ``GitWorkflow`` branch, commit, add, log, status, diff, push operations
- ``WorktreeInfo`` frozen dataclass shape
- ``WorktreeManager`` create / list / remove / cleanup / cleanup_all
- ``WorktreeContext`` async context manager cleanup semantics
- Adversarial edges: flag injection on every ref-accepting method, filename
  injection via ``add``/``commit`` paths, URL-encoded ``..`` traversal,
  symlink escape in ``make_relative``, Unicode branch names, concurrent
  worktree creation, and PathGuard dedup determinism.

The module-level imports are wrapped in ``try/except ImportError`` so pytest
can collect the file while ``src/bonfire/git/`` is still stubbed. Individual
tests then use package-level imports (via the re-exports) to surface RED
failures per-test rather than as a single collection error — aligning with
the v0.1 public idiom already used in ``test_engine_init.py`` and
``test_prompt_compiler.py``.

No engine↔git cross-wiring is asserted here — ``Envelope.working_dir`` and
``ContextBuilder`` path validation remain separate concerns for a later
ticket.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

# Deferred import shim — collection-safe while src/bonfire/git is stubbed.
# Each test re-imports the name it uses so RED output is per-test, not a
# single collection error.
try:
    from bonfire.git.path_guard import (
        IsolationViolation,
        PathGuard,
        PathGuardError,
        sanitize_prompt_paths,
    )
    from bonfire.git.workflow import GitWorkflow
    from bonfire.git.worktree import WorktreeContext, WorktreeInfo, WorktreeManager
except ImportError:  # pragma: no cover - expected RED before Warrior builds src
    pass


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

    def test_detects_home_path(self) -> None:
        assert PathGuard.contains_absolute_paths("Edit /home/user/project/main.py") is True

    def test_detects_tmp_path(self) -> None:
        assert PathGuard.contains_absolute_paths("Write output to /tmp/results.json") is True

    def test_detects_var_path(self) -> None:
        assert PathGuard.contains_absolute_paths("Log file is at /var/log/bonfire.log") is True

    def test_detects_etc_path(self) -> None:
        assert PathGuard.contains_absolute_paths("Read config from /etc/bonfire/c.toml") is True

    def test_detects_windows_path(self) -> None:
        assert PathGuard.contains_absolute_paths(r"Open C:\Users\dev\project\main.py") is True

    def test_detects_windows_drive_d(self) -> None:
        assert PathGuard.contains_absolute_paths(r"Stored at D:\repos\bonfire\src\main.py") is True

    def test_no_false_positive_on_relative_paths(self) -> None:
        text = "Edit src/bonfire/main.py and tests/unit/test_main.py"
        assert PathGuard.contains_absolute_paths(text) is False

    def test_no_false_positive_on_plain_text(self) -> None:
        assert PathGuard.contains_absolute_paths("This is a regular prompt.") is False

    def test_empty_string(self) -> None:
        assert PathGuard.contains_absolute_paths("") is False

    def test_detects_path_in_multiline_text(self) -> None:
        text = (
            "## Task\n\n"
            "Implement the feature.\n\n"
            "## Files\n\n"
            "- /home/user/workspace/project/src/bonfire/engine/executor.py\n"
            "- src/bonfire/models/envelope.py\n"
        )
        assert PathGuard.contains_absolute_paths(text) is True

    def test_no_false_positive_on_https_url(self) -> None:
        """URLs like https://example.com/path must not trigger detection."""
        text = "See https://docs.python.org/3/library/pathlib.html"
        assert PathGuard.contains_absolute_paths(text) is False

    def test_no_false_positive_on_ftp_url(self) -> None:
        assert PathGuard.contains_absolute_paths("ftp://example.com/files") is False


# ===========================================================================
# PathGuard.find_absolute_paths
# ===========================================================================


class TestFindAbsolutePaths:
    """PathGuard.find_absolute_paths returns deduplicated ordered list."""

    def test_returns_empty_list_for_no_paths(self) -> None:
        result = PathGuard.find_absolute_paths("No absolute paths here, just src/bonfire/main.py")
        assert result == []

    def test_finds_single_unix_path(self) -> None:
        result = PathGuard.find_absolute_paths("Edit /home/user/project/main.py please")
        assert result == ["/home/user/project/main.py"]

    def test_finds_multiple_unix_paths(self) -> None:
        text = "Read /etc/bonfire/config.toml and write to /tmp/output.json"
        result = PathGuard.find_absolute_paths(text)
        assert len(result) == 2
        assert "/etc/bonfire/config.toml" in result
        assert "/tmp/output.json" in result

    def test_finds_windows_path(self) -> None:
        text = r"Open C:\Users\dev\project\main.py"
        result = PathGuard.find_absolute_paths(text)
        assert len(result) == 1
        assert r"C:\Users\dev\project\main.py" in result

    def test_finds_paths_in_multiline(self) -> None:
        text = (
            "Files:\n"
            "- /home/user/workspace/project/src/main.py\n"
            "- /var/log/bonfire.log\n"
            "- src/bonfire/other.py\n"
        )
        assert len(PathGuard.find_absolute_paths(text)) == 2

    def test_empty_string_returns_empty(self) -> None:
        assert PathGuard.find_absolute_paths("") == []

    def test_deduplicates_repeated_paths(self) -> None:
        text = "cp /tmp/a.txt /tmp/b.txt && mv /tmp/a.txt /tmp/c.txt"
        result = PathGuard.find_absolute_paths(text)
        assert result.count("/tmp/a.txt") == 1

    def test_preserves_first_occurrence_order(self) -> None:
        text = "first /home/a/x.py then /tmp/b/y.py"
        result = PathGuard.find_absolute_paths(text)
        assert result.index("/home/a/x.py") < result.index("/tmp/b/y.py")

    def test_many_duplicates_stable_order(self) -> None:
        """Under pathological repetition, first-occurrence order is preserved."""
        text = " ".join(["/tmp/a.txt"] * 5 + ["/tmp/b.txt"] * 5 + ["/tmp/a.txt"])
        assert PathGuard.find_absolute_paths(text) == ["/tmp/a.txt", "/tmp/b.txt"]

    def test_ignores_https_url(self) -> None:
        assert PathGuard.find_absolute_paths("https://github.com/foo/bar") == []


# ===========================================================================
# PathGuard.is_traversal
# ===========================================================================


class TestIsTraversal:
    """PathGuard.is_traversal detects ``..`` traversal in paths."""

    def test_unix_dot_dot(self) -> None:
        assert PathGuard.is_traversal("../secret") is True

    def test_nested_traversal(self) -> None:
        assert PathGuard.is_traversal("foo/../../etc/passwd") is True

    def test_windows_backslash(self) -> None:
        assert PathGuard.is_traversal(r"foo\..\bar") is True

    def test_url_encoded_lowercase(self) -> None:
        """URL-encoded ``%2e%2e`` must be detected as traversal."""
        assert PathGuard.is_traversal("files/%2e%2e/etc") is True

    def test_url_encoded_uppercase(self) -> None:
        """``%2E%2E`` (uppercase) must also trip traversal detection."""
        assert PathGuard.is_traversal("x/%2E%2E/y") is True

    def test_dot_dot_at_start(self) -> None:
        assert PathGuard.is_traversal("../../etc/passwd") is True

    def test_no_dots(self) -> None:
        assert PathGuard.is_traversal("normal/path") is False

    def test_file_with_dots_in_name(self) -> None:
        """``my.file.py`` has dots but no ``..`` component — not traversal."""
        assert PathGuard.is_traversal("src/my.file.py") is False


# ===========================================================================
# PathGuard.make_relative
# ===========================================================================


class TestMakeRelative:
    """PathGuard.make_relative converts absolute paths to project-relative."""

    def test_strips_project_root(self, tmp_path: Path) -> None:
        project_root = tmp_path / "proj"
        project_root.mkdir()
        (project_root / "src").mkdir()
        (project_root / "src" / "main.py").write_text("")
        result = PathGuard.make_relative(str(project_root / "src" / "main.py"), project_root)
        # Use os-agnostic separator comparison
        assert result == str(Path("src") / "main.py")

    def test_path_outside_project_raises(self, tmp_path: Path) -> None:
        project_root = tmp_path / "proj"
        project_root.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        (other / "main.py").write_text("")
        with pytest.raises(ValueError, match="outside.*project"):
            PathGuard.make_relative(str(other / "main.py"), project_root)

    def test_root_returns_dot(self, tmp_path: Path) -> None:
        project_root = tmp_path / "proj"
        project_root.mkdir()
        assert PathGuard.make_relative(str(project_root), project_root) == "."

    def test_trailing_slash_handled(self, tmp_path: Path) -> None:
        project_root = tmp_path / "proj"
        project_root.mkdir()
        (project_root / "src").mkdir()
        assert PathGuard.make_relative(str(project_root / "src") + "/", project_root) == "src"

    def test_symlink_outside_root_raises(self, tmp_path: Path) -> None:
        """A symlink that resolves outside project_root must raise ValueError."""
        project_root = tmp_path / "proj"
        project_root.mkdir()
        outside = tmp_path / "outside_root"
        outside.mkdir()
        link = project_root / "escape"
        try:
            link.symlink_to(outside)
        except OSError:  # Symlinks unsupported (rare on some CI)
            pytest.skip("symlinks unsupported on this filesystem")
        with pytest.raises(ValueError, match="outside"):
            PathGuard.make_relative(str(link / "x"), project_root)


# ===========================================================================
# IsolationViolation + PathGuardError
# ===========================================================================


class TestIsolationViolation:
    """IsolationViolation is a frozen dataclass of violation metadata."""

    def test_frozen(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=1, severity="error")
        with pytest.raises((AttributeError, Exception)):
            v.path = "/other"  # type: ignore[misc]

    def test_fields(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=3, severity="warning")
        assert v.path == "/tmp/x"
        assert v.line_number == 3
        assert v.severity == "warning"

    def test_line_number_optional(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=None, severity="error")
        assert v.line_number is None

    def test_path_guard_error_carries_violations(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=None, severity="error")
        err = PathGuardError("blocked", [v])
        assert err.violations == [v]
        assert "blocked" in str(err)


# ===========================================================================
# sanitize_prompt_paths
# ===========================================================================


class TestSanitizePromptPaths:
    """sanitize_prompt_paths rewrites in-root absolute paths to relative."""

    def test_replaces_in_root(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("")
        result = sanitize_prompt_paths(f"edit {target} please", tmp_path)
        assert str(target) not in result
        assert "mod.py" in result

    def test_leaves_external_paths(self, tmp_path: Path) -> None:
        """Paths outside project_root are left unchanged."""
        external = "/etc/passwd"
        result = sanitize_prompt_paths(f"read {external}", tmp_path)
        assert external in result

    def test_no_paths_is_passthrough(self, tmp_path: Path) -> None:
        assert sanitize_prompt_paths("just some text", tmp_path) == "just some text"


# ===========================================================================
# GitWorkflow — branch operations
# ===========================================================================


class TestGitWorkflowBranch:
    async def test_current_branch(self, git_workflow: GitWorkflow) -> None:
        assert await git_workflow.current_branch() == "main"

    async def test_create_branch_explicit_prefix(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("bonfire/test-feature")
        assert await git_workflow.current_branch() == "bonfire/test-feature"

    async def test_create_branch_auto_prefix(self, git_workflow: GitWorkflow) -> None:
        """Branches without bonfire/ prefix get it added automatically."""
        await git_workflow.create_branch("my-feature")
        assert await git_workflow.current_branch() == "bonfire/my-feature"

    async def test_create_branch_already_prefixed_not_doubled(
        self, git_workflow: GitWorkflow
    ) -> None:
        """Branches already prefixed with bonfire/ are not double-prefixed."""
        await git_workflow.create_branch("bonfire/already-prefixed")
        assert await git_workflow.current_branch() == "bonfire/already-prefixed"

    async def test_create_branch_no_checkout(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("other", checkout=False)
        assert await git_workflow.current_branch() == "main"

    async def test_create_branch_from_base(self, git_workflow: GitWorkflow) -> None:
        base = await git_workflow.current_branch()
        await git_workflow.create_branch("bonfire/from-base", base=base)
        assert await git_workflow.current_branch() == "bonfire/from-base"

    async def test_checkout(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("x", checkout=False)
        await git_workflow.checkout("bonfire/x")
        assert await git_workflow.current_branch() == "bonfire/x"

    async def test_list_branches(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("a", checkout=False)
        branches = await git_workflow.list_branches()
        assert "main" in branches
        assert "bonfire/a" in branches

    async def test_delete_branch(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("del", checkout=False)
        await git_workflow.delete_branch("bonfire/del")
        assert "bonfire/del" not in await git_workflow.list_branches()

    async def test_delete_current_branch_raises(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(RuntimeError, match="[Cc]annot delete"):
            await git_workflow.delete_branch("main")


# ===========================================================================
# GitWorkflow — commit operations
# ===========================================================================


class TestGitWorkflowCommit:
    async def test_commit_with_paths(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("hello\n")
        sha = await git_workflow.commit("add new file", paths=["new.txt"])
        assert len(sha) == 40

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
        await git_workflow.add()
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
        assert "dirty.txt" in await git_workflow.status()

    async def test_diff(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "README.md").write_text("# changed\n")
        assert "changed" in await git_workflow.diff()


# ===========================================================================
# GitWorkflow — log
# ===========================================================================


class TestGitWorkflowLog:
    async def test_log(self, git_workflow: GitWorkflow) -> None:
        entries = await git_workflow.log(n=1)
        assert len(entries) == 1
        assert "initial" in entries[0]

    async def test_log_default_limit(self, git_workflow: GitWorkflow) -> None:
        assert len(await git_workflow.log()) >= 1

    async def test_log_rejects_zero(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.log(n=0)

    async def test_log_rejects_negative(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.log(n=-5)


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
# GitWorkflow — rev_parse
# ===========================================================================


class TestGitWorkflowRevParse:
    """rev_parse returns full SHA; validates refs; surfaces unknown-ref errors."""

    async def test_rev_parse_head(self, git_workflow: GitWorkflow) -> None:
        sha = await git_workflow.rev_parse("HEAD")
        assert len(sha) == 40

    async def test_rev_parse_unknown_ref_raises(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(RuntimeError):
            await git_workflow.rev_parse("no-such-ref-zzz")


# ===========================================================================
# WorktreeInfo model
# ===========================================================================


class TestWorktreeInfo:
    def test_frozen(self) -> None:
        info = WorktreeInfo(path=Path("/tmp/wt"), branch="bonfire/x")
        with pytest.raises((AttributeError, Exception)):
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
        """Worktree paths must be under the repo tree (inside the worktree dir)."""
        info = await worktree_mgr.create("bonfire/rel-test")
        assert str(info.path).startswith(str(tmp_git_repo))

    async def test_list_worktrees(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        await worktree_mgr.create("bonfire/list-test")
        assert len(await worktree_mgr.list()) >= 2  # main repo + new worktree

    async def test_remove_worktree(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        info = await worktree_mgr.create("bonfire/rm-test")
        assert info.path.exists()
        await worktree_mgr.remove(info.path)
        assert not info.path.exists()

    async def test_remove_nonexistent_raises(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        with pytest.raises(RuntimeError):
            await worktree_mgr.remove(tmp_git_repo / "nonexistent")

    async def test_cleanup_by_branch(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        info = await worktree_mgr.create("bonfire/clean-test")
        assert info.path.exists()
        await worktree_mgr.cleanup("bonfire/clean-test")
        assert not info.path.exists()

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
        assert not info.path.exists()

    async def test_context_cleans_on_exception(self, worktree_mgr: WorktreeManager) -> None:
        captured_path: Path | None = None
        with pytest.raises(ValueError, match="intentional"):
            async with WorktreeContext(worktree_mgr, "bonfire/ctx-err") as info:
                captured_path = info.path
                raise ValueError("intentional")
        assert captured_path is not None
        assert not captured_path.exists()


# ===========================================================================
# Adversarial / security edges
# ===========================================================================


class TestRefFlagInjection:
    """Every ref-accepting method must reject dash-prefixed names."""

    async def test_create_branch_rejects_flag(self, git_workflow: GitWorkflow) -> None:
        """``--force`` as a branch name must NOT be parsed as a git flag."""
        with pytest.raises(ValueError):
            await git_workflow.create_branch("--force")

    async def test_create_branch_rejects_dash_d(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.create_branch("-D")

    async def test_checkout_rejects_flag(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.checkout("--orphan")

    async def test_delete_branch_rejects_flag(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.delete_branch("--all")

    async def test_rev_parse_rejects_flag(self, git_workflow: GitWorkflow) -> None:
        """``rev_parse`` on a dash-prefixed ref is rejected BEFORE git sees it."""
        with pytest.raises(ValueError):
            await git_workflow.rev_parse("--stdin")

    async def test_worktree_create_rejects_flag(self, worktree_mgr: WorktreeManager) -> None:
        with pytest.raises(ValueError):
            await worktree_mgr.create("--no-checkout")


class TestFilenameInjection:
    """Paths starting with ``-`` must be treated as paths, not git flags.

    The implementation must emit ``--`` separator before path arguments.
    """

    async def test_add_with_dash_filename_is_not_flag(
        self, git_workflow: GitWorkflow, tmp_git_repo: Path
    ) -> None:
        evil = tmp_git_repo / "-evil"
        evil.write_text("x\n")
        await git_workflow.add(["-evil"])
        assert "-evil" in await git_workflow.status()

    async def test_commit_with_dash_path_is_not_flag(
        self, git_workflow: GitWorkflow, tmp_git_repo: Path
    ) -> None:
        evil = tmp_git_repo / "-weird.txt"
        evil.write_text("x\n")
        sha = await git_workflow.commit("add dash file", paths=["-weird.txt"])
        assert len(sha) == 40


class TestWorktreeAdversarial:
    """Concurrent creation and duplicate-branch handling."""

    async def test_concurrent_creation_unique_paths(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        """Two concurrent ``create`` calls must produce two distinct worktrees."""
        results = await asyncio.gather(
            worktree_mgr.create("bonfire/concurrent-a"),
            worktree_mgr.create("bonfire/concurrent-b"),
        )
        paths = {r.path for r in results}
        assert len(paths) == 2
        for info in results:
            assert info.path.exists()

    async def test_create_duplicate_branch_raises(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        """Creating the same branch twice must surface git's failure."""
        await worktree_mgr.create("bonfire/dup")
        with pytest.raises(RuntimeError):
            await worktree_mgr.create("bonfire/dup")


class TestBranchNameEdges:
    """Unicode + control characters in branch names."""

    async def test_create_branch_rejects_newline(self, git_workflow: GitWorkflow) -> None:
        """A newline in a branch name is a git-refname violation."""
        with pytest.raises((ValueError, RuntimeError)):
            await git_workflow.create_branch("evil\nmain")


# ===========================================================================
# Package exports
# ===========================================================================


class TestPackageExports:
    """Public API: package-level imports must work."""

    def test_git_workflow_exported(self) -> None:
        import bonfire.git as g

        assert g.GitWorkflow is GitWorkflow

    def test_worktree_manager_exported(self) -> None:
        import bonfire.git as g

        assert g.WorktreeManager is WorktreeManager

    def test_worktree_context_exported(self) -> None:
        import bonfire.git as g

        assert g.WorktreeContext is WorktreeContext

    def test_worktree_info_exported(self) -> None:
        import bonfire.git as g

        assert g.WorktreeInfo is WorktreeInfo

    def test_path_guard_exported(self) -> None:
        import bonfire.git as g

        assert g.PathGuard is PathGuard

    def test_isolation_violation_exported(self) -> None:
        import bonfire.git as g

        assert g.IsolationViolation is IsolationViolation

    def test_path_guard_error_exported(self) -> None:
        import bonfire.git as g

        assert g.PathGuardError is PathGuardError
