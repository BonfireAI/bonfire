# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The composition root — what a real ``bonfire`` invocation is actually wired to.

Every other module in Bonfire takes its collaborators by keyword argument, so
every other module can be unit-tested against fakes. That is good design, and
it leaves exactly one thing untested: the place where the real objects are
finally chosen. This module is that place, and it is written to be called by
tests, not merely by ``main``.

What ``PipelineEngine`` does when an argument is omitted
-------------------------------------------------------
The engine's constructor defaults are all permissive, because a test that
cares about the DAG should not have to supply a gate registry. The costs of
those defaults land on whoever forgets them in production:

``handlers``
    Defaults to ``{}``. Any stage carrying a ``handler_name`` fails with
    ``Unknown handler: <name>``. ``standard_build`` has five such stages, so
    the pipeline dies at the first one.

``gate_registry``
    Defaults to ``{}``. A gate named by a stage but absent from the registry
    is *bypassed and treated as passed* — the engine emits ``QualityBypassed``
    and continues. An empty registry therefore does not disable quality
    control loudly; it disables it silently, and every stage reports success.

``tool_policy``
    Defaults to ``None``, which the engine turns into an empty tool list for
    every role. Dispatched agents get no Read, no Write, no Bash.

``project_root``
    Defaults to ``None``, which the engine renders as ``cwd=""``. The SDK
    backend reads an empty ``cwd`` as "the caller's own directory, trusted",
    and so passes ``setting_sources=['project']`` — meaning the ``CLAUDE.md``
    and ``.claude/settings.json`` of *whatever directory the user happened to
    be standing in* are loaded into the agent's system prompt. Naming a real
    root moves that decision onto the explicit ``bonfire.toml`` opt-in the
    backend already implements, so an unfamiliar repository is untrusted by
    default rather than trusted by omission.

Nothing here is clever. The point is that it exists, that it is one function,
and that ``tests/integration/test_composition_root.py`` calls *this* code
rather than a stand-in for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from bonfire.engine import gates as _gates
from bonfire.engine.gate_state import PytestSuiteProbe

if TYPE_CHECKING:
    from bonfire.dispatch.tool_policy import ToolPolicy
    from bonfire.engine.pipeline import PipelineEngine
    from bonfire.events.bus import EventBus
    from bonfire.models.config import BonfireSettings, PipelineConfig
    from bonfire.models.plan import WorkflowPlan
    from bonfire.protocols import AgentBackend, QualityGate, StageHandler

__all__ = [
    "PipelineWiringError",
    "build_default_engine",
    "build_default_gates",
    "build_default_handlers",
    "resolve_project_root",
    "validate_plan_wiring",
]


class PipelineWiringError(RuntimeError):
    """A plan names a handler or a gate that the engine was not given.

    Raised *before* the engine runs, so the operator is told which name is
    missing instead of paying for the stages that precede the discovery.

    This exists because the engine's own reaction to a missing name is not
    good enough to rely on. An unknown handler fails the stage, which is at
    least visible; an unknown *gate* is bypassed and counted as a pass, which
    is not visible at all. Checking the plan against the registries up front
    turns both into the same loud, named failure.
    """


# ---------------------------------------------------------------------------
# Environment discovery
# ---------------------------------------------------------------------------


def resolve_project_root(start: Path | None = None) -> Path:
    """Return the repository root containing *start* (default: the cwd).

    Walks upward looking for a ``.git`` entry, accepting a file as well as a
    directory: linked work trees and submodules write ``.git`` as a file
    containing a ``gitdir:`` pointer, and treating those as "not a repository"
    would silently pick the wrong root inside exactly the setups this project
    is developed in.

    Deliberately no subprocess. Shelling out to ``git rev-parse`` would make
    the security-relevant answer depend on ``git`` being installed and on
    ``PATH``, and the fallback below would then fire for reasons that have
    nothing to do with where the user is.

    Falls back to the resolved *start* directory when no ``.git`` is found.
    The fallback still returns a concrete path: the property this feeds is
    that ``project_root`` is *non-empty*, and a directory that is merely
    un-versioned is not thereby trustworthy.
    """
    base = (start or Path.cwd()).resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate
    return base


