# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""What a run leaves on disk — proved through the real composition root.

Two artifacts the release-gate box grades had readers and no producer:
``.bonfire/costs.jsonl`` (the box exports ``BONFIRE_COST_LEDGER_PATH`` and
nothing on the write side ever read it) and ``.bonfire/review-verdict.json``
(the reviewer's verdict lived only on the returned envelope's metadata). Both
gaps were invisible to the existing suite, and the reason is the shape of the
suite rather than an oversight in it: every test of the run command injects
its own engine factory, so the wiring nothing else exercises is exactly the
wiring nothing else could catch.

So this module calls :func:`bonfire.engine.composition.build_default_engine`
and runs the engine it returns. Building the same object graph by hand would
re-implement the wiring under test and pass whether or not the product is
wired at all.

Two replacements, both stated:

* ``claude_agent_sdk.query`` — every dispatch below would otherwise be a
  billed network call. The fake carries a real ``total_cost_usd`` because the
  ledger assertions are about money arriving, and a zero-cost fake would let
  an empty ledger look correct.
* ``bonfire.github.client.GitHubClient`` — the reviewer stage reads a PR diff
  before it has a verdict to record. This proves nothing about how Bonfire
  drives ``gh``; it puts the handler past the network so the artifact it
  writes afterwards can be observed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from typer.testing import CliRunner

from bonfire.cli.commands.cost import cost_app
from bonfire.cost import models as cost_models
from bonfire.dispatch import sdk_backend
from bonfire.engine.composition import build_default_engine
from bonfire.github import client as github_client_module
from bonfire.handlers.wizard import REVIEW_VERDICT_RELPATH
from bonfire.models.envelope import META_PR_NUMBER, Envelope
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType

#: What the fake backend charges. Deliberately not round: an assertion on
#: this exact figure cannot be satisfied by a default, a zero, or a total
#: someone rounded on the way through.
DISPATCH_COST_USD = 0.3742


class CostingTransport:
    """``claude_agent_sdk.query`` stand-in that charges and answers.

    ``RecordingTransport`` in ``conftest.py`` reports ``total_cost_usd=0.0``,
    which is the right default for tests about options and the wrong one for
    tests about a cost ledger.
    """

    def __init__(self, reply: str, cost_usd: float = DISPATCH_COST_USD) -> None:
        self.reply = reply
        self.cost_usd = cost_usd
        self.calls: list[Any] = []

    def __call__(self, *, prompt: str, options: Any) -> Any:
        self.calls.append(options)
        reply, cost = self.reply, self.cost_usd

        async def _stream() -> Any:
            yield AssistantMessage(content=[TextBlock(text=reply)], model="fake")
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fake-session",
                total_cost_usd=cost,
                result=reply,
            )

        return _stream()


class StubGitHubClient:
    """Answers the reviewer's two reads; records what it was asked to post."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.posted: list[tuple[int, str, str]] = []
        self.post_raises: Exception | None = None

    async def get_pr_diff(self, number: int) -> str:
        return "diff --git a/src/x.py b/src/x.py\n+pass\n"

    async def get_pr_files(self, number: int) -> list[dict]:
        return [{"path": "src/x.py", "additions": 1, "deletions": 0}]

    async def post_review(self, number: int, body: str, *, event: str) -> None:
        if self.post_raises is not None:
            raise self.post_raises
        self.posted.append((number, body, event))


@pytest.fixture
def target_repo(tmp_path: Path, git_repo: Any) -> Path:
    """A work tree the composition root will accept as a project root.

    Carries a GitHub-shaped ``origin`` so ``detect_github_repo`` finds a slug
    and the root builds a real client class (the one replaced below) rather
    than ``UnconfiguredGitHubClient``.
    """
    repo = git_repo(tmp_path / "target")
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/widget.git"],
        check=True,
    )
    return repo


@pytest.fixture
def ledger_env(target_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the ledger at the target, exactly as the box's export does."""
    path = target_repo / ".bonfire" / "costs.jsonl"
    monkeypatch.setenv("BONFIRE_COST_LEDGER_PATH", str(path))
    return path


