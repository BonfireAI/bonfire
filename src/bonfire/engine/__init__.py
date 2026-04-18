"""Pipeline execution engine -- the heart of Bonfire."""

from bonfire.engine.checkpoint import CheckpointData, CheckpointManager, CheckpointSummary
from bonfire.engine.context import ContextBuilder
from bonfire.engine.executor import StageExecutor
from bonfire.engine.gates import (
    CompletionGate,
    CostLimitGate,
    GateChain,
    RedPhaseGate,
    ReviewApprovalGate,
    TestPassGate,
    VerificationGate,
)
from bonfire.engine.pipeline import PipelineEngine, PipelineResult

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
