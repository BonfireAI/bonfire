"""Tests for bonfire.github — GitHubClient, MockGitHubClient, PRInfo, detect_github_repo.

Conservative Knight (BON-343): mirrors the established coverage of the private
reference implementation.

Covers:
- PRInfo frozen Pydantic model (field types, immutability, forbid extras,
  state validation, equality).
- MockGitHubClient in-memory fake: create/get/merge PR, issue/comment recording,
  validation, and action log.
- GitHubClient subprocess-mocked verification: each public method shells out to
  ``gh`` with the right arguments, failures surface as RuntimeError, uppercase
  state strings are normalized to lowercase, and ``-R owner/repo`` is passed.
- Interface parity: MockGitHubClient exposes the same public async methods with
  the same signatures as the real GitHubClient.
- ``bonfire.github`` package exports.
- ``detect_github_repo``: HTTPS/SSH parsing, no-remote, non-GitHub, non-repo.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# PRInfo model tests
# ---------------------------------------------------------------------------


class TestPRInfo:
    """PRInfo is a frozen Pydantic model for pull-request metadata."""

    def test_create_with_required_fields(self):
        from bonfire.github import PRInfo

        pr = PRInfo(
            number=42,
            url="https://github.com/owner/repo/pull/42",
            title="feat: add dispatch engine",
            state="open",
            head_branch="feat/dispatch",
            base_branch="main",
        )
        assert pr.number == 42
        assert pr.url == "https://github.com/owner/repo/pull/42"
        assert pr.title == "feat: add dispatch engine"
        assert pr.state == "open"
        assert pr.head_branch == "feat/dispatch"
        assert pr.base_branch == "main"

    def test_frozen_model_rejects_mutation(self):
        from bonfire.github import PRInfo

        pr = PRInfo(
            number=1,
            url="https://github.com/o/r/pull/1",
            title="t",
            state="open",
            head_branch="h",
            base_branch="main",
        )
        with pytest.raises(ValidationError):
            pr.number = 99

    def test_extra_fields_forbidden(self):
        from bonfire.github import PRInfo

        with pytest.raises(ValidationError):
            PRInfo(
                number=1,
                url="u",
                title="t",
                state="open",
                head_branch="h",
                base_branch="main",
                bogus="nope",
            )

    def test_number_must_be_positive_int(self):
        from bonfire.github import PRInfo

        with pytest.raises(ValidationError):
            PRInfo(
                number=-1,
                url="u",
                title="t",
                state="open",
                head_branch="h",
                base_branch="main",
            )

    def test_state_must_be_valid(self):
        from bonfire.github import PRInfo

        with pytest.raises(ValidationError):
            PRInfo(
                number=1,
                url="u",
                title="t",
                state="invalid_state",
                head_branch="h",
                base_branch="main",
            )

    def test_valid_states(self):
        from bonfire.github import PRInfo

        for state in ("open", "closed", "merged"):
            pr = PRInfo(
                number=1,
                url="u",
                title="t",
                state=state,
                head_branch="h",
                base_branch="main",
            )
            assert pr.state == state

    def test_equality(self):
        from bonfire.github import PRInfo

        a = PRInfo(number=1, url="u", title="t", state="open", head_branch="h", base_branch="main")
        b = PRInfo(number=1, url="u", title="t", state="open", head_branch="h", base_branch="main")
        assert a == b


# ---------------------------------------------------------------------------
# MockGitHubClient tests
# ---------------------------------------------------------------------------


class TestMockGitHubClient:
    """MockGitHubClient stores actions in memory with the same async interface."""

    async def test_create_pr_returns_pr_info(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(
            title="feat: init",
            head="feat/init",
            base="main",
            body="Initial PR",
        )
        assert pr.number == 1
        assert pr.title == "feat: init"
        assert pr.state == "open"
        assert pr.head_branch == "feat/init"
        assert pr.base_branch == "main"

    async def test_create_pr_increments_number(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr1 = await mock.create_pr(title="first", head="a", base="main")
        pr2 = await mock.create_pr(title="second", head="b", base="main")
        assert pr1.number == 1
        assert pr2.number == 2

    async def test_get_pr_returns_created(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        created = await mock.create_pr(title="t", head="h", base="main")
        fetched = await mock.get_pr(created.number)
        assert fetched.number == created.number
        assert fetched.title == "t"

    async def test_get_pr_not_found_raises(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(KeyError):
            await mock.get_pr(999)

    async def test_close_issue_records_action(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.close_issue(42)
        assert len(mock.actions) == 1
        assert mock.actions[0]["type"] == "close_issue"
        assert mock.actions[0]["issue_number"] == 42

    async def test_add_comment_records_action(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.add_comment(issue_number=10, body="LGTM")
        assert len(mock.actions) == 1
        assert mock.actions[0]["type"] == "add_comment"
        assert mock.actions[0]["issue_number"] == 10
        assert mock.actions[0]["body"] == "LGTM"

    async def test_merge_pr_updates_state(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        await mock.merge_pr(pr.number)
        merged = await mock.get_pr(pr.number)
        assert merged.state == "merged"

    async def test_merge_pr_not_found_raises(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(KeyError):
            await mock.merge_pr(999)

    async def test_merge_pr_already_merged_raises(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        await mock.merge_pr(pr.number)
        with pytest.raises(ValueError, match="already merged"):
            await mock.merge_pr(pr.number)

    async def test_merge_pr_closed_raises(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        mock._prs[pr.number] = pr.model_copy(update={"state": "closed"})
        with pytest.raises(ValueError, match="not open"):
            await mock.merge_pr(pr.number)

    async def test_create_pr_validates_empty_title(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(ValueError, match="title"):
            await mock.create_pr(title="", head="h", base="main")

    async def test_create_pr_validates_empty_head(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(ValueError, match="head"):
            await mock.create_pr(title="t", head="", base="main")

    async def test_actions_log_tracks_all_operations(self):
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        await mock.add_comment(issue_number=pr.number, body="hi")
        await mock.merge_pr(pr.number)
        await mock.close_issue(5)
        assert len(mock.actions) == 4
        types = [a["type"] for a in mock.actions]
        assert types == ["create_pr", "add_comment", "merge_pr", "close_issue"]


# ---------------------------------------------------------------------------
# GitHubClient (real) — subprocess-mocked tests
# ---------------------------------------------------------------------------


class TestGitHubClient:
    """GitHubClient wraps gh CLI via subprocess. All tests mock _run_gh."""

    async def test_create_pr_calls_gh(self):
        from bonfire.github import GitHubClient

        gh_output = json.dumps(
            {
                "number": 7,
                "url": "https://github.com/o/r/pull/7",
                "title": "feat: x",
                "state": "OPEN",
                "headRefName": "feat/x",
                "baseRefName": "main",
            }
        )

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, gh_output, "")
            pr = await client.create_pr(title="feat: x", head="feat/x", base="main")

        assert pr.number == 7
        assert pr.title == "feat: x"
        assert pr.state == "open"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "pr" in call_args
        assert "create" in call_args

    async def test_get_pr_calls_gh(self):
        from bonfire.github import GitHubClient

        gh_output = json.dumps(
            {
                "number": 3,
                "url": "https://github.com/o/r/pull/3",
                "title": "fix: bug",
                "state": "OPEN",
                "headRefName": "fix/bug",
                "baseRefName": "main",
            }
        )

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, gh_output, "")
            pr = await client.get_pr(3)

        assert pr.number == 3
        assert pr.title == "fix: bug"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "pr" in call_args
        assert "view" in call_args

    async def test_merge_pr_calls_gh(self):
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.merge_pr(5)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "pr" in call_args
        assert "merge" in call_args

    async def test_close_issue_calls_gh(self):
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.close_issue(10)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "issue" in call_args
        assert "close" in call_args

    async def test_add_comment_calls_gh(self):
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.add_comment(issue_number=10, body="Nice work")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "comment" in call_args

    async def test_gh_failure_raises_runtime_error(self):
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "not authenticated")
            with pytest.raises(RuntimeError, match="not authenticated"):
                await client.create_pr(title="t", head="h", base="main")

    async def test_gh_state_normalization(self):
        """gh CLI returns UPPER state names; client normalizes to lowercase."""
        from bonfire.github import GitHubClient

        for gh_state, expected in [
            ("OPEN", "open"),
            ("CLOSED", "closed"),
            ("MERGED", "merged"),
        ]:
            gh_output = json.dumps(
                {
                    "number": 1,
                    "url": "u",
                    "title": "t",
                    "state": gh_state,
                    "headRefName": "h",
                    "baseRefName": "main",
                }
            )
            client = GitHubClient(repo="owner/repo")
            with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (0, gh_output, "")
                pr = await client.get_pr(1)
            assert pr.state == expected

    async def test_repo_passed_to_gh_commands(self):
        """Every gh call includes -R owner/repo."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="myorg/myrepo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.close_issue(1)

        call_args = mock_run.call_args[0][0]
        assert "-R" in call_args
        idx = call_args.index("-R")
        assert call_args[idx + 1] == "myorg/myrepo"