@pytest.fixture
def stub_github(monkeypatch: pytest.MonkeyPatch) -> StubGitHubClient:
    """Replace the client class the composition root constructs."""
    stub = StubGitHubClient("acme/widget")
    monkeypatch.setattr(github_client_module, "GitHubClient", lambda repo: stub)
    return stub


def _dispatch_plan() -> WorkflowPlan:
    """One backend stage — the smallest run that spends money."""
    return WorkflowPlan(
        name="probe",
        workflow_type=WorkflowType.DEBUG,
        description="probe",
        task_description="probe",
        stages=[StageSpec(name="scout", agent_name="scout", role="scout")],
    )


def _review_plan() -> WorkflowPlan:
    """One reviewer stage — the smallest run that produces a verdict."""
    return WorkflowPlan(
        name="review",
        workflow_type=WorkflowType.DEBUG,
        description="review",
        task_description="review the diff",
        stages=[
            StageSpec(
                name="wizard",
                agent_name="review-agent",
                role="reviewer",
                handler_name="wizard",
            )
        ],
    )


def _pr_envelope() -> Envelope:
    """Seed metadata carrying the PR number the reviewer stage needs."""
    return Envelope(task="review the diff", metadata={META_PR_NUMBER: 7})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse *path* as JSONL, failing on the first line that is not JSON."""
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:  # pragma: no cover - failure detail
            pytest.fail(f"{path} line {number} is not valid JSON: {exc}")
    return rows


# ---------------------------------------------------------------------------
# The cost ledger
# ---------------------------------------------------------------------------


async def test_a_run_that_spends_money_writes_the_ledger_the_box_reads(
    target_repo: Path, ledger_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wallet hole, closed at both layers at once.

    Two separate defects had to be fixed for this to pass, and either one
    alone leaves it red: nothing subscribed a ledger consumer to the bus the
    composition root built, and the writer ignored the environment variable
    naming the file. Wiring without the path yields a ledger the box cannot
    see; the path without the wiring yields a correctly-named file nobody
    writes.
    """
    monkeypatch.setattr(sdk_backend, "query", CostingTransport("done"))
    plan = _dispatch_plan()

    result = await build_default_engine(plan, project_root=target_repo).run(plan)

    assert result.success, result.error
    assert ledger_env.is_file(), (
        "no cost ledger: a run that charged real money left no record of it, "
        "and 'bonfire cost' reports $0.00 forever"
    )
    rows = _read_jsonl(ledger_env)
    dispatches = [r for r in rows if r["type"] == "dispatch"]
    assert dispatches, f"ledger has no dispatch row: {rows}"
    assert dispatches[0]["cost_usd"] == DISPATCH_COST_USD
    assert dispatches[0]["agent_name"] == "scout"
    assert [r for r in rows if r["type"] == "pipeline"], f"ledger has no pipeline row: {rows}"


