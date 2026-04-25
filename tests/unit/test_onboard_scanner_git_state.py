"""RED tests for bonfire.onboard.scanners.git_state — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 17 tests per Sage §D6 Row 6. Verbatim v1 port. No innovations (conservative lens).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(path, *, commit: bool = True) -> None:
    """Initialise a real git repo at *path* with optional first commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    if commit:
        (path / "init.txt").write_text("hello")
        subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    return [c.args[0] for c in emit.call_args_list]


def _find(events: list[ScanUpdate], label: str) -> ScanUpdate | None:
    return next((e for e in events if e.label == label), None)


# ---------------------------------------------------------------------------
# Core git detection
# ---------------------------------------------------------------------------


class TestGitRepoDetection:
    """Scanner detects whether path is a git repository."""

    async def test_detects_git_repo(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        count = await scan(tmp_path, emit)

        assert count >= 1
        events = _events(emit)
        repo_event = _find(events, "repository")
        assert repo_event is not None
        assert repo_event.value == "initialized"

    async def test_non_git_directory_returns_zero(self, tmp_path) -> None:
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        count = await scan(tmp_path, emit)

        assert count == 0
        emit.assert_not_called()


# ---------------------------------------------------------------------------
# Panel name
# ---------------------------------------------------------------------------


class TestPanelName:
    """Every event has panel='git_state'."""

    async def test_panel_is_always_git_state(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        assert len(events) > 0
        assert all(e.panel == "git_state" for e in events)


# ---------------------------------------------------------------------------
# Branch detection
# ---------------------------------------------------------------------------


class TestBranchDetection:
    """Scanner reports current branch and branch count."""

    async def test_reports_current_branch(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        branch_event = _find(events, "branch")
        assert branch_event is not None
        # Default branch is typically "main" or "master"
        assert branch_event.value in ("main", "master")

    async def test_reports_branch_count(self, tmp_path) -> None:
        _git_init(tmp_path)
        # Create an extra branch
        subprocess.run(
            ["git", "-C", str(tmp_path), "branch", "feature"],
            check=True,
            capture_output=True,
        )
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        branches_event = _find(events, "branches")
        assert branches_event is not None
        assert branches_event.value == "2"


# ---------------------------------------------------------------------------
# Remote detection + URL sanitization
# ---------------------------------------------------------------------------


class TestRemoteDetection:
    """Scanner reports remotes with sanitized URLs."""

    async def test_reports_remote(self, tmp_path) -> None:
        _git_init(tmp_path)
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "remote",
                "add",
                "origin",
                "https://github.com/org/repo.git",
            ],
            check=True,
            capture_output=True,
        )
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        origin_event = _find(events, "origin")
        assert origin_event is not None
        assert origin_event.value == "github.com/org/repo"

    async def test_no_remotes_emits_nothing_for_remotes(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        # Should not have any remote-specific labels (no "origin" etc.)
        remote_labels = {"origin", "upstream"}
        assert not any(e.label in remote_labels for e in events)


# ---------------------------------------------------------------------------
# URL sanitization (unit tests for the function)
# ---------------------------------------------------------------------------


class TestSanitizeRemoteUrl:
    """Direct tests for sanitize_remote_url."""

    def test_sanitize_https_with_token(self) -> None:
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url("https://user:ghp_abc123@github.com/org/repo.git")
        assert result == "github.com/org/repo"

    def test_sanitize_ssh(self) -> None:
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url("git@github.com:org/repo.git")
        assert result == "github.com/org/repo"

    def test_sanitize_ssh_protocol(self) -> None:
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url("ssh://git@github.com/org/repo.git")
        assert result == "github.com/org/repo"

    def test_sanitize_plain_https(self) -> None:
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url("https://github.com/org/repo.git")
        assert result == "github.com/org/repo"

    def test_sanitize_no_git_suffix(self) -> None:
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url("https://github.com/org/repo")
        assert result == "github.com/org/repo"

    def test_sanitize_http_with_credentials(self) -> None:
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url("http://token@github.com/org/repo.git")
        assert result == "github.com/org/repo"


# ---------------------------------------------------------------------------
# Uncommitted changes
# ---------------------------------------------------------------------------


class TestUncommittedChanges:
    """Scanner reports working tree state."""

    async def test_clean_working_tree(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        wt_event = _find(events, "working tree")
        assert wt_event is not None
        assert wt_event.value == "clean"

    async def test_modified_working_tree(self, tmp_path) -> None:
        _git_init(tmp_path)
        (tmp_path / "new_file.txt").write_text("dirty")
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        wt_event = _find(events, "working tree")
        assert wt_event is not None
        assert wt_event.value == "modified"
        assert "1" in wt_event.detail
        assert "file" in wt_event.detail


# ---------------------------------------------------------------------------
# Last commit
# ---------------------------------------------------------------------------


class TestLastCommit:
    """Scanner reports last commit date."""

    async def test_reports_last_commit_date(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        await scan(tmp_path, emit)

        events = _events(emit)
        commit_event = _find(events, "last commit")
        assert commit_event is not None
        # Should contain a date-like string (at minimum a year)
        assert "20" in commit_event.value  # e.g., 2026-...


# ---------------------------------------------------------------------------
# GitHub CLI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Count consistency
# ---------------------------------------------------------------------------


class TestCountConsistency:
    """Return value matches number of emitted events."""

    async def test_count_matches_emitted_events(self, tmp_path) -> None:
        _git_init(tmp_path)
        emit = AsyncMock()
        from bonfire.onboard.scanners.git_state import scan

        count = await scan(tmp_path, emit)

        assert count == emit.call_count
        assert count > 0
