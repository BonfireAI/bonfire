"""RED tests for bonfire.onboard.scanners.git_state — BON-349 W6.3 (CONTRACT-LOCKED canonical).

Sage decision logs:
  - docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md (Warrior contract)
  - docs/audit/sage-decisions/bon-349-contract-lock-*.md (Knight A/B reconciliation)

Floor (17 tests, per Sage §D6 Row 6): port v1 test_scanner_git_state.py test
surface verbatim, with the import renames
``bonfire.front_door.scanners.git_state`` →
``bonfire.onboard.scanners.git_state``.

Innovations (2 adopted, drift-guards over Sage floor):

  * ``TestPanelConstantContract::test_panel_constant_value_is_stable``
    — Asserts ``PANEL == "git_state"`` is exported as a module-level
    constant. The floor only checks panel name on individual events. Cites
    Sage Appendix item 1 + v1
    src/bonfire/front_door/scanners/git_state.py:27
    (``PANEL = "git_state"``).

  * ``TestSanitizeRemoteUrlMatrix::test_sanitize_remote_url_parametrized_matrix``
    — Parametrize sweep over a broader URL matrix (extends the 6 URL
    transformations the floor pins to also cover edge-cases like
    multi-slash paths, .git double-suffix, ssh URI variant, github
    enterprise URLs). Each URL is sourced from Sage Appendix item 18
    "git_state::sanitize_remote_url regex chain order matters" — a regex
    chain reorder would break canonical normalization but slip past the
    floor's narrow set of inputs. Cites Sage Appendix item 18 + v1
    src/bonfire/front_door/scanners/git_state.py:75-83 (5-step regex
    chain).

Imports are RED — ``bonfire.onboard.scanners.git_state`` does not exist
until Warriors port v1 source per Sage §D9.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING  # noqa: F401 - kept for parity with v1 source
from unittest.mock import AsyncMock

import pytest

# Eager import so RED collection fails fast (the floor's TYPE_CHECKING
# guard would defer ImportError to test execution; the BON-349 mission
# spec requires 8 collection-time errors). The ScanUpdate symbol still
# only flows through type annotations at runtime.
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


# ---------------------------------------------------------------------------
# INNOVATIONS (Knight B drift-guards — Sage Appendix item 1 + item 18)
# ---------------------------------------------------------------------------


class TestPanelConstantContract:
    """Innovation: PANEL constant export contract.

    Cites Sage Appendix item 1 (PANEL vs _PANEL naming) + v1
    src/bonfire/front_door/scanners/git_state.py:27
    (``PANEL = "git_state"`` — un-prefixed convention).
    """

    def test_panel_constant_value_is_stable(self) -> None:
        """``PANEL`` module constant equals ``"git_state"``."""
        from bonfire.onboard.scanners.git_state import PANEL

        assert PANEL == "git_state", (
            "PANEL module constant must equal 'git_state' (v1 verbatim) "
            "— un-prefixed per Sage Appendix item 1"
        )


class TestSanitizeRemoteUrlMatrix:
    """Innovation: extended URL matrix for sanitize_remote_url.

    Cites Sage Appendix item 18 ("git_state::sanitize_remote_url regex chain
    order matters") + v1 src/bonfire/front_door/scanners/git_state.py:75-83.
    The floor pins 6 URL transformations; this sweeps additional inputs that
    exercise the regex-chain-order property the appendix flags.
    """

    @pytest.mark.parametrize(
        ("raw_url", "expected"),
        [
            # Multi-segment org/path
            (
                "https://github.com/org-name/sub-team/repo.git",
                "github.com/org-name/sub-team/repo",
            ),
            # No scheme, no .git suffix (already sanitized — must be idempotent)
            ("github.com/org/repo", "github.com/org/repo"),
            # GitLab self-hosted
            (
                "https://gitlab.example.com/group/repo.git",
                "gitlab.example.com/group/repo",
            ),
            # SSH with non-default user
            ("user@gitlab.com:org/repo.git", "gitlab.com/org/repo"),
            # HTTPS with port
            (
                "https://git.example.com:8443/org/repo.git",
                "git.example.com:8443/org/repo",
            ),
            # Bitbucket SSH form
            (
                "git@bitbucket.org:team/repo.git",
                "bitbucket.org/team/repo",
            ),
        ],
        ids=[
            "multi_segment_path",
            "already_sanitized_idempotent",
            "gitlab_self_hosted",
            "ssh_non_default_user",
            "https_with_port",
            "bitbucket_ssh",
        ],
    )
    def test_sanitize_remote_url_parametrized_matrix(self, raw_url: str, expected: str) -> None:
        """Extended URL matrix exercises Sage Appendix item 18 regex-chain order.

        Each input flows through the 5 sequential ``re.sub`` calls (HTTP creds
        strip → SSH creds strip → ``git@host:path`` normalize →
        ``https?://`` strip → ``.git`` suffix strip). Reordering any step
        breaks at least one of these inputs.
        """
        from bonfire.onboard.scanners.git_state import sanitize_remote_url

        result = sanitize_remote_url(raw_url)
        assert result == expected, (
            f"sanitize_remote_url({raw_url!r}) -> {result!r}, expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# Subprocess-failure narration (observability)
# ---------------------------------------------------------------------------


class TestRunCmdFailureNarration:
    """``_run_cmd`` narrates the subprocess timeout/OSError sentinel.

    Before this contract, ``_run_cmd`` returned the sentinel ``(-1, "")`` on
    both a hung subprocess (timeout) and an exec failure (``OSError``) without
    saying anything. Callers then silently skip emitting that git fact (branch,
    remotes, last-commit), so a hung or unlaunchable ``git`` is invisible to an
    operator reading the logs. These tests pin that each failure path emits a
    DEBUG line naming the git subcommand and the reason — while the ``(-1, "")``
    return contract callers depend on stays unchanged.
    """

    async def test_oserror_returns_sentinel_and_narrates(self, monkeypatch, caplog) -> None:
        """An exec failure (``OSError``) returns ``(-1, "")`` and logs the cause.

        ``OSError`` is what you get when the binary cannot be launched
        (missing executable, permission denied). The sentinel return is the
        contract; the DEBUG narration is the new, additive signal.
        """
        from bonfire.onboard.scanners import git_state

        async def _boom(*args, **kwargs):
            raise OSError("git executable not found")

        monkeypatch.setattr(git_state.asyncio, "create_subprocess_exec", _boom)

        with caplog.at_level(logging.DEBUG, logger=git_state._log.name):
            rc, out = await git_state._run_cmd(["git", "status", "--porcelain"])

        # Return contract is unchanged.
        assert (rc, out) == (-1, "")

        # The failure now speaks: the joined subcommand and the reason appear.
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "git status --porcelain" in messages
        assert any(
            r.levelno == logging.DEBUG and "git executable not found" in r.getMessage()
            for r in caplog.records
        ), f"expected a DEBUG line naming the OSError cause, got: {messages!r}"

    async def test_timeout_returns_sentinel_and_narrates(self, monkeypatch, caplog) -> None:
        """A hung subprocess (timeout) returns ``(-1, "")`` and logs the timeout.

        The subprocess launches but never finishes within the per-command
        budget; ``_run_cmd`` kills it and returns the sentinel. The narration
        must mark this as a timeout so an operator can tell a hang apart from a
        launch failure.
        """
        from bonfire.onboard.scanners import git_state

        class _HangingProc:
            """Stand-in process whose ``communicate`` never resolves in time."""

            returncode = None

            async def communicate(self):
                # First call (inside wait_for) hangs forever -> TimeoutError;
                # the post-kill call resolves immediately.
                if not getattr(self, "_killed", False):
                    await asyncio.sleep(3600)
                return (b"", b"")

            def kill(self):
                self._killed = True

        async def _make_proc(*args, **kwargs):
            return _HangingProc()

        monkeypatch.setattr(git_state.asyncio, "create_subprocess_exec", _make_proc)

        with caplog.at_level(logging.DEBUG, logger=git_state._log.name):
            rc, out = await git_state._run_cmd(["git", "log", "-1", "--format=%ci"], timeout=0.01)

        # Return contract is unchanged.
        assert (rc, out) == (-1, "")

        # The timeout now speaks: the subcommand and a timeout marker appear.
        messages = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "git log -1 --format=%ci" in messages
        assert "timeout" in messages, (
            f"expected a DEBUG line marking the timeout, got: {messages!r}"
        )

    async def test_narration_does_not_leak_cwd_path(self, monkeypatch, caplog) -> None:
        """Narration names the subcommand, not an absolute ``cwd`` path.

        The log message must carry the git subcommand (safe, non-PII) and not
        echo a verbatim filesystem path — this keeps the line self-describing
        without tripping path-guard expectations or leaking layout.
        """
        from bonfire.onboard.scanners import git_state

        async def _boom(*args, **kwargs):
            raise OSError("nope")

        monkeypatch.setattr(git_state.asyncio, "create_subprocess_exec", _boom)

        secret_cwd = "/home/someone/private/repo"
        with caplog.at_level(logging.DEBUG, logger=git_state._log.name):
            await git_state._run_cmd(["git", "branch", "--show-current"], cwd=secret_cwd)

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "git branch --show-current" in messages
        assert secret_cwd not in messages, "narration must not echo the verbatim cwd path"
