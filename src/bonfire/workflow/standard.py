# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Standard workflow factories — the bread and butter of Bonfire pipelines.

These factories produce immutable WorkflowPlans for common build patterns.
Each factory returns a DAG-validated, frozen plan ready for the engine.
"""

from __future__ import annotations

from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType


def _stage(
    name: str,
    role: str,
    *,
    handler_name: str | None = None,
    gates: list[str] | None = None,
    on_gate_failure: str | None = None,
    depends_on: list[str] | None = None,
    max_iterations: int = 1,
    parallel_group: str | None = None,
) -> StageSpec:
    """Build a StageSpec with sensible defaults — less noise, more signal."""
    return StageSpec(
        name=name,
        agent_name=name,
        role=role,
        handler_name=handler_name,
        gates=gates or [],
        on_gate_failure=on_gate_failure,
        depends_on=depends_on or [],
        max_iterations=max_iterations,
        parallel_group=parallel_group,
    )


def standard_build() -> WorkflowPlan:
    """The reference 9-stage TDD build pipeline.

    Flow: scout -> knight -> warrior -> prover -> sage_correction_bounce ->
    bard -> wizard -> merge_preflight -> steward.

    Three on_gate_failure bounces target the warrior (from prover,
    sage_correction_bounce, and wizard). MergePreflight runs full-suite
    pytest against the simulated merged tip before the merge button
    (Sage memo ``bon-519-sage-20260428T033101Z.md`` §D6 lines 530-544).
    """
    return WorkflowPlan(
        name="standard_build",
        workflow_type=WorkflowType.STANDARD,
        description="Full TDD build pipeline: scout through steward with quality gates.",
        stages=[
            _stage("scout", "scout"),
            _stage("knight", "knight", gates=["completion"]),
            _stage(
                "warrior",
                "warrior",
                gates=["test_pass"],
                max_iterations=3,
                depends_on=["knight"],
            ),
            _stage(
                "prover",
                "prover",
                gates=["verification"],
                on_gate_failure="warrior",
                depends_on=["warrior"],
            ),
            _stage(
                "sage_correction_bounce",
                "synthesizer",
                handler_name="sage_correction_bounce",
                gates=["sage_correction_resolved"],
                on_gate_failure="warrior",
                depends_on=["prover"],
            ),
            _stage(
                "bard",
                "bard",
                handler_name="bard",
                depends_on=["sage_correction_bounce"],
            ),
            _stage(
                "wizard",
                "wizard",
                handler_name="wizard",
                gates=["review_approval"],
                on_gate_failure="warrior",
                depends_on=["bard"],
            ),
            _stage(
                "merge_preflight",
                "verifier",
                handler_name="merge_preflight",
                gates=["merge_preflight_passed"],
                depends_on=["wizard"],
            ),
            _stage(
                "steward",
                "steward",
                handler_name="steward",
                depends_on=["merge_preflight"],
            ),
        ],
    )


def debug() -> WorkflowPlan:
    """Minimal 2-stage workflow for quick iteration.

    Flow: scout -> warrior

    No gates, no bounce-back. Useful for debugging and rapid prototyping
    where the full ceremony of the standard pipeline is overkill.
    """
    return WorkflowPlan(
        name="debug",
        workflow_type=WorkflowType.DEBUG,
        description="Minimal scout-warrior pipeline for rapid iteration.",
        stages=[
            _stage("scout", "scout"),
            _stage("warrior", "warrior", depends_on=["scout"]),
        ],
    )