# ---------------------------------------------------------------------------
# Interface parity: Mock implements same public methods as Real
# ---------------------------------------------------------------------------


class TestInterfaceParity:
    """MockGitHubClient must expose the exact same async methods as GitHubClient."""

    def test_mock_has_all_real_methods(self):
        from bonfire.github import GitHubClient, MockGitHubClient

        real_methods = {
            name
            for name in dir(GitHubClient)
            if not name.startswith("_") and callable(getattr(GitHubClient, name))
        }
        mock_methods = {
            name
            for name in dir(MockGitHubClient)
            if not name.startswith("_") and callable(getattr(MockGitHubClient, name))
        }
        missing = real_methods - mock_methods
        assert not missing, f"MockGitHubClient missing methods: {missing}"

    def test_method_signatures_match(self):
        """Same parameter names and counts for each public method."""
        import inspect

        from bonfire.github import GitHubClient, MockGitHubClient

        real_methods = {
            name
            for name in dir(GitHubClient)
            if not name.startswith("_") and callable(getattr(GitHubClient, name))
        }
        for name in real_methods:
            real_sig = inspect.signature(getattr(GitHubClient, name))
            mock_sig = inspect.signature(getattr(MockGitHubClient, name))
            real_params = list(real_sig.parameters.keys())
            mock_params = list(mock_sig.parameters.keys())
            assert real_params == mock_params, (
                f"Signature mismatch for {name}: real={real_params}, mock={mock_params}"
            )

    def test_all_public_methods_are_async(self):
        """Every public method on both classes must be a coroutine function."""
        import asyncio

        from bonfire.github import GitHubClient, MockGitHubClient

        for cls in (GitHubClient, MockGitHubClient):
            for name in dir(cls):
                if name.startswith("_"):
                    continue
                attr = getattr(cls, name)
                if callable(attr) and not isinstance(attr, type):
                    assert asyncio.iscoroutinefunction(attr), f"{cls.__name__}.{name} is not async"


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


