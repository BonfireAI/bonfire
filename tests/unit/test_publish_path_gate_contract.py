# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The publishing path's contract with the release gate.

Four defects sat between the publisher stage and a branch the release
gate would recognise. Only the first two were visible from the handler:

1. ``GitWorkflow.create_branch`` auto-prefixes ``bonfire/`` by rebinding
   its *local* ``name`` parameter and returning ``None``. The prefixed
   name was used to create the ref and then discarded, so the publisher
   kept its unprefixed string and pushed a ref that was never created.
2. ``gh pr create`` does not accept ``--json``. The client passed it, so
   every PR creation died on ``unknown flag: --json`` -- after the branch
   and commit had already landed.
3. The branch's second segment was the *stage* name (``bard``). The gate,
   this repo's own operator docs, and the in-box prompt all specify
   ``fix``.
4. The id suffix was 12 hex characters. The same three sources specify 8.

Defects 3 and 4 are why fixing 1 alone would not have moved the gate:
``pr_opened`` is decided by grepping the local branch list against
``^bonfire/fix/[a-z0-9-]+-[0-9a-f]{8}$``, so a correctly-created
``bonfire/bard/<slug>-<12 hex>`` still reads as "no PR opened".

The regex below is written out rather than imported from the
implementation. Importing it would make every assertion here agree with
whatever the code happens to produce, which is the failure mode that let
the branch name drift from its own documentation in the first place.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bonfire.git.workflow import GitWorkflow
from bonfire.handlers.bard import BardHandler
from bonfire.models.envelope import Artifact, Envelope, TaskStatus
from bonfire.models.plan import StageSpec

#: The pattern the release gate greps the local branch list for. Duplicated
#: verbatim from the fixture's ``gate/expected-assertions.yaml`` and from
#: ``docs/box-operator.md``; a change here must be a deliberate contract change.
GATE_BRANCH_PATTERN = r"^bonfire/fix/[a-z0-9-]+-[0-9a-f]{8}$"

TICKET = "average() raises ZeroDivisionError on an empty list; it must return 0.0"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    # A real local bare remote, so ``push`` is exercised rather than stubbed:
    # the defect being fixed here is that the publisher pushed a ref that did
    # not exist, and a faked push cannot tell a real ref from an absent one.
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)

    root = tmp_path / "target"
    root.mkdir()
    _git("init", "-q", "-b", "main", ".", cwd=root)
    _git("config", "user.email", "t@example.invalid", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    _git("remote", "add", "origin", str(remote), cwd=root)
    (root / "src").mkdir()
    (root / "src" / "stats.py").write_text("def average(v):\n    return sum(v) / len(v)\n")
    _git("add", "-A", cwd=root)
    _git("commit", "-qm", "base", cwd=root)
    _git("push", "-q", "origin", "main", cwd=root)
    # The agent's edit, already on disk.
    (root / "src" / "stats.py").write_text(
        "def average(v):\n    if not v:\n        return 0.0\n    return sum(v) / len(v)\n"
    )
    return root


class _RecordingGitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def create_pr(self, title: str, head: str, base: str, body: str = "") -> Any:
        self.calls.append((title, head, base, body))

        class _PR:
            number = 1
            url = "https://github.com/o/r/pull/1"

        return _PR()


async def _publish(repo: Path, github: Any) -> Envelope:
    handler = BardHandler(git_workflow=GitWorkflow(repo), github_client=github, base_branch="main")
    return await handler.handle(
        StageSpec(name="bard", agent_name="bard", role="publisher", handler_name="bard"),
        Envelope(
            task=TICKET,
            artifacts=[Artifact(name="src/stats.py", content="", artifact_type="file_modified")],
        ),
        {},
    )


def _branches(repo: Path) -> list[str]:
    return _git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=repo).split()


