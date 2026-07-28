# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the composition root — calling the real function, not a stand-in.

``bonfire.cli.commands.run`` shipped a ``_default_engine`` that omitted the
engine's ``handlers``, ``gate_registry``, ``tool_policy`` and ``project_root``
arguments, and it did so undetected because every test of the run command
injects its own engine factory. The docstring said as much: *"Unit tests never
call this — they inject their own factory."*

So the rule for this module is that it must call
:func:`bonfire.engine.composition.build_default_engine` itself. Anything that
accepts a factory parameter is not exercising the composition root; it is
exercising the seam that hid it.

Only the SDK transport is replaced, and only where a test needs to observe
what the engine handed it. That boundary is deliberate: everything above it
(plan selection, handler dispatch, gate evaluation, the ``ClaudeAgentOptions``
the backend constructs) is the thing under test, and everything below it is a
billed network call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import typer

from bonfire.cli.commands import run as run_module
from bonfire.dispatch import sdk_backend
from bonfire.engine import composition
from bonfire.engine.composition import (
    PipelineWiringError,
    build_default_engine,
    build_default_gates,
    build_default_handlers,
    resolve_project_root,
    validate_plan_wiring,
)
from bonfire.engine.pipeline import PipelineEngine
from bonfire.models.envelope import Envelope
from bonfire.models.plan import GateContext, StageSpec, WorkflowPlan, WorkflowType
from bonfire.workflow.registry import get_default_registry
from bonfire.workflow.standard import debug, standard_build
from tests.integration.conftest import RecordingTransport

# ---------------------------------------------------------------------------
# The four omitted arguments
# ---------------------------------------------------------------------------


def test_build_default_engine_supplies_every_argument_the_engine_accepts(
    tmp_path: Path, git_repo: object
) -> None:
    """The regression this module exists for.

    Each assertion names the consequence of the omission it guards, because
    "the argument is not None" on its own does not say why anyone should care.
    """
    engine = build_default_engine(standard_build(), project_root=git_repo(tmp_path / "r"))

    assert engine._handlers, (
        "no handler registry: every stage with a handler_name fails with 'Unknown handler'"
    )
    assert engine._gates, (
        "no gate registry: every gate named by a plan is bypassed and counted as a pass"
    )
    assert engine._tool_policy is not None, (
        "no tool policy: the engine resolves an empty tool list for every role, "
        "so dispatched agents get no Read, no Write, no Bash"
    )
    assert engine._project_root, (
        "no project root: the engine sends cwd='' and the backend reads that as "
        "'trusted', ingesting the ambient directory's CLAUDE.md"
    )


def test_the_engine_is_the_real_one_with_the_real_backend(tmp_path: Path, git_repo: object) -> None:
    engine = build_default_engine(debug(), project_root=git_repo(tmp_path / "r"))
    assert isinstance(engine, PipelineEngine)
    assert isinstance(engine._backend, sdk_backend.ClaudeSDKBackend)


def test_tool_policy_grants_a_non_empty_toolset_to_a_build_role(
    tmp_path: Path, git_repo: object
) -> None:
    """Control rod on the policy: it must actually return tools.

    ``DefaultToolPolicy`` returns ``[]`` for unknown roles, which is the same
    value the un-wired engine produced. Asserting the object exists would not
    distinguish the two.
    """
    engine = build_default_engine(debug(), project_root=git_repo(tmp_path / "r"))
    assert engine._tool_policy is not None
    assert "Bash" in engine._tool_policy.tools_for("warrior")


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_gate_reports_the_name_it_is_registered_under(tmp_path: Path) -> None:
    """A registry key that disagrees with its gate's own name is a lie.

    Filing ``TestPassGate`` under ``"verification"`` would satisfy every
    structural check in this file while stamping the wrong gate name onto
    every failure message a user reads.

    Wired with a root and a review verdict: state-grading gates refuse
    to answer without one, which is the point of them.
    """
    registry = build_default_gates(budget_usd=1.0, project_root=tmp_path)
    envelope = Envelope(envelope_id="probe", task="probe").with_result("")
    envelope = envelope.with_metadata(review_verdict="approve")
    context = GateContext(pipeline_cost_usd=0.0, prior_results={})

    checked = 0
    for key, gate in registry.items():
        result = await gate.evaluate(envelope, context)
        assert result.gate_name == key, (
            f"registered as {key!r} but reports itself as {result.gate_name!r}"
        )
        checked += 1

    assert checked == len(registry) and checked >= 7, (
        f"only {checked} gate(s) checked; the loop guards nothing if it is empty"
    )


