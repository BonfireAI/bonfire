"""Tests for bonfire.git — PathGuard, GitWorkflow, WorktreeContext, WorktreeManager.

Knight-A (innovative lens). Baseline private-mirror coverage plus an
adversarial-lens class (``TestInnovativeGitEdge``) attacking the security seam:
flag injection on ref names, ``..`` traversal variants (Unix/Windows/URL-encoded),
symlink resolution in ``make_relative``, Unicode/control-character branch names,
concurrent worktree operations, and filename-injection via ``add``/``commit``
paths that start with ``-``.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

# Module-level imports are deferred into try/except so that pytest can still
# collect individual tests while the public-v0.1 implementation is stubbed.
# Each test (and fixture) that uses a name imports it directly, so RED output
# shows ImportError per-test rather than a single collection error.

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
# PathGuard
# ===========================================================================


class TestPathGuard:
    """PathGuard detects absolute paths and ``..`` traversal in agent output."""

    def test_finds_unix_home_path(self) -> None:
        paths = PathGuard.find_absolute_paths("edit /home/user/file.py now")
        assert "/home/user/file.py" in paths

    def test_finds_tmp_path(self) -> None:
        paths = PathGuard.find_absolute_paths("write to /tmp/scratch/out.txt")
        assert "/tmp/scratch/out.txt" in paths

    def test_finds_windows_drive_path(self) -> None:
        paths = PathGuard.find_absolute_paths(r"see C:\Users\Alice\file.py")
        assert r"C:\Users\Alice\file.py" in paths

    def test_ignores_relative_path(self) -> None:
        assert PathGuard.find_absolute_paths("src/bonfire/mod.py tests/unit/x.py") == []

    def test_ignores_https_url(self) -> None:
        """URLs like https:// must not be classified as absolute paths."""
        assert PathGuard.find_absolute_paths("https://github.com/foo/bar") == []

    def test_ignores_ftp_url(self) -> None:
        assert PathGuard.find_absolute_paths("ftp://example.com/files") == []

    def test_contains_absolute_paths_true(self) -> None:
        assert PathGuard.contains_absolute_paths("cd /home/ishtar/Projects") is True

    def test_contains_absolute_paths_false(self) -> None:
        assert PathGuard.contains_absolute_paths("no paths here") is False

    def test_find_absolute_paths_deduplicates(self) -> None:
        text = "cp /tmp/a.txt /tmp/b.txt && mv /tmp/a.txt /tmp/c.txt"
        result = PathGuard.find_absolute_paths(text)
        # /tmp/a.txt appears twice but must be listed once
        assert result.count("/tmp/a.txt") == 1

    def test_find_absolute_paths_preserves_first_occurrence_order(self) -> None:
        text = "first /home/a/x.py then /tmp/b/y.py"
        result = PathGuard.find_absolute_paths(text)
        assert result.index("/home/a/x.py") < result.index("/tmp/b/y.py")

    def test_find_absolute_paths_empty_string(self) -> None:
        assert PathGuard.find_absolute_paths("") == []

    def test_is_traversal_unix(self) -> None:
        assert PathGuard.is_traversal("../secret") is True

    def test_is_traversal_nested(self) -> None:
        assert PathGuard.is_traversal("foo/../../etc/passwd") is True

    def test_is_traversal_windows(self) -> None:
        assert PathGuard.is_traversal(r"foo\..\bar") is True

    def test_is_traversal_url_encoded(self) -> None:
        """URL-encoded ``%2e%2e`` must be detected as traversal."""
        assert PathGuard.is_traversal("files/%2e%2e/etc") is True

    def test_is_traversal_no_dots(self) -> None:
        assert PathGuard.is_traversal("normal/path") is False

    def test_is_traversal_only_dots_no_separator(self) -> None:
        """A literal ``..`` with separators on either side is traversal."""
        assert PathGuard.is_traversal("../x") is True

    def test_make_relative_inside_root(self, tmp_path: Path) -> None:
        target = tmp_path / "src" / "m.py"
        target.parent.mkdir()
        target.write_text("")
        result = PathGuard.make_relative(str(target), tmp_path)
        assert result == str(Path("src") / "m.py")

    def test_make_relative_outside_root_raises(self, tmp_path: Path) -> None:
        # A path that is NOT under tmp_path
        other = tmp_path.parent / "not-under-root"
        with pytest.raises(ValueError, match="outside the project root"):
            PathGuard.make_relative(str(other), tmp_path)

    def test_make_relative_equal_to_root_is_dot(self, tmp_path: Path) -> None:
        assert PathGuard.make_relative(str(tmp_path), tmp_path) == "."

    def test_isolation_violation_frozen(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=1, severity="error")
        with pytest.raises((AttributeError, Exception)):
            v.path = "/other"  # type: ignore[misc]

    def test_isolation_violation_fields(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=3, severity="warning")
        assert v.path == "/tmp/x"
        assert v.line_number == 3
        assert v.severity == "warning"

    def test_path_guard_error_carries_violations(self) -> None:
        v = IsolationViolation(path="/tmp/x", line_number=None, severity="error")
        err = PathGuardError("blocked", [v])
        assert err.violations == [v]
        assert "blocked" in str(err)

    def test_sanitize_prompt_paths_replaces_in_root(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("")
        text = f"edit {target} please"
        result = sanitize_prompt_paths(text, tmp_path)
        assert str(target) not in result
        assert "mod.py" in result

    def test_sanitize_prompt_paths_leaves_external_paths(self, tmp_path: Path) -> None:
        """Paths outside project_root are left unchanged (cannot safely relativize)."""
        external = "/etc/passwd"
        text = f"read {external}"
        result = sanitize_prompt_paths(text, tmp_path)
        assert external in result


# ===========================================================================
# GitWorkflow — branch operations
# ===========================================================================


class TestGitWorkflow:
    async def test_current_branch(self, git_workflow: GitWorkflow) -> None:
        branch = await git_workflow.current_branch()
        assert branch == "main"

    async def test_create_branch_explicit_prefix(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("bonfire/test-feature")
        assert await git_workflow.current_branch() == "bonfire/test-feature"

    async def test_create_branch_auto_prefix(self, git_workflow: GitWorkflow) -> None:
        await git_workflow.create_branch("my-feature")
        assert await git_workflow.current_branch() == "bonfire/my-feature"

    async def test_create_branch_already_prefixed_not_doubled(
        self, git_workflow: GitWorkflow
    ) -> None:
        await git_workflow.create_branch("bonfire/already")
        assert await git_workflow.current_branch() == "bonfire/already"

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
        status = await git_workflow.status()
        assert "dirty.txt" in status

    async def test_diff(self, git_workflow: GitWorkflow, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "README.md").write_text("# changed\n")
        diff = await git_workflow.diff()
        assert "changed" in diff

    async def test_log(self, git_workflow: GitWorkflow) -> None:
        entries = await git_workflow.log(n=1)
        assert len(entries) == 1
        assert "initial" in entries[0]

    async def test_log_default_limit(self, git_workflow: GitWorkflow) -> None:
        entries = await git_workflow.log()
        assert len(entries) >= 1

    async def test_log_rejects_zero(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.log(n=0)

    async def test_log_rejects_negative(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.log(n=-5)

    async def test_non_repo_raises(self, tmp_path: Path) -> None:
        wf = GitWorkflow(repo_path=tmp_path)
        with pytest.raises(RuntimeError):
            await wf.current_branch()

    async def test_push_no_remote_raises(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(RuntimeError):
            await git_workflow.push()


# ===========================================================================
# WorktreeInfo, WorktreeContext, WorktreeManager
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


class TestWorktreeManager:
    def test_worktree_info_frozen(self) -> None:
        info = WorktreeInfo(path=Path("/tmp/wt"), branch="bonfire/x")
        with pytest.raises((AttributeError, Exception)):
            info.path = Path("/other")  # type: ignore[misc]

    def test_worktree_info_fields(self) -> None:
        info = WorktreeInfo(path=Path("/tmp/wt"), branch="bonfire/x")
        assert info.path == Path("/tmp/wt")
        assert info.branch == "bonfire/x"

    async def test_create_worktree(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        info = await worktree_mgr.create("bonfire/wt-test")
        assert info.branch == "bonfire/wt-test"
        assert info.path.exists()
        assert ".bonfire-worktrees" in str(info.path)

    async def test_worktree_path_under_repo(
        self, worktree_mgr: WorktreeManager, tmp_git_repo: Path
    ) -> None:
        info = await worktree_mgr.create("bonfire/rel-test")
        assert str(info.path).startswith(str(tmp_git_repo))

    async def test_list_worktrees(self, worktree_mgr: WorktreeManager, tmp_git_repo: Path) -> None:
        await worktree_mgr.create("bonfire/list-test")
        worktrees = await worktree_mgr.list()
        assert len(worktrees) >= 2

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
# Innovative / adversarial-lens edge cases
# ===========================================================================


class TestInnovativeGitEdge:
    """Attack surfaces a security-minded adversary would probe.

    Covers flag injection on every ref-accepting method, ``..`` traversal
    variants, symlink resolution in ``make_relative``, Unicode / control
    characters in branch names, concurrent worktree creation, filename
    injection via ``add`` / ``commit`` paths, absolute-path rejection in
    ``WorktreeManager.create``, and PathGuard dedup determinism under
    pathological input.
    """

    # ---------- Flag-injection guards on ref-accepting methods ----------

    async def test_create_branch_rejects_flag_injection(self, git_workflow: GitWorkflow) -> None:
        """``--force`` as a branch name must NOT be parsed as a git flag."""
        with pytest.raises(ValueError):
            await git_workflow.create_branch("--force")

    async def test_create_branch_rejects_dash_d(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.create_branch("-D")

    async def test_checkout_rejects_flag_injection(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.checkout("--orphan")

    async def test_delete_branch_rejects_flag_injection(self, git_workflow: GitWorkflow) -> None:
        with pytest.raises(ValueError):
            await git_workflow.delete_branch("--all")

    async def test_rev_parse_rejects_flag_injection(self, git_workflow: GitWorkflow) -> None:
        """``rev_parse`` on a dash-prefixed ref is rejected BEFORE git sees it."""
        with pytest.raises(ValueError):
            await git_workflow.rev_parse("--stdin")

    async def test_worktree_create_rejects_flag_injection(
        self, worktree_mgr: WorktreeManager
    ) -> None:
        with pytest.raises(ValueError):
            await worktree_mgr.create("--no-checkout")

    # ---------- Filename injection via add/commit paths ----------

    async def test_add_with_dash_filename_is_not_flag(
        self, git_workflow: GitWorkflow, tmp_git_repo: Path
    ) -> None:
        """A file literally named ``-evil`` must be added as a file, not a flag.

        The implementation uses ``--`` before paths; this test pins that contract.
        """
        evil = tmp_git_repo / "-evil"
        evil.write_text("x\n")
        # Should not raise (the -- separator makes this safe)
        await git_workflow.add(["-evil"])
        status = await git_workflow.status()
        assert "-evil" in status

    async def test_commit_with_dash_path_is_not_flag(
        self, git_workflow: GitWorkflow, tmp_git_repo: Path
    ) -> None:
        evil = tmp_git_repo / "-weird.txt"
        evil.write_text("x\n")
        sha = await git_workflow.commit("add dash file", paths=["-weird.txt"])
        assert len(sha) == 40

    # ---------- PathGuard traversal / path-escape ----------

    def test_path_guard_detects_url_encoded_mixed_case(self) -> None:
        """``%2E%2E`` (uppercase) must also trip traversal detection."""
        assert PathGuard.is_traversal("x/%2E%2E/y") is True

    def test_path_guard_detects_dot_dot_at_start(self) -> None:
        assert PathGuard.is_traversal("../../etc/passwd") is True

    def test_path_guard_ignores_file_with_dots_in_name(self) -> None:
        """``my.file.py`` has dots but no ``..`` component — not traversal."""
        assert PathGuard.is_traversal("src/my.file.py") is False

    def test_path_guard_absolute_path_escape_via_home(self) -> None:
        """An adversary embedding ``/home/attacker/../../root/.ssh`` in output."""
        text = "please read /home/attacker/../../root/.ssh/id_rsa"
        paths = PathGuard.find_absolute_paths(text)
        # The unix-anchor regex stops at whitespace; the escape attempt is caught
        assert any(p.startswith("/home/") for p in paths)

    def test_make_relative_resolves_symlink_outside_root(self, tmp_path: Path) -> None:
        """A symlink that escapes project_root must raise ValueError."""
        outside = tmp_path.parent / "outside_root"
        outside.mkdir(exist_ok=True)
        try:
            link = tmp_path / "escape"
            link.symlink_to(outside)
            with pytest.raises(ValueError, match="outside"):
                PathGuard.make_relative(str(link / "x"), tmp_path)
        finally:
            if outside.exists():
                try:
                    outside.rmdir()
                except OSError:
                    pass

    # ---------- Unicode / control characters in branch names ----------

    async def test_create_branch_rejects_newline(self, git_workflow: GitWorkflow) -> None:
        """A newline in a branch name is a git-refname violation and MUST raise."""
        # git itself rejects refs containing newlines; this guarantees we surface
        # the failure as an exception (not silent pass) on the public contract.
        with pytest.raises((ValueError, RuntimeError)):
            await git_workflow.create_branch("evil\nmain")

    async def test_create_branch_accepts_unicode_identifier(
        self, git_workflow: GitWorkflow
    ) -> None:
        """Non-ASCII identifier characters that git permits must round-trip."""
        await git_workflow.create_branch("fixé")
        # Auto-prefix applied, branch exists
        current = await git_workflow.current_branch()
        assert current == "bonfire/fixé"

    # ---------- Concurrent worktree operations ----------

    async def test_concurrent_worktree_creation_unique_paths(
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

    # ---------- PathGuard dedup determinism ----------

    def test_find_absolute_paths_many_duplicates_stable_order(self) -> None:
        """Under pathological repetition, order of first occurrence is preserved."""
        text = " ".join(["/tmp/a.txt"] * 5 + ["/tmp/b.txt"] * 5 + ["/tmp/a.txt"])
        result = PathGuard.find_absolute_paths(text)
        assert result == ["/tmp/a.txt", "/tmp/b.txt"]

    # ---------- Exports ----------

    def test_exports_are_re_exported_from_package(self) -> None:
        """Public API: package-level imports must work."""
        import bonfire.git as g

        assert g.GitWorkflow is GitWorkflow
        assert g.WorktreeManager is WorktreeManager
        assert g.WorktreeContext is WorktreeContext
        assert g.WorktreeInfo is WorktreeInfo
        assert g.PathGuard is PathGuard
        assert g.IsolationViolation is IsolationViolation
        assert g.PathGuardError is PathGuardError
