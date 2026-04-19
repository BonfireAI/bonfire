"""Tests for bonfire.github — GitHubClient, MockGitHubClient, PRInfo, detect_github_repo.

Knight-A (innovative lens). Baseline private-mirror coverage plus an
adversarial-lens class (``TestInnovativeGithubEdge``) attacking the public-API
seam: malformed ``gh`` JSON, rate-limit / auth-failure stderr, non-zero exit
with empty stderr, mock-vs-real method signature parity, corner cases in
``detect_github_repo`` (scp-form URLs, paths with .git in the name), and
``post_review`` event-flag correctness.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# PRInfo
# ---------------------------------------------------------------------------


class TestPRInfo:
    """PRInfo is a frozen Pydantic model for pull-request metadata."""

    def test_create_with_required_fields(self) -> None:
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

    def test_frozen_model_rejects_mutation(self) -> None:
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

    def test_extra_fields_forbidden(self) -> None:
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

    def test_number_must_be_positive_int(self) -> None:
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

    def test_number_zero_rejected(self) -> None:
        from bonfire.github import PRInfo

        with pytest.raises(ValidationError):
            PRInfo(
                number=0,
                url="u",
                title="t",
                state="open",
                head_branch="h",
                base_branch="main",
            )

    def test_state_must_be_valid(self) -> None:
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

    def test_valid_states(self) -> None:
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

    def test_equality(self) -> None:
        from bonfire.github import PRInfo

        a = PRInfo(number=1, url="u", title="t", state="open", head_branch="h", base_branch="main")
        b = PRInfo(number=1, url="u", title="t", state="open", head_branch="h", base_branch="main")
        assert a == b


# ---------------------------------------------------------------------------
# MockGitHubClient
# ---------------------------------------------------------------------------


class TestMockGitHubClient:
    """MockGitHubClient is a real deliverable — in-memory with call recording."""

    async def test_create_pr_returns_pr_info(self) -> None:
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

    async def test_create_pr_increments_number(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr1 = await mock.create_pr(title="first", head="a", base="main")
        pr2 = await mock.create_pr(title="second", head="b", base="main")
        assert pr1.number == 1
        assert pr2.number == 2

    async def test_get_pr_returns_created(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        created = await mock.create_pr(title="t", head="h", base="main")
        fetched = await mock.get_pr(created.number)
        assert fetched.number == created.number
        assert fetched.title == "t"

    async def test_get_pr_not_found_raises(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(KeyError):
            await mock.get_pr(999)

    async def test_close_issue_records_action(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.close_issue(42)
        assert len(mock.actions) == 1
        assert mock.actions[0]["type"] == "close_issue"
        assert mock.actions[0]["issue_number"] == 42

    async def test_add_comment_records_action(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.add_comment(issue_number=10, body="LGTM")
        assert len(mock.actions) == 1
        assert mock.actions[0]["type"] == "add_comment"
        assert mock.actions[0]["issue_number"] == 10
        assert mock.actions[0]["body"] == "LGTM"

    async def test_merge_pr_updates_state(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        await mock.merge_pr(pr.number)
        merged = await mock.get_pr(pr.number)
        assert merged.state == "merged"

    async def test_merge_pr_not_found_raises(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(KeyError):
            await mock.merge_pr(999)

    async def test_merge_pr_already_merged_raises(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        await mock.merge_pr(pr.number)
        with pytest.raises(ValueError, match="already merged"):
            await mock.merge_pr(pr.number)

    async def test_create_pr_validates_empty_title(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(ValueError, match="title"):
            await mock.create_pr(title="", head="h", base="main")

    async def test_create_pr_validates_empty_head(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        with pytest.raises(ValueError, match="head"):
            await mock.create_pr(title="t", head="", base="main")

    async def test_actions_log_tracks_all_operations(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        await mock.add_comment(issue_number=pr.number, body="hi")
        await mock.merge_pr(pr.number)
        await mock.close_issue(5)
        assert len(mock.actions) == 4
        assert [a["type"] for a in mock.actions] == [
            "create_pr",
            "add_comment",
            "merge_pr",
            "close_issue",
        ]

    async def test_mock_get_pr_diff_returns_string(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        diff = await mock.get_pr_diff(1)
        assert isinstance(diff, str)
        assert "diff --git" in diff
        assert mock.actions[-1]["type"] == "get_pr_diff"

    async def test_mock_get_pr_files_returns_list_of_dicts(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        files = await mock.get_pr_files(1)
        assert isinstance(files, list)
        assert files and "path" in files[0]

    async def test_mock_post_review_records_event(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.post_review(1, body="looks good", event="APPROVE")
        assert mock.actions[-1]["type"] == "post_review"
        assert mock.actions[-1]["event"] == "APPROVE"


# ---------------------------------------------------------------------------
# GitHubClient (subprocess-mocked)
# ---------------------------------------------------------------------------


class TestGitHubClient:
    """GitHubClient wraps gh CLI via subprocess. All tests mock _run_gh."""

    async def test_create_pr_calls_gh(self) -> None:
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
        assert pr.state == "open"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "pr" in args
        assert "create" in args

    async def test_get_pr_calls_gh(self) -> None:
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
        args = mock_run.call_args[0][0]
        assert "pr" in args
        assert "view" in args

    async def test_merge_pr_calls_gh(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.merge_pr(5)

        args = mock_run.call_args[0][0]
        assert "merge" in args

    async def test_close_issue_calls_gh(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.close_issue(10)

        args = mock_run.call_args[0][0]
        assert "issue" in args
        assert "close" in args

    async def test_add_comment_calls_gh(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.add_comment(issue_number=10, body="Nice work")

        args = mock_run.call_args[0][0]
        assert "comment" in args

    async def test_gh_failure_raises_runtime_error(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "not authenticated")
            with pytest.raises(RuntimeError, match="not authenticated"):
                await client.create_pr(title="t", head="h", base="main")

    async def test_gh_state_normalization(self) -> None:
        """gh CLI returns UPPER state names; client normalizes to lowercase."""
        from bonfire.github import GitHubClient

        for gh_state, expected in [("OPEN", "open"), ("CLOSED", "closed"), ("MERGED", "merged")]:
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

    async def test_repo_passed_to_gh_commands(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="myorg/myrepo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.close_issue(1)

        args = mock_run.call_args[0][0]
        assert "-R" in args
        assert args[args.index("-R") + 1] == "myorg/myrepo"

    async def test_get_pr_diff(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "diff --git a/x b/x\n", "")
            diff = await client.get_pr_diff(1)
        assert "diff --git" in diff

    async def test_get_pr_files(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (
                0,
                json.dumps({"files": [{"path": "a.py", "additions": 1, "deletions": 0}]}),
                "",
            )
            files = await client.get_pr_files(1)
        assert files == [{"path": "a.py", "additions": 1, "deletions": 0}]

    async def test_post_review_approve(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.post_review(1, body="lgtm", event="APPROVE")
        args = mock_run.call_args[0][0]
        assert "--approve" in args


# ---------------------------------------------------------------------------
# detect_github_repo
# ---------------------------------------------------------------------------


class TestDetectGithubRepo:
    def test_https_url(self, tmp_path) -> None:
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Acme/widget.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Acme/widget"

    def test_ssh_url(self, tmp_path) -> None:
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:Acme/widget.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Acme/widget"

    def test_no_remote(self, tmp_path) -> None:
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        assert detect_github_repo(tmp_path) == ""

    def test_non_github_remote(self, tmp_path) -> None:
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.com/Acme/widget.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == ""

    def test_not_a_repo(self, tmp_path) -> None:
        from bonfire.github import detect_github_repo

        assert detect_github_repo(tmp_path) == ""


# ---------------------------------------------------------------------------
# Innovative / adversarial-lens edge cases
# ---------------------------------------------------------------------------


class TestInnovativeGithubEdge:
    """Attack HTTP/CLI failure modes, parse robustness, and interface parity.

    Probes rate-limit text patterns, JSON that omits expected keys, empty
    stderr on non-zero exit, malformed JSON, mock/real method parity (the
    moat — you can swap Mock for Real in tests), state passthrough when
    gh returns an unknown value, Literal enforcement on post_review, and
    detect_github_repo against tricky URLs.
    """

    # ---------- HTTP/CLI failure modes ----------

    async def test_rate_limit_stderr_raises_with_message(self) -> None:
        """gh rate-limit failures surface as RuntimeError carrying the message."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (
                1,
                "",
                "HTTP 403: API rate limit exceeded",
            )
            with pytest.raises(RuntimeError, match="rate limit"):
                await client.get_pr(1)

    async def test_nonzero_exit_with_empty_stderr_still_raises(self) -> None:
        """Even when gh prints nothing to stderr, a non-zero exit MUST raise."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (2, "", "")
            with pytest.raises(RuntimeError):
                await client.merge_pr(1)

    async def test_malformed_json_raises(self) -> None:
        """Gibberish stdout must raise (json.JSONDecodeError is acceptable)."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "not json {", "")
            with pytest.raises((ValueError, json.JSONDecodeError, RuntimeError)):
                await client.get_pr(1)

    async def test_json_missing_optional_fields_uses_defaults(self) -> None:
        """When gh omits ``url``/``title``/branches, client fills with empty string."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        minimal = json.dumps({"number": 1, "state": "OPEN"})
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, minimal, "")
            pr = await client.get_pr(1)
        assert pr.number == 1
        assert pr.url == ""
        assert pr.title == ""
        assert pr.head_branch == ""
        assert pr.base_branch == ""

    async def test_json_number_missing_raises(self) -> None:
        """The only truly required field is ``number``; omission must raise."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps({"state": "OPEN"}), "")
            with pytest.raises((KeyError, ValidationError, ValueError)):
                await client.get_pr(1)

    async def test_auth_error_raises_with_message(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "gh auth login: not authenticated")
            with pytest.raises(RuntimeError, match="auth"):
                await client.create_pr(title="t", head="h", base="main")

    # ---------- post_review event-flag correctness ----------

    async def test_post_review_request_changes_flag(self) -> None:
        """``REQUEST_CHANGES`` -> ``--request-changes`` flag passed to gh."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.post_review(1, body="nope", event="REQUEST_CHANGES")
        args = mock_run.call_args[0][0]
        assert "--request-changes" in args
        assert "--approve" not in args

    async def test_post_review_comment_flag(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.post_review(1, body="fyi", event="COMMENT")
        args = mock_run.call_args[0][0]
        assert "--comment" in args

    async def test_post_review_body_passed_as_flag(self) -> None:
        """``--body`` must be passed as a separate argv element (never shell-spliced)."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            # A body containing shell-metacharacters must not corrupt the call
            nasty = "lgtm; rm -rf /"
            await client.post_review(1, body=nasty, event="APPROVE")
        args = mock_run.call_args[0][0]
        assert "--body" in args
        assert args[args.index("--body") + 1] == nasty

    # ---------- create_pr argument assembly ----------

    async def test_create_pr_omits_body_when_empty(self) -> None:
        """Empty body must NOT emit a ``--body ""`` pair (private-mirror behaviour)."""
        from bonfire.github import GitHubClient

        gh_output = json.dumps(
            {
                "number": 1,
                "url": "u",
                "title": "t",
                "state": "OPEN",
                "headRefName": "h",
                "baseRefName": "main",
            }
        )
        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, gh_output, "")
            await client.create_pr(title="t", head="h", base="main")  # no body
        args = mock_run.call_args[0][0]
        assert "--body" not in args

    async def test_create_pr_includes_body_when_provided(self) -> None:
        from bonfire.github import GitHubClient

        gh_output = json.dumps(
            {
                "number": 1,
                "url": "u",
                "title": "t",
                "state": "OPEN",
                "headRefName": "h",
                "baseRefName": "main",
            }
        )
        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, gh_output, "")
            await client.create_pr(title="t", head="h", base="main", body="hello")
        args = mock_run.call_args[0][0]
        assert "--body" in args
        assert args[args.index("--body") + 1] == "hello"

    # ---------- detect_github_repo corner cases ----------

    def test_detect_repo_strips_trailing_git(self, tmp_path) -> None:
        """``.git`` suffix is always stripped even for ``group/.git`` names."""
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Owner/Name.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Owner/Name"

    def test_detect_repo_no_dotgit_suffix(self, tmp_path) -> None:
        """A URL without ``.git`` suffix still parses correctly."""
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Owner/Name"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Owner/Name"

    def test_detect_repo_returns_empty_when_path_missing(self, tmp_path) -> None:
        from bonfire.github import detect_github_repo

        missing = tmp_path / "does-not-exist"
        # Must not crash; empty string signals detection failure
        assert detect_github_repo(missing) == ""

    # ---------- Interface parity: Mock must match Real ----------

    def test_mock_has_all_real_public_methods(self) -> None:
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

    def test_method_signatures_match(self) -> None:
        from bonfire.github import GitHubClient, MockGitHubClient

        real_methods = {
            name
            for name in dir(GitHubClient)
            if not name.startswith("_") and callable(getattr(GitHubClient, name))
        }
        for name in real_methods:
            real_sig = inspect.signature(getattr(GitHubClient, name))
            mock_sig = inspect.signature(getattr(MockGitHubClient, name))
            assert list(real_sig.parameters) == list(mock_sig.parameters), (
                f"Signature mismatch for {name}"
            )

    def test_all_public_methods_are_async(self) -> None:
        from bonfire.github import GitHubClient, MockGitHubClient

        for cls in (GitHubClient, MockGitHubClient):
            for name in dir(cls):
                if name.startswith("_"):
                    continue
                attr = getattr(cls, name)
                if callable(attr) and not isinstance(attr, type):
                    assert asyncio.iscoroutinefunction(attr), f"{cls.__name__}.{name}"

    # ---------- Mock-vs-Real semantic divergence we EXPECT ----------

    async def test_mock_close_issue_is_idempotent(self) -> None:
        """Closing the same issue twice on the mock is allowed (no failure)."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.close_issue(1)
        await mock.close_issue(1)  # must not raise
        closes = [a for a in mock.actions if a["type"] == "close_issue"]
        assert len(closes) == 2

    async def test_mock_get_pr_diff_records_number(self) -> None:
        """Action log preserves the PR number requested for diff."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.get_pr_diff(42)
        assert mock.actions[-1]["number"] == 42

    # ---------- Exports ----------

    def test_package_exports(self) -> None:
        import bonfire.github as gh

        assert gh.GitHubClient is not None
        assert gh.MockGitHubClient is not None
        assert gh.PRInfo is not None
        assert gh.detect_github_repo is not None
