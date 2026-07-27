# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The composition root -- what a real ``bonfire run`` is actually wired with.

``PipelineEngine`` takes every collaborator by keyword and defaults each one
to empty:

    self._handlers = handlers or {}
    self._gates = gate_registry or {}

That is the right shape for a testable engine and the wrong shape for a
caller who forgets an argument, because both omissions are silent. An
unregistered handler surfaces as a stage failure partway through a paid run;
an unregistered gate does not surface at all -- ``_evaluate_gates`` emits
``QualityBypassed`` and continues, so a missing gate reads as a passing one.

This module is the single place that answers "what does a user get?", and it
answers it eagerly:

* :func:`build_default_gates` and :func:`build_default_handlers` return the
  full built-in registries rather than the subset some plan happens to need.
* :func:`validate_plan_wiring` refuses a plan naming anything those registries
  cannot supply, raising :class:`WiringError` *before* the engine starts and
  therefore before a single dollar is spent.
* :func:`build_default_engine` passes ``project_root``, which is what stops
  the dispatched agent from ingesting a foreign repository's ``CLAUDE.md``
  (see :func:`bonfire.dispatch.sdk_backend._resolve_setting_sources`: an empty
  ``cwd`` means "the caller's own tree" and is trusted by default, so omitting
  ``project_root`` is what grants that trust, not what withholds it).

Why this file exists at all: the previous composition root lived inline in
``bonfire.cli.commands.run._default_engine`` and carried the note "Unit tests
never call this -- they inject their own factory". The one function deciding
what users get was the one nothing exercised. Keeping the wiring here, in
functions with no I/O in their signatures, is what makes
``tests/unit/test_engine_composition.py`` able to call the real thing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.engine.gates import (
    CompletionGate,
    CostLimitGate,
    MergePreflightGate,
    RedPhaseGate,
    ReviewApprovalGate,
    SageCorrectionResolvedGate,
    TestPassGate,
    VerificationGate,
)

if TYPE_CHECKING:
    from bonfire.engine.pipeline import PipelineEngine
    from bonfire.events.bus import EventBus
    from bonfire.models.config import BonfireSettings, PipelineConfig
    from bonfire.models.plan import WorkflowPlan
    from bonfire.protocols import AgentBackend, QualityGate, StageHandler

__all__ = [
    "WiringError",
    "build_default_engine",
    "build_default_gates",
    "build_default_handlers",
    "validate_plan_wiring",
]


class WiringError(RuntimeError):
    """A plan names a handler or gate the composition root cannot supply.

    Typed rather than a bare ``RuntimeError`` so the CLI can render it as a
    configuration problem (exit 2) instead of a run failure (exit 1): nothing
    ran, nothing was billed, and the user's next move is to fix the workflow
    definition, not to retry.
    """


def build_default_gates(*, budget_usd: float) -> dict[str, QualityGate]:
    """Return every built-in quality gate, keyed by its workflow-facing name.

    The keys are the strings workflow factories put in ``StageSpec.gates``.
    They are written out here rather than derived from the gate classes
    because the engine looks a gate up by this key and the gate reports a
    ``gate_name`` of its own; the two are separate values that must agree.
    ``test_registry_keys_match_emitted_gate_names`` asserts the agreement, so
    a typo here fails loudly instead of registering a gate nobody can reach.

    Args:
        budget_usd: Ceiling handed to :class:`CostLimitGate`. Callers pass the
            pipeline config's ``max_budget_usd`` so the gate and the engine's
            own budget watchdog agree on the number.
    """
    return {
        "completion": CompletionGate(),
        "test_pass": TestPassGate(),
        "red_phase": RedPhaseGate(),
        "verification": VerificationGate(),
        "review_approval": ReviewApprovalGate(),
        "cost_limit": CostLimitGate(budget_usd=budget_usd),
        "merge_preflight_passed": MergePreflightGate(),
        "sage_correction_resolved": SageCorrectionResolvedGate(),
    }


def _build_github_client(project_root: Path) -> object:
    """Build the ``gh``-backed client for the repository at *project_root*.

    ``detect_github_repo`` returns ``""`` on every failure path -- no remote,
    not a git tree, remote is not GitHub, ``git`` missing, timeout. Turning
    that empty string into a client would produce a handler that fails on its
    first call with an unrelated message, so it is refused here instead.

    Raises:
        WiringError: If no GitHub ``owner/repo`` slug can be determined.
    """
    from bonfire.github import GitHubClient, detect_github_repo

    slug = detect_github_repo(project_root)
    if not slug:
        raise WiringError(
            f"No GitHub repository detected at {project_root}. The handler stages "
            "(bard, wizard, merge_preflight, steward, sage_correction_bounce) open "
            "pull requests and read review state, so they need a git checkout whose "
            "'origin' remote points at GitHub. Run from such a checkout, or choose a "
            "workflow with no handler stages (for example --workflow debug)."
        )
    return GitHubClient(slug)