def test_every_builtin_workflow_is_fully_wired() -> None:
    """No built-in plan may name a handler or gate the defaults lack.

    Walks the shipped workflow registry rather than a hard-coded list, so a
    new workflow whose wiring was never added fails here.
    """
    registry = get_default_registry()
    handlers = build_default_handlers(
        project_root=Path("/nonexistent"),
        backend=object(),
        bus=object(),
        config=object(),
        settings=object(),
        repo_slug="owner/repo",
    )
    gates = build_default_gates(budget_usd=1.0)

    workflows = registry.list_names()
    assert workflows, "empty workflow registry would make this test vacuous"

    named_handlers: set[str] = set()
    named_gates: set[str] = set()
    for name in workflows:
        plan = registry.get(name)()
        validate_plan_wiring(plan, handlers=handlers, gates=gates)
        for stage in plan.stages:
            if stage.handler_name:
                named_handlers.add(stage.handler_name)
            named_gates.update(stage.gates)

    # Control rod: the loop above passes trivially if the built-in plans name
    # nothing at all. They name five handlers and six gates.
    assert len(named_handlers) >= 5, f"only {sorted(named_handlers)} handlers exercised"
    assert len(named_gates) >= 6, f"only {sorted(named_gates)} gates exercised"


# ---------------------------------------------------------------------------
# The unknown-gate control rod
# ---------------------------------------------------------------------------


def _plan_naming(*, gate: str | None = None, handler: str | None = None) -> WorkflowPlan:
    return WorkflowPlan(
        name="rod",
        workflow_type=WorkflowType.DEBUG,
        description="control rod",
        task_description="control rod",
        stages=[
            StageSpec(
                name="scout",
                agent_name="scout",
                role="scout",
                handler_name=handler,
                gates=[gate] if gate else [],
            )
        ],
    )


def test_unknown_gate_is_refused_and_the_message_names_it() -> None:
    """The rod. An unregistered gate must be loud, not a pass.

    Left to the engine, this plan runs to completion: ``_evaluate_gates``
    looks the name up, misses, emits ``QualityBypassed`` and continues, and
    the stage is reported as having passed its quality checks.
    """
    with pytest.raises(PipelineWiringError) as excinfo:
        validate_plan_wiring(
            _plan_naming(gate="no_such_gate"),
            handlers={},
            gates=build_default_gates(),
        )
    message = str(excinfo.value)
    assert "no_such_gate" in message, "the failure must name the gate"
    assert "scout" in message, "the failure must name the stage"
    assert "completion" in message, "the failure must list what IS registered"


def test_unknown_handler_is_refused_and_the_message_names_it() -> None:
    with pytest.raises(PipelineWiringError) as excinfo:
        validate_plan_wiring(
            _plan_naming(handler="no_such_handler"),
            handlers={"bard": object()},
            gates=build_default_gates(),
        )
    message = str(excinfo.value)
    assert "no_such_handler" in message
    assert "bard" in message, "the failure must list what IS registered"


def test_all_missing_names_are_reported_in_one_pass() -> None:
    """Reporting one at a time means paying for the run again per fix."""
    plan = WorkflowPlan(
        name="rod",
        workflow_type=WorkflowType.DEBUG,
        description="control rod",
        task_description="control rod",
        stages=[
            StageSpec(name="a", agent_name="a", role="scout", gates=["ghost_one"]),
            StageSpec(
                name="b",
                agent_name="b",
                role="scout",
                handler_name="ghost_handler",
                gates=["ghost_two"],
                depends_on=["a"],
            ),
        ],
    )
    with pytest.raises(PipelineWiringError) as excinfo:
        validate_plan_wiring(plan, handlers={}, gates={})
    message = str(excinfo.value)
    for name in ("ghost_one", "ghost_two", "ghost_handler"):
        assert name in message, f"{name} missing from a single-pass report"


