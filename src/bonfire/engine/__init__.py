# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pipeline execution engine — the heart of Bonfire.

This package walks a frozen :class:`~bonfire.models.plan.WorkflowSpec`
in topological order and turns each stage into an envelope-carrying
agent dispatch with quality gates, checkpoints, and observable cost.

Public surface:

- :class:`PipelineEngine` / :class:`PipelineResult` — top-level
  orchestrator and its terminal result type.
- :class:`StageExecutor` — runs a single stage: build input, dispatch
  the handler, evaluate gates, emit events.
- :class:`ContextBuilder` — assembles per-stage prompt context from
  prior stage results and project state.
- The shipped quality gates (:class:`CompletionGate`,
  :class:`TestPassGate`, :class:`RedPhaseGate`,
  :class:`VerificationGate`, :class:`ReviewApprovalGate`,
  :class:`CostLimitGate`, :class:`SageCorrectionResolvedGate`,
  :class:`MergePreflightGate`) plus :class:`GateChain` for sequential
  evaluation with short-circuit on error severity.
- The checkpoint trio (:class:`CheckpointManager`,
  :class:`CheckpointData`, :class:`CheckpointSummary`) — durable
  resume state written between stages.
"""

from bonfire.engine.checkpoint import CheckpointData, CheckpointManager, CheckpointSummary
from bonfire.engine.context import ContextBuilder
from bonfire.engine.executor import StageExecutor
from bonfire.engine.gates import (
    CompletionGate,
    CostLimitGate,
    GateChain,
    MergePreflightGate,
    RedPhaseGate,
    ReviewApprovalGate,
    SageCorrectionResolvedGate,
    TestPassGate,
    VerificationGate,
)
from bonfire.engine.pipeline import PipelineEngine, PipelineResult

# Every shipped quality gate now surfaces in ``__all__``; no gate is
# intentionally excluded. The canonical 16-symbol surface is locked by
# ``tests/unit/test_engine_init.py``.

__all__ = [
    "CheckpointData",
    "CheckpointManager",
    "CheckpointSummary",
    "CompletionGate",
    "ContextBuilder",
    "CostLimitGate",
    "GateChain",
    "MergePreflightGate",
    "PipelineEngine",
    "PipelineResult",
    "RedPhaseGate",
    "ReviewApprovalGate",
    "SageCorrectionResolvedGate",
    "StageExecutor",
    "TestPassGate",
    "VerificationGate",
]