class TestTheBranchThatLandsOnDisk:
    async def test_the_created_ref_matches_the_release_gate_pattern(self, repo: Path) -> None:
        await _publish(repo, _RecordingGitHub())
        feature = [b for b in _branches(repo) if b != "main"]
        assert len(feature) == 1, feature
        assert re.match(GATE_BRANCH_PATTERN, feature[0]), (
            f"{feature[0]!r} would read as pr_opened=false in the release gate"
        )

    async def test_the_publisher_reports_the_ref_that_exists(self, repo: Path) -> None:
        result = await _publish(repo, _RecordingGitHub())
        reported = result.metadata.get("bard_branch")
        assert reported in _branches(repo), (
            f"publisher reported {reported!r}; branches on disk are {_branches(repo)}"
        )

    async def test_the_branch_it_pushes_is_the_branch_it_created(self, repo: Path) -> None:
        pushed: list[str] = []

        class _WatchingWorkflow(GitWorkflow):
            async def push(self, *, branch: str, **kw: Any) -> None:
                pushed.append(branch)

        handler = BardHandler(
            git_workflow=_WatchingWorkflow(repo),
            github_client=_RecordingGitHub(),
            base_branch="main",
        )
        await handler.handle(
            StageSpec(name="bard", agent_name="bard", role="publisher", handler_name="bard"),
            Envelope(
                task=TICKET,
                artifacts=[
                    Artifact(name="src/stats.py", content="", artifact_type="file_modified")
                ],
            ),
            {},
        )
        assert pushed, "nothing was pushed"
        assert pushed[0] in _branches(repo), (
            f"pushed {pushed[0]!r}, which is not a ref that exists: {_branches(repo)}"
        )

    async def test_the_pr_is_opened_against_the_real_ref(self, repo: Path) -> None:
        github = _RecordingGitHub()
        await _publish(repo, github)
        assert github.calls, "no PR was opened"
        head = github.calls[0][1]
        assert head in _branches(repo), f"PR head {head!r} does not exist: {_branches(repo)}"

    async def test_the_id_suffix_is_eight_hex_characters(self, repo: Path) -> None:
        await _publish(repo, _RecordingGitHub())
        feature = [b for b in _branches(repo) if b != "main"][0]
        assert re.search(r"-[0-9a-f]{8}$", feature), feature
        assert not re.search(r"-[0-9a-f]{9,}$", feature), (
            f"{feature!r} carries a longer id than the gate pattern allows"
        )

    async def test_a_slugless_task_still_produces_a_matching_branch(self, repo: Path) -> None:
        handler = BardHandler(
            git_workflow=GitWorkflow(repo),
            github_client=_RecordingGitHub(),
            base_branch="main",
        )
        await handler.handle(
            StageSpec(name="bard", agent_name="bard", role="publisher", handler_name="bard"),
            Envelope(
                task="!!! ???",
                artifacts=[
                    Artifact(name="src/stats.py", content="", artifact_type="file_modified")
                ],
            ),
            {},
        )
        feature = [b for b in _branches(repo) if b != "main"][0]
        assert re.match(GATE_BRANCH_PATTERN, feature), feature

    async def test_the_publisher_still_succeeds(self, repo: Path) -> None:
        result = await _publish(repo, _RecordingGitHub())
        assert result.status is TaskStatus.COMPLETED, result.error.message if result.error else ""


class TestCreateBranchReturnsWhatItMade:
    async def test_create_branch_returns_the_prefixed_name(self, repo: Path) -> None:
        made = await GitWorkflow(repo).create_branch("fix/thing-0123abcd")
        assert made == "bonfire/fix/thing-0123abcd"
        assert made in _branches(repo)

    async def test_an_already_prefixed_name_is_returned_unchanged(self, repo: Path) -> None:
        made = await GitWorkflow(repo).create_branch("bonfire/fix/other-0123abcd")
        assert made == "bonfire/fix/other-0123abcd"
        assert made in _branches(repo)


class TestGhPrCreateFlags:
    """``gh pr create`` rejects ``--json``; the call must not pass it."""

    async def test_create_pr_does_not_pass_json(self) -> None:
        from bonfire.github.client import GitHubClient

        client = GitHubClient("owner/repo")
        seen: list[list[str]] = []

        async def _fake_run_gh(args: list[str]) -> tuple[int, str, str]:
            seen.append(args)
            return 0, "https://github.com/owner/repo/pull/42\n", ""

        client._run_gh = _fake_run_gh  # type: ignore[method-assign]
        await client.create_pr("title", "bonfire/fix/x-0123abcd", "main")

        assert seen, "gh was never invoked"
        assert "--json" not in seen[0], "gh pr create rejects --json with 'unknown flag: --json'"

    async def test_create_pr_reads_the_number_from_the_url_gh_prints(self) -> None:
        from bonfire.github.client import GitHubClient

        client = GitHubClient("owner/repo")

        async def _fake_run_gh(args: list[str]) -> tuple[int, str, str]:
            del args
            return 0, "\nhttps://github.com/owner/repo/pull/42\n", ""

        client._run_gh = _fake_run_gh  # type: ignore[method-assign]
        info = await client.create_pr("title", "bonfire/fix/x-0123abcd", "main")

        assert info.number == 42
        assert info.url == "https://github.com/owner/repo/pull/42"
        assert info.head_branch == "bonfire/fix/x-0123abcd"
        assert info.base_branch == "main"

    async def test_unparseable_output_is_an_error_not_a_fake_pr(self) -> None:
        from bonfire.github.client import GitHubClient

        client = GitHubClient("owner/repo")

        async def _fake_run_gh(args: list[str]) -> tuple[int, str, str]:
            del args
            return 0, "something went sideways\n", ""

        client._run_gh = _fake_run_gh  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="pull-request URL"):
            await client.create_pr("title", "bonfire/fix/x-0123abcd", "main")
