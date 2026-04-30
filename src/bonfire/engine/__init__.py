"""Pipeline execution engine — the heart of Bonfire.

This package walks a frozen :class:`~bonfire.models.plan.WorkflowPlan`
in topological order and turns each stage into an envelope-carrying
agent dispatch with quality gates, checkpoints, and observable cost.

Public surface:

- :class:`PipelineEngine` / :class:`PipelineResult` — top-level
  orchestrator and its terminal result type.
- :class:`StageExecutor` — runs a single stage: build input, dispatch
  the handler, evaluate gates, emit events.
- :class:`ContextBuilder` — assembles per-stage prompt context from
  prior stage results and project state.
- The six shipped quality gates (:class:`CompletionGate`,
  :class:`TestPassGate`, :class:`RedPhaseGate`,
  :class:`VerificationGate`, :class:`ReviewApprovalGate`,
  :class:`CostLimitGate`) plus :class:`GateChain` for sequential
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
    RedPhaseGate,
    ReviewApprovalGate,
    SageCorrectionResolvedGate,  # noqa: F401 -- not in __all__; reachable via package attr access
    TestPassGate,
    VerificationGate,
)
from bonfire.engine.pipeline import PipelineEngine, PipelineResult

# ``MergePreflightGate`` and ``SageCorrectionResolvedGate`` are intentionally
# NOT in ``__all__`` -- the canonical 14-symbol surface is locked by
# ``tests/unit/test_engine_init.py``. ``SageCorrectionResolvedGate`` is
# imported here so it is available via attribute access on the package
# (``hasattr(bonfire.engine, "SageCorrectionResolvedGate")``); promoting
# it to ``__all__`` is a follow-up decision once the 14-surface lock is
# widened. ``MergePreflightGate`` is reachable only via the submodule
# (``from bonfire.engine.gates import MergePreflightGate``).

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
    "StageExecutor",
    "TestPassGate",
    "VerificationGate",
]
