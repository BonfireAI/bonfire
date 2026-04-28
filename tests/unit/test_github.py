"""Canonical RED suite for bonfire.github — BON-343 (Wave 5.4).

Synthesized from Knight-A (innovative lens) + Knight-B (conservative lens)
+ private v1 reference, then deduplicated. Covers:

- ``PRInfo`` frozen Pydantic model (field types, immutability, ``extra=forbid``,
  state ``Literal`` validation, equality, positive-int ``number`` constraint).
- ``MockGitHubClient`` in-memory fake: create / get / merge PR; issue close,
  comment, diff, files, review recording; validation; idempotent close; action
  log order.
- ``GitHubClient`` subprocess-mocked verification: every public method shells
  out to ``gh`` with correct ``pr|issue``/action argv, failures surface as
  ``RuntimeError``, uppercase state strings normalize to lowercase, every call
  includes ``-R owner/repo``, ``post_review`` maps ``APPROVE|REQUEST_CHANGES|
  COMMENT`` to the right CLI flag, ``--body`` passes user text as a separate
  argv element (never shell-spliced).
- HTTP/CLI failure modes: rate-limit stderr, auth failure, non-zero with empty
  stderr, malformed JSON, missing ``number`` field, defaults for optional JSON
  fields.
- Interface parity: ``MockGitHubClient`` exposes every public method of
  ``GitHubClient`` with the same parameter names; both are fully async.
- ``detect_github_repo``: HTTPS, SSH, no-remote, non-GitHub, non-repo,
  trailing ``.git`` stripping, no-suffix parsing, missing-path graceful fail.
- Package exports.

The tests use per-test lazy imports rather than top-level imports so pytest
can collect the file while ``src/bonfire/github/`` is stubbed — each missing
name surfaces RED per-test, not as a collection error. This matches the
public v0.1 idiom in ``test_engine_init.py`` / ``test_prompt_compiler.py``.
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
# PRInfo model tests
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
# MockGitHubClient tests
# ---------------------------------------------------------------------------


class TestMockGitHubClient:
    """MockGitHubClient stores actions in memory with the same async interface."""

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

    async def test_merge_pr_closed_raises(self) -> None:
        """Closed PRs cannot be merged — surfaces a 'not open' ValueError."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        pr = await mock.create_pr(title="t", head="h", base="main")
        mock._prs[pr.number] = pr.model_copy(update={"state": "closed"})
        with pytest.raises(ValueError, match="not open"):
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

    async def test_mock_get_pr_diff_records_number(self) -> None:
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.get_pr_diff(42)
        assert mock.actions[-1]["number"] == 42

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

    async def test_mock_close_issue_is_idempotent(self) -> None:
        """Closing the same issue twice on the mock is allowed (no failure)."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.close_issue(1)
        await mock.close_issue(1)  # must not raise
        closes = [a for a in mock.actions if a["type"] == "close_issue"]
        assert len(closes) == 2


# ---------------------------------------------------------------------------
# GitHubClient (real) — subprocess-mocked tests
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
        assert pr.title == "feat: x"
        assert pr.state == "open"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "pr" in call_args
        assert "create" in call_args

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
        assert pr.title == "fix: bug"
        call_args = mock_run.call_args[0][0]
        assert "pr" in call_args
        assert "view" in call_args

    async def test_merge_pr_calls_gh(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.merge_pr(5)

        call_args = mock_run.call_args[0][0]
        assert "pr" in call_args
        assert "merge" in call_args

    async def test_close_issue_calls_gh(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.close_issue(10)

        call_args = mock_run.call_args[0][0]
        assert "issue" in call_args
        assert "close" in call_args

    async def test_add_comment_calls_gh(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.add_comment(issue_number=10, body="Nice work")

        call_args = mock_run.call_args[0][0]
        assert "comment" in call_args

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
        call_args = mock_run.call_args[0][0]
        assert "--body" in call_args
        assert call_args[call_args.index("--body") + 1] == "hello"

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
        call_args = mock_run.call_args[0][0]
        assert "--body" not in call_args


# ---------------------------------------------------------------------------
# post_review event-flag correctness
# ---------------------------------------------------------------------------


class TestPostReview:
    """post_review maps APPROVE/REQUEST_CHANGES/COMMENT to correct gh CLI flags."""

    async def test_approve_flag(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.post_review(1, body="lgtm", event="APPROVE")
        args = mock_run.call_args[0][0]
        assert "--approve" in args

    async def test_request_changes_flag(self) -> None:
        """``REQUEST_CHANGES`` -> ``--request-changes`` flag passed to gh."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.post_review(1, body="nope", event="REQUEST_CHANGES")
        args = mock_run.call_args[0][0]
        assert "--request-changes" in args
        assert "--approve" not in args

    async def test_comment_flag(self) -> None:
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            await client.post_review(1, body="fyi", event="COMMENT")
        args = mock_run.call_args[0][0]
        assert "--comment" in args

    async def test_body_passed_as_separate_argv(self) -> None:
        """``--body`` must be passed as a separate argv element (never shell-spliced)."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "", "")
            nasty = "lgtm; rm -rf /"  # Shell metacharacters — must not corrupt argv
            await client.post_review(1, body=nasty, event="APPROVE")
        args = mock_run.call_args[0][0]
        assert "--body" in args
        assert args[args.index("--body") + 1] == nasty


# ---------------------------------------------------------------------------
# HTTP / CLI failure modes
# ---------------------------------------------------------------------------


class TestGitHubClientFailures:
    """Rate limits, auth errors, non-zero exits, malformed JSON."""

    async def test_rate_limit_stderr_raises_with_message(self) -> None:
        """gh rate-limit failures surface as RuntimeError carrying the message."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "HTTP 403: API rate limit exceeded")
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
        """When gh omits url/title/branches, client fills with empty string."""
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
        """``number`` is the only truly required field; omission must raise."""
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