def test_a_fully_registered_plan_is_not_refused() -> None:
    """Control rod on the rod: the validator is not simply always raising."""
    validate_plan_wiring(
        _plan_naming(gate="completion"),
        handlers={},
        gates=build_default_gates(),
    )


def test_cli_refuses_an_unknown_gate_with_exit_code_2(
    tmp_path: Path,
    git_repo: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The rod, driven through the real CLI verb and the real factory.

    Registers a workflow naming a gate that does not exist, then runs the
    published command path with its default ``build_engine`` -- no injection.
    """
    monkeypatch.chdir(git_repo(tmp_path / "r"))

    def _registry_with_rod() -> Any:
        registry = get_default_registry()
        registry.register(
            "rod_unknown_gate",
            lambda: _plan_naming(gate="gate_that_does_not_exist"),
        )
        return registry

    monkeypatch.setattr(run_module, "get_default_registry", _registry_with_rod)

    with pytest.raises(typer.Exit) as excinfo:
        run_module._run("probe", workflow="rod_unknown_gate")

    assert excinfo.value.exit_code == 2, "a plan that cannot be honoured is not a run"
    captured = capsys.readouterr()
    assert "gate_that_does_not_exist" in captured.err
    assert "counted as a pass" in captured.err, "the message must say why refusing beats bypassing"


# ---------------------------------------------------------------------------
# The verb, end to end
# ---------------------------------------------------------------------------


def test_run_completes_through_the_published_command_path(
    tmp_path: Path,
    git_repo: object,
    monkeypatch: pytest.MonkeyPatch,
    transport: RecordingTransport,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``bonfire run "<task>"`` succeeds through the published command path.

    No injected factory: ``_run`` builds its engine with ``_default_engine``,
    which is the composition root. Exit code 0 is the claim.

    ``debug`` is named explicitly rather than relying on the default. The
    default is ``standard_build``, which ends by pushing a branch and opening
    a pull request -- it cannot exit 0 against a throwaway repository with no
    remote, and it should not be made to. What this test is for is the wiring
    between the CLI verb and the composition root, and ``debug`` exercises
    that without needing publishing infrastructure.
    """
    monkeypatch.chdir(git_repo(tmp_path / "r"))

    with pytest.raises(typer.Exit) as excinfo:
        run_module._run("add a docstring to the module", workflow="debug")

    assert excinfo.value.exit_code == 0, capsys.readouterr().err
    assert "Run succeeded" in capsys.readouterr().out
    assert transport.calls, "the workflow must actually dispatch"


def test_standard_build_reaches_the_publisher_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transport: RecordingTransport,
    git_repo: object,
) -> None:
    """Pins where ``standard_build`` stops, and where it no longer does.

    Before the composition root existed this plan died at stage five with
    ``Unknown handler: sage_correction_bounce``. It then reached ``bard``
    and refused there, because nothing populated ``Envelope.artifacts``.

    With a transport that reports no file writes, refusing is still the
    right answer -- there is genuinely nothing to commit. What changed is
    that the refusal is now a *function of the run* rather than
    unconditional; :func:`test_a_reported_file_write_reaches_the_publisher`
    is the other half.
    """
    monkeypatch.chdir(git_repo(tmp_path / "r"))

    plan = standard_build().model_copy(update={"task_description": "probe"})
    engine = build_default_engine(plan)
    result = __import__("asyncio").run(engine.run(plan))

    assert result.failed_stage != "sage_correction_bounce", (
        "the handler registry did not take effect"
    )
    assert "Unknown handler" not in result.error, result.error
    assert result.failed_stage == "bard", (
        f"expected the publisher stage to be the boundary, got "
        f"{result.failed_stage!r}: {result.error}"
    )
    assert "empty_artifacts" in result.error or "artifacts" in result.error
    assert len(transport.calls) == 4, (
        f"expected four dispatched stages before bard, got {len(transport.calls)}"
    )