class UnconfiguredGitHubClient:
    """Stands in for :class:`~bonfire.github.client.GitHubClient` with no remote.

    Every attribute access returns a coroutine function that raises. The
    alternative — substituting ``MockGitHubClient`` — would let a pipeline
    report that it opened and merged a pull request that never existed, which
    is precisely the failure mode this lane is here to remove. Refusing
    loudly at the call site keeps the handler's own error path (a ``FAILED``
    envelope naming the cause) intact.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def __getattr__(self, name: str) -> Any:
        async def _refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(
                f"GitHub operation {name!r} is unavailable: {self._reason}. "
                "Run bonfire from a clone with an 'origin' remote, or wire a "
                "GitHub client explicitly."
            )

        return _refuse


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


def build_default_gates(
    *,
    budget_usd: float | None = None,
    project_root: Path | None = None,
) -> dict[str, QualityGate]:
    """Return the built-in gate registry, keyed by the name plans use.

    The keys are the strings that appear in ``StageSpec.gates``. They are also
    the ``gate_name`` each gate stamps onto its own :class:`GateResult`, and
    ``test_composition_root.py`` asserts that correspondence rather than
    trusting this dict — a registry that files ``TestPassGate`` under
    ``"verification"`` would otherwise pass every structural check while
    reporting the wrong gate in every failure message.

    ``project_root`` is the collaborator the three suite-backed gates need:
    it is where their pytest observation runs. Omitting it does not produce
    permissive gates — it produces gates that raise
    ``GateStateUnavailableError`` when evaluated, because a gate with no way
    to see the tests must fail loudly rather than wave the run through.
    """
    probe = PytestSuiteProbe(project_root=project_root) if project_root is not None else None
    registry: dict[str, QualityGate] = {
        "completion": _gates.CompletionGate(),
        "test_pass": _gates.TestPassGate(probe),
        "red_phase": _gates.RedPhaseGate(probe),
        "verification": _gates.VerificationGate(probe),
        "review_approval": _gates.ReviewApprovalGate(),
        "merge_preflight_passed": _gates.MergePreflightGate(),
        "sage_correction_resolved": _gates.SageCorrectionResolvedGate(),
    }
    if budget_usd is not None:
        registry["cost_limit"] = _gates.CostLimitGate(budget_usd=budget_usd)
    return registry


def build_default_handlers(
    *,
    project_root: Path,
    backend: AgentBackend,
    bus: EventBus,
    config: PipelineConfig,
    settings: BonfireSettings,
    repo_slug: str | None = None,
    base_branch: str = "main",
) -> dict[str, StageHandler]:
    """Return the built-in handler registry, keyed by ``StageSpec.handler_name``.

    ``project_root`` is also where the reviewer records its verdict, so the
    run leaves ``.bonfire/review-verdict.json`` beside the repository it
    reviewed rather than only in the envelope it returns.

    Covers every ``handler_name`` any built-in workflow names.
    ``ArchitectHandler`` is deliberately absent: no built-in plan references
    it, and constructing it would require a knowledge-vault backend from the
    optional ``knowledge`` extra. Registering a handler no plan can reach
    would add an import cost and a failure mode for nothing.
    """
    from bonfire.git.scratch import ScratchWorktreeFactory
    from bonfire.git.workflow import GitWorkflow
    from bonfire.github.client import GitHubClient, detect_github_repo
    from bonfire.handlers.bard import BardHandler
    from bonfire.handlers.merge_preflight import MergePreflightHandler
    from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler
    from bonfire.handlers.steward import StewardHandler
    from bonfire.handlers.wizard import WizardHandler

    slug = detect_github_repo(project_root) if repo_slug is None else repo_slug
    github_client: Any = (
        GitHubClient(slug)
        if slug
        else UnconfiguredGitHubClient(f"no GitHub 'origin' remote was found for {project_root}")
    )
    git_workflow = GitWorkflow(project_root)

    return {
        "bard": BardHandler(
            git_workflow=git_workflow,
            github_client=github_client,
            base_branch=base_branch,
            config=config,
        ),
        "wizard": WizardHandler(
            github_client=github_client,
            backend=backend,
            config=config,
            event_bus=bus,
            settings=settings,
            project_root=project_root,
        ),
        "merge_preflight": MergePreflightHandler(
            github_client=github_client,
            scratch_worktree_factory=ScratchWorktreeFactory(project_root),
            repo_path=project_root,
            base_branch=base_branch,
        ),
        "sage_correction_bounce": SageCorrectionBounceHandler(
            backend=backend,
            git_workflow=git_workflow,
            config=config,
            github_client=github_client,
            repo_path=project_root,
            event_bus=bus,
        ),
        "steward": StewardHandler(github_client=github_client),
    }


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def validate_plan_wiring(
    plan: WorkflowPlan,
    *,
    handlers: dict[str, StageHandler],
    gates: dict[str, QualityGate],
) -> None:
    """Raise :class:`PipelineWiringError` if *plan* names anything unregistered.

    Checks every ``handler_name`` and every entry of every stage's ``gates``
    against the registries the engine is about to be given, and reports *all*
    missing names at once — fixing them one run at a time would mean paying
    for the earlier stages again on each attempt.

    The gate half is the load-bearing half. A missing handler eventually
    surfaces as a failed stage; a missing gate never surfaces at all, because
    the engine bypasses it and the stage is reported as having passed its
    quality checks. Refusing to start is the only way that becomes visible.
    """
    missing_handlers: list[tuple[str, str]] = []
    missing_gates: list[tuple[str, str]] = []
    for stage in plan.stages:
        if stage.handler_name is not None and stage.handler_name not in handlers:
            missing_handlers.append((stage.name, stage.handler_name))
        for gate_name in stage.gates:
            if gate_name not in gates:
                missing_gates.append((stage.name, gate_name))

    if not missing_handlers and not missing_gates:
        return

    lines = [f"Workflow '{plan.name}' names wiring the engine does not have."]
    for stage_name, handler_name in missing_handlers:
        lines.append(
            f"  unknown handler '{handler_name}' (stage '{stage_name}'); "
            f"registered: {', '.join(sorted(handlers)) or '(none)'}"
        )
    for stage_name, gate_name in missing_gates:
        lines.append(
            f"  unknown gate '{gate_name}' (stage '{stage_name}'); "
            f"registered: {', '.join(sorted(gates)) or '(none)'}"
        )
    lines.append(
        "Refusing to run: an unregistered gate is bypassed by the engine and "
        "counted as a pass, so the run would report quality it never checked."
    )
    raise PipelineWiringError("\n".join(lines))


# ---------------------------------------------------------------------------
# The root itself
# ---------------------------------------------------------------------------


def build_default_engine(
    plan: WorkflowPlan,
    *,
    project_root: Path | None = None,
) -> PipelineEngine:
    """Build the engine a real ``bonfire run`` executes, fully wired.

    Validates *plan* against the registries before returning, so a plan the
    engine cannot honour fails here rather than partway through a billed run.

    Args:
        plan: The workflow about to be executed. Used for the wiring check
            and to size the cost gate against the plan's budget.
        project_root: Override for the detected repository root. Tests pass
            this; the CLI does not.

    Raises:
        PipelineWiringError: If *plan* names an unregistered handler or gate.
    """
    from bonfire.cost.consumer import CostLedgerConsumer
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
    from bonfire.dispatch.tool_policy import DefaultToolPolicy
    from bonfire.engine.factory import load_settings_or_default
    from bonfire.engine.pipeline import PipelineEngine
    from bonfire.events.bus import EventBus

    root = resolve_project_root() if project_root is None else project_root.resolve()
    settings = load_settings_or_default()
    bus = EventBus()
    # The bus with nothing on it was a wallet hole: every dispatch emitted its
    # cost, no consumer was subscribed, so a run that spent real money left no
    # ledger and ``bonfire cost`` answered $0.00 forever.
    CostLedgerConsumer().register(bus)
    backend = ClaudeSDKBackend(bus=bus)

    handlers = build_default_handlers(
        project_root=root,
        backend=backend,
        bus=bus,
        config=settings.bonfire,
        settings=settings,
    )
    gate_registry = build_default_gates(budget_usd=plan.budget_usd, project_root=root)
    validate_plan_wiring(plan, handlers=handlers, gates=gate_registry)

    tool_policy: ToolPolicy = DefaultToolPolicy()
    return PipelineEngine(
        backend=backend,
        bus=bus,
        config=settings.bonfire,
        handlers=handlers,
        gate_registry=gate_registry,
        project_root=root,
        tool_policy=tool_policy,
        settings=settings,
    )
