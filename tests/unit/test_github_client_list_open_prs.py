"""RED tests for GitHubClient.list_open_prs and PRSummary — BON-519 Knight B.

Per Sage memo bon-519-sage-20260428T033101Z.md:
- §D5 (lines 473-522) — list_open_prs signature, gh CLI invocation shape,
  PRSummary frozen Pydantic model, MockGitHubClient parity.
- §D-CL.2 (lines 903-908) — Knight B contract for this file.

The tests assert:
- gh subprocess is invoked with the correct argv shape (mocked at
  asyncio.create_subprocess_exec via the existing _run_gh seam).
- gh JSON output parses into a list[PRSummary].
- exclude=N filters PR #N from the returned list.
- PRSummary is a frozen Pydantic model (mutation raises ValidationError).
- MockGitHubClient.list_open_prs returns canned data, deterministic order.
- MockGitHubClient signature matches GitHubClient.list_open_prs (parity).

All tests MUST FAIL on first run: list_open_prs and PRSummary do not yet
exist on disk.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# PRSummary model — frozen Pydantic per Sage §D5 lines 498-504.
# ---------------------------------------------------------------------------


class TestPRSummaryModel:
    """PRSummary frozen Pydantic model: number, head_branch, title, file_paths."""

    def test_construct_with_required_fields(self) -> None:
        from bonfire.github import PRSummary

        summary = PRSummary(
            number=17,
            head_branch="feat/x",
            title="add x",
            file_paths=("src/x.py", "tests/test_x.py"),
        )
        assert summary.number == 17
        assert summary.head_branch == "feat/x"
        assert summary.title == "add x"
        assert summary.file_paths == ("src/x.py", "tests/test_x.py")

    def test_pr_summary_frozen_raises_on_mutation(self) -> None:
        """Sage §D-CL.2 line 907: PRSummary is frozen=True; mutating raises
        ValidationError."""
        from bonfire.github import PRSummary

        summary = PRSummary(
            number=1,
            head_branch="h",
            title="t",
            file_paths=(),
        )
        with pytest.raises(ValidationError):
            summary.number = 99

    def test_pr_summary_extra_forbid(self) -> None:
        """PRSummary uses extra='forbid' (mirrors PRInfo convention)."""
        from bonfire.github import PRSummary

        with pytest.raises(ValidationError):
            PRSummary(
                number=1,
                head_branch="h",
                title="t",
                file_paths=(),
                bogus="nope",
            )

    def test_pr_summary_number_must_be_positive(self) -> None:
        """Mirror PRInfo: number=Field(gt=0)."""
        from bonfire.github import PRSummary

        with pytest.raises(ValidationError):
            PRSummary(number=0, head_branch="h", title="t", file_paths=())


# ---------------------------------------------------------------------------
# GitHubClient.list_open_prs — Sage §D-CL.2 lines 903-907 + §D5 lines 478-491.
# ---------------------------------------------------------------------------


class TestListOpenPRs:
    """GitHubClient.list_open_prs shells out to ``gh pr list`` correctly."""

    async def test_invokes_correct_gh_command(self) -> None:
        """Sage §D-CL.2 line 904: arg list contains
        ['pr', 'list', '-R', repo, '--base', base, '--state', 'open',
         '--json', 'number,headRefName,title,files'].
        """
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "[]", "")
            await client.list_open_prs("master")

        args = mock_run.call_args[0][0]
        assert "pr" in args
        assert "list" in args
        assert "-R" in args
        assert "owner/repo" in args
        assert "--base" in args
        idx = args.index("--base")
        assert args[idx + 1] == "master"
        assert "--state" in args
        idx = args.index("--state")
        assert args[idx + 1] == "open"
        assert "--json" in args
        idx = args.index("--json")
        assert args[idx + 1] == "number,headRefName,title,files"

    async def test_parses_json_into_pr_summary_list(self) -> None:
        """Sage §D-CL.2 line 905: given canned gh JSON, returns
        list[PRSummary]."""
        from bonfire.github import GitHubClient, PRSummary

        gh_json = json.dumps(
            [
                {
                    "number": 17,
                    "headRefName": "feat/peer",
                    "title": "peer pr",
                    "files": [
                        {"path": "src/persona.py"},
                        {"path": "tests/test_persona.py"},
                    ],
                },
                {
                    "number": 23,
                    "headRefName": "feat/other",
                    "title": "other pr",
                    "files": [{"path": "src/other.py"}],
                },
            ]
        )

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, gh_json, "")
            result = await client.list_open_prs("master")

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(pr, PRSummary) for pr in result)
        first = result[0]
        assert first.number == 17
        assert first.head_branch == "feat/peer"
        assert first.title == "peer pr"
        assert "src/persona.py" in first.file_paths
        assert "tests/test_persona.py" in first.file_paths

    async def test_exclude_param_filters_pr_number(self) -> None:
        """Sage §D-CL.2 line 906: when exclude=42 is set, the returned list
        filters PR #42 (handled client-side post-parse OR via a separate
        gh-level filter; either is acceptable as long as the result excludes
        PR 42)."""
        from bonfire.github import GitHubClient

        gh_json = json.dumps(
            [
                {"number": 42, "headRefName": "h1", "title": "t1", "files": []},
                {"number": 17, "headRefName": "h2", "title": "t2", "files": []},
            ]
        )

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, gh_json, "")
            result = await client.list_open_prs("master", exclude=42)

        numbers = {pr.number for pr in result}
        assert 42 not in numbers
        assert 17 in numbers

    async def test_empty_list_returns_empty(self) -> None:
        """gh returns empty array -> empty list."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, "[]", "")
            result = await client.list_open_prs("master")

        assert result == []

    async def test_gh_failure_raises_runtime_error(self) -> None:
        """Mirror existing client error-surfacing: non-zero exit -> RuntimeError."""
        from bonfire.github import GitHubClient

        client = GitHubClient(repo="owner/repo")
        with patch.object(client, "_run_gh", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "auth failure")
            with pytest.raises(RuntimeError, match="auth failure"):
                await client.list_open_prs("master")


