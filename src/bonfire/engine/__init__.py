# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pipeline execution engine — the heart of Bonfire.

This package walks a frozen :class:`~bonfire.models.plan.WorkflowPlan`
in topological order and turns each stage into an envelope-carrying
agent dispatch with quality gates, observable cost, and an opt-in
checkpoint persistence surface.

Public surface:

- :class:`PipelineEngine` / :class:`PipelineResult` — top-level
  orchestrator and its terminal result type. ``PipelineEngine`` owns
  per-stage execution inline (``_execute_stage``); the historical
  standalone ``StageExecutor`` class was deleted after an audit
  surfaced divergence between the dead path and the live engine
  path (unreachable code, missing initial-envelope metadata merge,
  vault-advisor wired only through the dead path, and a
  model-override semantic gap).
- :class:`ContextBuilder` — assembles per-stage prompt context from
  prior stage results and project state.
- The six shipped quality gates (:class:`CompletionGate`,
  :class:`TestPassGate`, :class:`RedPhaseGate`,
  :class:`VerificationGate`, :class:`ReviewApprovalGate`,
  :class:`CostLimitGate`) plus :class:`GateChain` for sequential
  evaluation with short-circuit on error severity.
- The checkpoint trio (:class:`CheckpointManager`,
  :class:`CheckpointData`, :class:`CheckpointSummary`) — the
  persistence surface behind ``bonfire status`` / ``resume`` /
  ``handoff``. The engine writes a checkpoint at every stage-group
  boundary when its ``checkpoint_sink`` is wired, which is what the
  composition root does; a caller constructing an engine by hand and
  omitting the sink gets the previous behaviour, no writes. Resume is
  unchanged: pass a loaded ``CheckpointData.completed`` mapping back
  into :meth:`PipelineEngine.run` and the named stages are skipped,
  their cost seeded rather than spent again.
"""

from bonfire.engine.checkpoint import CheckpointData, CheckpointManager, CheckpointSummary
from bonfire.engine.context import ContextBuilder
from bonfire.engine.gates import (
    CompletionGate,
    CostLimitGate,
    GateChain,
    RedPhaseGate,
    ReviewApprovalGate,
    SageCorrectionResolvedGate,
    TestPassGate,
    VerificationGate,
)
from bonfire.engine.pipeline import PipelineEngine, PipelineResult

# ``MergePreflightGate`` is intentionally NOT in ``__all__`` here; the
# canonical 14-symbol surface is locked by ``tests/unit/test_engine_init.py``.
# It IS importable both from the package and from the submodule
# (``from bonfire.engine.gates import MergePreflightGate``). Promoting it
# to ``__all__`` is a follow-up decision.

__all__ = [
    "CheckpointData",
    "CheckpointManager",
    "CheckpointSummary",
    "CompletionGate",
    "ContextBuilder",
    "CostLimitGate",
    "GateChain",
    "PipelineEngine",
    "PipelineResult",
    "RedPhaseGate",
    "ReviewApprovalGate",
    "SageCorrectionResolvedGate",
    "TestPassGate",
    "VerificationGate",
]