# ---------------------------------------------------------------------------
# Interface parity: Mock implements same public methods as Real
# ---------------------------------------------------------------------------


class TestInterfaceParity:
    """MockGitHubClient must expose the exact same async methods as GitHubClient."""

    def test_mock_has_all_real_methods(self) -> None:
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
        """Same parameter names and counts for each public method."""
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

    def test_all_public_methods_are_async(self) -> None:
        """Every public method on both classes must be a coroutine function.

        Mock-only synchronous configuration helpers (e.g. ``set_open_prs``
        for canned-data injection) are exempted via ``_SYNC_MOCK_HELPERS``;
        they have no real-client counterpart and are not part of the
        async wire protocol.
        """
        from bonfire.github import GitHubClient, MockGitHubClient

        # Sync helpers on the mock that exist purely for test-fixture
        # configuration. They have no analogue on the real client.
        _SYNC_MOCK_HELPERS: frozenset[str] = frozenset({"set_open_prs"})

        for cls in (GitHubClient, MockGitHubClient):
            for name in dir(cls):
                if name.startswith("_"):
                    continue
                if cls is MockGitHubClient and name in _SYNC_MOCK_HELPERS:
                    continue
                attr = getattr(cls, name)
                if callable(attr) and not isinstance(attr, type):
                    assert asyncio.iscoroutinefunction(attr), f"{cls.__name__}.{name} is not async"


# ---------------------------------------------------------------------------
# detect_github_repo
# ---------------------------------------------------------------------------


class TestDetectGithubRepo:
    """detect_github_repo parses ``owner/repo`` from the origin remote URL."""

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

    def test_strips_trailing_git_suffix(self, tmp_path) -> None:
        """``.git`` suffix is stripped."""
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Owner/Name.git"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Owner/Name"

    def test_no_dotgit_suffix(self, tmp_path) -> None:
        """A URL without ``.git`` suffix still parses correctly."""
        from bonfire.github import detect_github_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Owner/Name"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert detect_github_repo(tmp_path) == "Owner/Name"

    def test_missing_path_graceful(self, tmp_path) -> None:
        """Missing path must not crash; empty string signals detection failure."""
        from bonfire.github import detect_github_repo

        missing = tmp_path / "does-not-exist"
        assert detect_github_repo(missing) == ""


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


class TestExports:
    """bonfire.github exports GitHubClient, MockGitHubClient, PRInfo, detect_github_repo."""

    def test_github_client_importable(self) -> None:
        from bonfire.github import GitHubClient

        assert GitHubClient is not None

    def test_mock_github_client_importable(self) -> None:
        from bonfire.github import MockGitHubClient

        assert MockGitHubClient is not None

    def test_pr_info_importable(self) -> None:
        from bonfire.github import PRInfo

        assert PRInfo is not None

    def test_detect_github_repo_importable(self) -> None:
        from bonfire.github import detect_github_repo

        assert detect_github_repo is not None