class TestExports:
    """bonfire.github exports GitHubClient, MockGitHubClient, PRInfo."""

    def test_github_client_importable(self):
        from bonfire.github import GitHubClient

        assert GitHubClient is not None

    def test_mock_github_client_importable(self):
        from bonfire.github import MockGitHubClient

        assert MockGitHubClient is not None

    def test_pr_info_importable(self):
        from bonfire.github import PRInfo

        assert PRInfo is not None

    def test_detect_github_repo_importable(self):
        from bonfire.github import detect_github_repo

        assert detect_github_repo is not None


# ---------------------------------------------------------------------------
# detect_github_repo tests
# ---------------------------------------------------------------------------


class TestDetectGithubRepo:
    """Tests for detect_github_repo utility."""

    def test_https_url(self, tmp_path):
        """Parses HTTPS remote into owner/repo."""
        import subprocess

        from bonfire.github.client import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Acme/widget.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Acme/widget"

    def test_ssh_url(self, tmp_path):
        """Parses SSH remote into owner/repo."""
        import subprocess

        from bonfire.github.client import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:Acme/widget.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Acme/widget"

    def test_no_remote(self, tmp_path):
        """Returns empty string when no remote exists."""
        import subprocess

        from bonfire.github.client import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        assert detect_github_repo(tmp_path) == ""

    def test_non_github_remote(self, tmp_path):
        """Returns empty string for non-GitHub remotes."""
        import subprocess

        from bonfire.github.client import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.com/Acme/widget.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == ""

    def test_not_a_repo(self, tmp_path):
        """Returns empty string when path is not a git repo."""
        from bonfire.github.client import detect_github_repo

        assert detect_github_repo(tmp_path) == ""