async def test_bonfire_cost_reports_the_money_that_run_spent(
    target_repo: Path, ledger_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end across the two ends of the ledger.

    The producer is the real engine; the reader is the real CLI command. The
    file is not constructed by the test at any point — if the two ends
    disagree about which path to use, this goes red the way the box did.
    """
    monkeypatch.setattr(sdk_backend, "query", CostingTransport("done"))
    plan = _dispatch_plan()
    await build_default_engine(plan, project_root=target_repo).run(plan)

    output = CliRunner().invoke(cost_app, []).output

    assert f"${DISPATCH_COST_USD:.2f}" in output, output
    assert "Built by Bonfire for $0.00" not in output, output


async def test_the_ledger_default_stays_the_cross_project_one(
    target_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No override means the shared ledger, not a per-target file.

    ``bonfire cost`` answers "Built by Bonfire for $X" cumulatively across
    every project on the machine, so honouring the override must not turn
    into relocating the default: a per-repository default would fragment
    that history and orphan the ledgers users already have.

    The stand-in is ``DEFAULT_LEDGER_PATH`` itself rather than
    ``Path.home()``, and the reason is a real property of the module — the
    constant is evaluated once at import, so a later ``Path.home`` patch
    would not move it. What this proves is the branch taken: with no
    override the writer goes to the shared constant and writes nothing
    under the target.
    """
    shared = tmp_path / "shared" / "cost_ledger.jsonl"
    monkeypatch.delenv("BONFIRE_COST_LEDGER_PATH", raising=False)
    monkeypatch.setattr(cost_models, "DEFAULT_LEDGER_PATH", shared)
    monkeypatch.setattr(sdk_backend, "query", CostingTransport("done"))
    plan = _dispatch_plan()

    await build_default_engine(plan, project_root=target_repo).run(plan)

    assert shared.is_file()
    assert not (target_repo / ".bonfire" / "costs.jsonl").exists()
    assert cost_models.DEFAULT_LEDGER_PATH.name == "cost_ledger.jsonl"


# ---------------------------------------------------------------------------
# The review verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected_verdict", "expected_source"),
    [
        ("Looks good.\n<verdict>APPROVE</verdict>", "approve", "agent"),
        ("Needs work.\n<verdict>REQUEST_CHANGES</verdict>", "request_changes", "agent"),
        ("I cannot approve this.", "request_changes", "parser_fallback"),
    ],
)
async def test_the_verdict_file_carries_this_run_s_actual_decision(
    target_repo: Path,
    ledger_env: Path,
    stub_github: StubGitHubClient,
    monkeypatch: pytest.MonkeyPatch,
    reply: str,
    expected_verdict: str,
    expected_source: str,
) -> None:
    """The artifact must track the run, not merely exist.

    Parametrised over three replies because a producer that hardcoded
    ``approve`` — or any fixed document — would satisfy "the file is there"
    while reporting a decision nobody made. That is worse than the missing
    file: the gap is visible and the lie is not. The third row is the
    fail-safe path, where the parser rather than the agent decides.
    """
    monkeypatch.setattr(sdk_backend, "query", CostingTransport(reply))
    plan = _review_plan()

    await build_default_engine(plan, project_root=target_repo).run(
        plan, initial_envelope=_pr_envelope()
    )

    verdict_path = target_repo / REVIEW_VERDICT_RELPATH
    assert verdict_path.is_file(), "the reviewer stage ran and left no verdict artifact"
    document = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert document["verdict"] == expected_verdict
    assert document["verdict_source"] == expected_source
    assert document["pr_number"] == 7
    assert document["cost_usd"] == DISPATCH_COST_USD


async def test_the_verdict_survives_a_github_that_refuses(
    target_repo: Path,
    ledger_env: Path,
    stub_github: StubGitHubClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The box has no ``gh`` and no credentials, so this is the graded path.

    A verdict recorded after the GitHub call would be absent on exactly the
    runs the release gate reads. Writing before the post is what makes the
    artifact a statement about the review rather than about the network.
    """
    stub_github.post_raises = RuntimeError("gh: command not found")
    monkeypatch.setattr(sdk_backend, "query", CostingTransport("Fine.\n<verdict>APPROVE</verdict>"))
    plan = _review_plan()

    await build_default_engine(plan, project_root=target_repo).run(
        plan, initial_envelope=_pr_envelope()
    )

    verdict_path = target_repo / REVIEW_VERDICT_RELPATH
    assert verdict_path.is_file()
    assert json.loads(verdict_path.read_text(encoding="utf-8"))["verdict"] == "approve"
    assert stub_github.posted == []


async def test_the_verdict_lands_where_the_release_gate_looks(
    target_repo: Path,
    ledger_env: Path,
    stub_github: StubGitHubClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path is the assertion.

    ``docs/release-gates.md`` and the box both name
    ``<target>/.bonfire/review-verdict.json``. Spelled out literally here
    rather than through the constant, so renaming the constant cannot move
    the artifact and keep the suite green.
    """
    monkeypatch.setattr(sdk_backend, "query", CostingTransport("Fine.\n<verdict>APPROVE</verdict>"))
    plan = _review_plan()

    await build_default_engine(plan, project_root=target_repo).run(
        plan, initial_envelope=_pr_envelope()
    )

    assert (target_repo / ".bonfire" / "review-verdict.json").is_file()