# ---------------------------------------------------------------------------
# Environment discovery
# ---------------------------------------------------------------------------


def test_resolve_project_root_finds_the_repository_root(tmp_path: Path, git_repo: object) -> None:
    repo = git_repo(tmp_path / "repo")
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    assert resolve_project_root(nested) == repo.resolve()


def test_resolve_project_root_falls_back_to_a_concrete_directory(tmp_path: Path) -> None:
    """Outside a work tree the answer must still be non-empty.

    Returning ``None`` or ``""`` here would put the ambient directory back on
    the trusted path, which is the bug this whole module is about.
    """
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert resolve_project_root(plain) == plain.resolve()


def test_the_composition_root_does_not_define_a_second_slug_detector() -> None:
    """No parallel copy of a helper this repo already ships.

    ``bonfire.github.client.detect_github_repo`` predates this module and is
    what ``GitHubClient`` callers elsewhere use. Two answers to "which
    repository is this?" is one more than the question has.
    """
    source = Path(composition.__file__).read_text(encoding="utf-8")
    assert "detect_github_repo" in source, "the existing detector must be the one used"
    assert "def detect_repo_slug" not in source, "a second slug detector was reintroduced"


def test_the_detected_slug_reaches_the_github_client(tmp_path: Path, git_repo: object) -> None:
    """Behavioural check that detection is wired, not merely imported."""
    repo = git_repo(tmp_path / "repo")
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:BonfireAI/bonfire.git"],
        check=True,
    )
    handlers = build_default_handlers(
        project_root=repo,
        backend=object(),
        bus=object(),
        config=object(),
        settings=object(),
    )
    assert handlers["steward"]._github_client._repo == "BonfireAI/bonfire"


def test_slug_detection_reads_the_origin_remote(tmp_path: Path, git_repo: object) -> None:
    repo = git_repo(tmp_path / "repo")
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:BonfireAI/bonfire.git"],
        check=True,
    )
    from bonfire.github.client import detect_github_repo

    assert detect_github_repo(repo) == "BonfireAI/bonfire"


@pytest.mark.asyncio
async def test_github_operations_refuse_loudly_when_no_remote_is_configured() -> None:
    """Never a mock. A silent mock would report a merge that never happened.

    ``StewardHandler`` merges pull requests. Handing it ``MockGitHubClient``
    when no remote exists would make the pipeline claim success for work it
    did not do -- the exact class of failure this lane removes.
    """
    handlers = build_default_handlers(
        project_root=Path("/nonexistent"),
        backend=object(),
        bus=object(),
        config=object(),
        settings=object(),
        repo_slug="",
    )
    client = handlers["steward"]._github_client
    with pytest.raises(RuntimeError, match="unavailable"):
        await client.merge_pr(1)


# ---------------------------------------------------------------------------
# The default-workflow decision, and the tripwire that should undo it
# ---------------------------------------------------------------------------


def test_the_default_workflow_is_the_flagship_pipeline() -> None:
    """The default is back to ``standard_build``.

    It was temporarily ``debug`` because the publisher stage refused on every
    run: nothing populated ``Envelope.artifacts``. That producer now exists,
    so the reason for the stopgap is gone and the headline verb runs the
    pipeline the documentation describes.
    """
    assert run_module._DEFAULT_WORKFLOW == "standard_build"
    assert run_module._DEFAULT_WORKFLOW in get_default_registry()


def test_help_text_names_what_the_default_workflow_requires() -> None:
    """The default now ends in a push and a pull request.

    That needs a remote and an authenticated ``gh``. A user without them
    should learn it from ``--help``, not from a stage failure four dispatches
    into a billed run.
    """
    parameter = run_module.run.__defaults__[-1]
    help_text = (parameter.help or "").lower()
    assert "gh" in help_text
    assert "remote" in help_text
    assert "debug" in help_text