def build_default_handlers(
    *,
    project_root: Path,
    backend: AgentBackend,
    config: PipelineConfig,
    bus: EventBus | None = None,
    github_client: object | None = None,
) -> dict[str, StageHandler]:
    """Return every built-in stage handler, keyed by its ``handler_name``.

    The keys are the strings workflow factories put in
    ``StageSpec.handler_name``.

    ``ArchitectHandler`` is deliberately absent: no registered workflow names
    it, and it requires a ``VaultBackend`` from the optional ``[knowledge]``
    extra. Registering it would drag that extra into every run to serve a
    stage nothing dispatches. A plan that does name ``architect`` gets a
    :class:`WiringError` from :func:`validate_plan_wiring`, which is the
    honest answer.

    Args:
        project_root: The repository the pipeline operates on. Also the root
            for git worktree operations.
        backend: Agent backend shared with the engine, used by the reviewer
            and synthesizer-correction handlers for their own dispatches.
        config: Pipeline config, forwarded to handlers that size their own
            dispatches from it.
        bus: Event bus, so handler-internal dispatches reach the same
            observers as engine-driven ones.
        github_client: Injection seam for tests. Built from *project_root*
            when omitted.

    Raises:
        WiringError: If *github_client* is omitted and no GitHub repository
            can be detected at *project_root*.
    """
    from bonfire.git import GitWorkflow, ScratchWorktreeFactory
    from bonfire.handlers import (
        BardHandler,
        MergePreflightHandler,
        SageCorrectionBounceHandler,
        StewardHandler,
        WizardHandler,
    )

    client = github_client if github_client is not None else _build_github_client(project_root)
    git_workflow = GitWorkflow(project_root)

    return {
        "bard": BardHandler(
            git_workflow=git_workflow,
            github_client=client,
            config=config,
        ),
        "wizard": WizardHandler(
            github_client=client,
            backend=backend,
            config=config,
            event_bus=bus,
        ),
        "sage_correction_bounce": SageCorrectionBounceHandler(
            backend=backend,
            git_workflow=git_workflow,
            github_client=client,
            config=config,
            repo_path=project_root,
            event_bus=bus,
        ),
        "merge_preflight": MergePreflightHandler(
            github_client=client,
            scratch_worktree_factory=ScratchWorktreeFactory(project_root),
            repo_path=project_root,
        ),
        "steward": StewardHandler(github_client=client),
    }


def validate_plan_wiring(
    plan: WorkflowPlan,
    *,
    handlers: dict[str, StageHandler],
    gates: dict[str, QualityGate],
) -> None:
    """Refuse *plan* if it names a handler or gate the registries lack.

    This is the loud half of the fix. Without it the two omissions fail in
    two different quiet ways -- a handler as a stage error partway through a
    billed run, a gate not at all -- and only one of them is visible.

    Raises:
        WiringError: Listing every missing name and what is registered. Both
            categories are reported together so one round of fixing is
            enough.
    """
    missing_handlers = sorted(
        {
            stage.handler_name
            for stage in plan.stages
            if stage.handler_name and stage.handler_name not in handlers
        }
    )
    missing_gates = sorted(
        {gate for stage in plan.stages for gate in stage.gates if gate not in gates}
    )
    if not missing_handlers and not missing_gates:
        return

    problems: list[str] = []
    if missing_handlers:
        problems.append(f"unregistered handler(s): {', '.join(missing_handlers)}")
    if missing_gates:
        problems.append(f"unregistered gate(s): {', '.join(missing_gates)}")

    raise WiringError(
        f"Workflow '{plan.name}' cannot run -- {'; '.join(problems)}. "
        f"Registered handlers: {', '.join(sorted(handlers)) or '(none)'}. "
        f"Registered gates: {', '.join(sorted(gates)) or '(none)'}. "
        "Nothing was dispatched and nothing was billed."
    )


def build_default_engine(
    plan: WorkflowPlan,
    *,
    project_root: Path | None = None,
    settings: BonfireSettings | None = None,
) -> PipelineEngine:
    """Build the engine a real ``bonfire run`` uses, wired and validated.

    Handlers are built only when *plan* actually has a stage naming one. The
    handler set needs a GitHub checkout; the scout-only and debug workflows do
    not, and refusing to run them outside a GitHub repository would be a cost
    with no matching benefit.

    Args:
        plan: The plan about to run. Used to validate wiring and to decide
            whether handlers are needed at all.
        project_root: Repository to operate on. Defaults to the process cwd.
            Passed through to the engine, where it becomes the dispatch
            ``cwd`` and therefore governs whether the target repository's
            ``CLAUDE.md`` / ``.claude/settings.json`` are trusted.
        settings: Loaded settings. Loaded from ``bonfire.toml`` + env when
            omitted.

    Raises:
        WiringError: If the plan names an unregistered handler or gate, or if
            it needs handlers and no GitHub repository can be detected.
    """
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
    from bonfire.dispatch.tool_policy import DefaultToolPolicy
    from bonfire.engine.factory import load_settings_or_default
    from bonfire.engine.pipeline import PipelineEngine
    from bonfire.events.bus import EventBus

    root = Path(project_root) if project_root is not None else Path.cwd()
    resolved = settings if settings is not None else load_settings_or_default()
    config = resolved.bonfire

    bus = EventBus()
    backend = ClaudeSDKBackend(bus=bus)

    handlers: dict[str, StageHandler] = {}
    if any(stage.handler_name for stage in plan.stages):
        handlers = build_default_handlers(
            project_root=root,
            backend=backend,
            config=config,
            bus=bus,
        )
    gates = build_default_gates(budget_usd=config.max_budget_usd)

    validate_plan_wiring(plan, handlers=handlers, gates=gates)

    return PipelineEngine(
        backend=backend,
        bus=bus,
        config=config,
        handlers=handlers,
        gate_registry=gates,
        project_root=root,
        tool_policy=DefaultToolPolicy(),
        settings=resolved,
    )
