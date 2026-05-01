"""Research workflow factories — parallel scouts converging on a sage.

Research workflows are about gathering diverse perspectives before synthesis.
Multiple scouts explore the problem space in parallel; a sage distills
their findings into a coherent recommendation.
"""

from __future__ import annotations

from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType


def _scout(name: str, *, parallel_group: str) -> StageSpec:
    """Build a scout stage with a parallel group assignment."""
    return StageSpec(
        name=name,
        agent_name=name,
        role="scout",
        parallel_group=parallel_group,
    )


def _sage(name: str, *, depends_on: list[str]) -> StageSpec:
    """Build a sage stage that synthesizes scout outputs."""
    return StageSpec(
        name=name,
        agent_name=name,
        role="sage",
        depends_on=depends_on,
    )


def _multi_scout_workflow(
    name: str,
    *,
    scout_count: int,
    description: str = "",
) -> WorkflowPlan:
    """Shared factory for N-scout + sage research workflows.

    ``dual_scout()`` and ``spike()`` are aliases — same shape, two names by intent.
    """
    group = f"{name}_scouts"
    scout_names = [f"scout_{i + 1}" for i in range(scout_count)]
    scouts = [_scout(sn, parallel_group=group) for sn in scout_names]

    return WorkflowPlan(
        name=name,
        workflow_type=WorkflowType.RESEARCH,
        description=description,
        stages=[*scouts, _sage("sage", depends_on=scout_names)],
    )


def dual_scout() -> WorkflowPlan:
    """Two parallel scouts with competing perspectives, synthesized by a sage.

    The dual workflow is Bonfire's signature: two scouts attack the same
    problem from different angles, and the sage picks the best of both.
    """
    return _multi_scout_workflow(
        "dual_scout",
        scout_count=2,
        description="Two parallel scouts synthesized by a sage.",
    )


def triple_scout() -> WorkflowPlan:
    """Three parallel scouts for deep research, synthesized by a sage.

    When the problem space is large or contentious, three perspectives
    reduce blind spots. The sage weighs all three before recommending.
    """
    return _multi_scout_workflow(
        "triple_scout",
        scout_count=3,
        description="Three parallel scouts synthesized by a sage.",
    )


def spike() -> WorkflowPlan:
    """Research spike — scouts explore, sage synthesizes. No implementation.

    A spike is pure research: no knights, no warriors, no code.
    Used for architectural decisions, technology evaluation, and
    design exploration before committing to a build path.

    Structurally identical to ``dual_scout()`` (both call
    ``_multi_scout_workflow`` with ``scout_count=2``); the two are
    intentional aliases — ``spike()`` is the design-exploration vocabulary,
    ``dual_scout()`` is the build-research vocabulary.
    """
    return _multi_scout_workflow(
        "spike",
        scout_count=2,
        description="Research spike: scouts explore, sage synthesizes. No code.",
    )