# ---------------------------------------------------------------------------
# MockGitHubClient parity — Sage §D-CL.2 line 908 + §D5 line 506.
# ---------------------------------------------------------------------------


class TestMockListOpenPRs:
    """MockGitHubClient.list_open_prs mirrors the real client interface
    and returns canned data the test fixture pre-populates."""

    async def test_default_empty_list(self) -> None:
        """Mock returns empty list when no PRs are configured."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        result = await mock.list_open_prs("master")
        assert result == []

    async def test_canned_data_returned(self) -> None:
        """Sage §D5 line 506 + §D-CL.2 line 908: mock parity. Test fixtures
        pre-populate with N synthetic PRs each with a deterministic file set.

        The mock exposes ``set_open_prs(base=..., prs=[...])`` as the
        canonical configuration entry point so tests can drive sibling
        scenarios without monkey-patching internals.
        """
        from bonfire.github import MockGitHubClient, PRSummary

        mock = MockGitHubClient()
        mock.set_open_prs(  # type: ignore[attr-defined]
            base="master",
            prs=[
                {
                    "number": 42,
                    "head_branch": "feat/a",
                    "title": "a",
                    "file_paths": ("src/a.py",),
                },
                {
                    "number": 17,
                    "head_branch": "feat/b",
                    "title": "b",
                    "file_paths": ("src/b.py", "tests/test_b.py"),
                },
            ],
        )
        result = await mock.list_open_prs("master")
        assert len(result) == 2
        assert all(isinstance(pr, PRSummary) for pr in result)
        nums = {pr.number for pr in result}
        assert nums == {42, 17}

    async def test_exclude_filters_canned_data(self) -> None:
        """Mock's exclude= behaviour matches real client."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        mock.set_open_prs(  # type: ignore[attr-defined]
            base="master",
            prs=[
                {
                    "number": 7,
                    "head_branch": "h1",
                    "title": "t1",
                    "file_paths": (),
                },
                {
                    "number": 8,
                    "head_branch": "h2",
                    "title": "t2",
                    "file_paths": (),
                },
            ],
        )
        result = await mock.list_open_prs("master", exclude=7)
        assert {pr.number for pr in result} == {8}

    async def test_records_action_in_mock_log(self) -> None:
        """Mirror MockGitHubClient action-recording convention."""
        from bonfire.github import MockGitHubClient

        mock = MockGitHubClient()
        await mock.list_open_prs("master")
        assert any(a.get("type") == "list_open_prs" for a in mock.actions)


# ---------------------------------------------------------------------------
# Interface parity (signature mirror) — extends existing TestInterfaceParity
# in test_github.py for the new method specifically.
# ---------------------------------------------------------------------------


class TestListOpenPRsInterfaceParity:
    """list_open_prs exists on both GitHubClient and MockGitHubClient with
    matching signatures (Sage §D5 line 506 mock parity)."""

    def test_real_client_has_method(self) -> None:
        from bonfire.github import GitHubClient

        assert hasattr(GitHubClient, "list_open_prs")

    def test_mock_client_has_method(self) -> None:
        from bonfire.github import MockGitHubClient

        assert hasattr(MockGitHubClient, "list_open_prs")

    def test_signatures_match(self) -> None:
        """Same parameter names and order on both classes."""
        from bonfire.github import GitHubClient, MockGitHubClient

        real_sig = inspect.signature(GitHubClient.list_open_prs)
        mock_sig = inspect.signature(MockGitHubClient.list_open_prs)
        assert list(real_sig.parameters.keys()) == list(mock_sig.parameters.keys())

    def test_both_methods_async(self) -> None:
        import asyncio

        from bonfire.github import GitHubClient, MockGitHubClient

        assert asyncio.iscoroutinefunction(GitHubClient.list_open_prs)
        assert asyncio.iscoroutinefunction(MockGitHubClient.list_open_prs)


# ---------------------------------------------------------------------------
# Package export — PRSummary surfaces from bonfire.github.
# ---------------------------------------------------------------------------


class TestPRSummaryExport:
    """PRSummary is exported from bonfire.github (Sage §D10 line 749)."""

    def test_pr_summary_importable_from_package(self) -> None:
        from bonfire.github import PRSummary

        assert PRSummary is not None
