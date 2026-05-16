# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Bonfire event types — 28 events across 9 categories.

Explicit, hand-built, zero magic. Every event class defined by hand.
The union is a manual Union[...]. The registry is a plain dict at the bottom.
Grep-friendly, no metaclass risk with Pydantic.

Depends only on pydantic. Python 3.12+.
"""

from __future__ import annotations

import re
import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter, field_validator

# ---------------------------------------------------------------------------
# session_id validation
# ---------------------------------------------------------------------------
# ``session_id`` is interpolated into filesystem paths at multiple sites
# (``session/persistence.py`` writes ``{session_id}.jsonl``; ``engine/
# checkpoint.py`` writes ``{session_id}.json``). Without validation, an
# attacker-controlled session_id of ``../../etc/passwd`` or
# ``..\\..\\Windows`` would yield arbitrary-path interpolation —
# path-traversal smuggling into operator-controlled write sites.
#
# Pattern: alphanumerics + ``_`` + ``-``, 1-64 chars. Permissive enough for
# uuid4-hex (default, 12 chars), human-readable slugs, and existing test
# fixtures (``sess-1``, ``ses_001``, ``session_under_attack``). Strict
# enough to reject ``..``, ``/``, ``\\``, null bytes, control chars, and
# any other path-traversal smuggling shape.
#
# The empty-string sentinel is preserved separately for ``BonfireEvent``
# subclasses (``AxiomLoaded``) that legitimately emit outside session
# context — see ``_validate_session_id`` below.
#
# The anchor MUST be ``\Z`` (true end-of-string), not ``$``.
# In MULTILINE mode ``$`` matches at any line boundary; in default mode
# it matches just before a single trailing ``\n``. A session_id of
# ``abc\n`` would slip through the ``$`` form and be interpolated into
# filesystem paths with the newline preserved (a log-injection /
# display-corruption shape). ``\Z`` anchors at the actual end of the
# string and refuses the trailing-newline shape outright.
_SESSION_ID_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,64}\Z")


def _validate_session_id(value: str) -> str:
    """Reject path-traversal and other dangerous shapes in session_id.

    Empty string is allowed for ``AxiomLoaded`` and other events that
    legitimately emit outside session context (default-state sentinel).
    Non-empty strings must match ``_SESSION_ID_RE``.
    """
    if value == "":
        return value
    if not _SESSION_ID_RE.match(value):
        msg = (
            f"invalid session_id {value!r}: must match {_SESSION_ID_RE.pattern} "
            f"(alphanumerics, '_', '-'; 1-64 chars). Rejected to prevent "
            "path-traversal smuggling into session/checkpoint file paths."
        )
        raise ValueError(msg)
    return value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_id() -> str:
    """Generate a 12-char hex event id from uuid4."""
    return uuid4().hex[:12]


def _utcnow() -> float:
    """UTC timestamp as a float (seconds since epoch)."""
    return time.time()


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


class BonfireEvent(BaseModel):
    """Immutable base for all Bonfire events.

    Subclasses MUST define a class-level ``event_type`` as a
    ``Literal["category.action"]`` field with a default value.
    """

    model_config = {"frozen": True}

    event_id: str = Field(default_factory=_make_event_id)
    timestamp: float = Field(default_factory=_utcnow)
    session_id: str
    sequence: int
    # event_type is defined per-subclass as a Literal field

    # session_id is interpolated into filesystem paths downstream
    # (session/persistence.py, engine/checkpoint.py). Reject path-traversal
    # shapes (``..``, ``/``, ``\\``, null) at the model boundary so the
    # write sites cannot be smuggled past their parent directory. Empty
    # string is allowed for AxiomLoaded and similar outside-session events.
    @field_validator("session_id")
    @classmethod
    def _session_id_must_be_path_safe(cls, v: str) -> str:
        return _validate_session_id(v)

    @property
    def category(self) -> str:
        """Return the category prefix of the event_type (e.g. 'pipeline')."""
        return self.event_type.split(".")[0]


# ---------------------------------------------------------------------------
# Pipeline events (4)
# ---------------------------------------------------------------------------


class PipelineStarted(BonfireEvent):
    event_type: Literal["pipeline.started"] = "pipeline.started"
    plan_name: str
    budget_usd: float


class PipelineCompleted(BonfireEvent):
    event_type: Literal["pipeline.completed"] = "pipeline.completed"
    total_cost_usd: float
    duration_seconds: float
    stages_completed: int


class PipelineFailed(BonfireEvent):
    event_type: Literal["pipeline.failed"] = "pipeline.failed"
    failed_stage: str
    error_message: str
    # Cumulative cost the engine accounted for through the halt point.
    # Symmetric with ``PipelineCompleted.total_cost_usd`` so bus
    # observers can reconstruct ``PipelineResult.total_cost_usd`` on
    # either the success OR the failure path. Default ``0.0`` keeps
    # legacy emitters round-tripping without raising.
    total_cost_usd: float = 0.0


class PipelinePaused(BonfireEvent):
    event_type: Literal["pipeline.paused"] = "pipeline.paused"
    reason: str
    checkpoint_path: str


# ---------------------------------------------------------------------------
# Stage events (4)
# ---------------------------------------------------------------------------


class StageStarted(BonfireEvent):
    event_type: Literal["stage.started"] = "stage.started"
    stage_name: str
    agent_name: str


class StageCompleted(BonfireEvent):
    event_type: Literal["stage.completed"] = "stage.completed"
    stage_name: str
    agent_name: str
    duration_seconds: float
    cost_usd: float


class StageFailed(BonfireEvent):
    event_type: Literal["stage.failed"] = "stage.failed"
    stage_name: str
    agent_name: str
    error_message: str


class StageSkipped(BonfireEvent):
    event_type: Literal["stage.skipped"] = "stage.skipped"
    stage_name: str
    reason: str


# ---------------------------------------------------------------------------
# Dispatch events (4)
# ---------------------------------------------------------------------------


class DispatchStarted(BonfireEvent):
    event_type: Literal["dispatch.started"] = "dispatch.started"
    agent_name: str
    model: str


class DispatchCompleted(BonfireEvent):
    event_type: Literal["dispatch.completed"] = "dispatch.completed"
    agent_name: str
    cost_usd: float
    duration_seconds: float
    model: str = ""


class DispatchFailed(BonfireEvent):
    event_type: Literal["dispatch.failed"] = "dispatch.failed"
    agent_name: str
    error_message: str
    # Accumulated cost the runner charged across every attempt that ran
    # before this failure was emitted. Symmetric with
    # ``DispatchCompleted.cost_usd`` so a single subscriber that sums
    # both events reconstructs total dispatch spend even on flaky-but-
    # eventually-failed paths. Default ``0.0`` keeps legacy emitters
    # round-tripping without raising.
    cost_usd: float = 0.0


class DispatchRetry(BonfireEvent):
    event_type: Literal["dispatch.retry"] = "dispatch.retry"
    agent_name: str
    attempt: int
    reason: str


# ---------------------------------------------------------------------------
# Quality events (3)
# ---------------------------------------------------------------------------


class QualityPassed(BonfireEvent):
    event_type: Literal["quality.passed"] = "quality.passed"
    gate_name: str
    stage_name: str


class QualityFailed(BonfireEvent):
    event_type: Literal["quality.failed"] = "quality.failed"
    gate_name: str
    stage_name: str = ""
    severity: str = "error"
    message: str


class QualityBypassed(BonfireEvent):
    event_type: Literal["quality.bypassed"] = "quality.bypassed"
    gate_name: str
    stage_name: str
    reason: str


# ---------------------------------------------------------------------------
# Git events (4)
# ---------------------------------------------------------------------------


class GitBranchCreated(BonfireEvent):
    event_type: Literal["git.branch_created"] = "git.branch_created"
    branch_name: str


class GitCommitCreated(BonfireEvent):
    event_type: Literal["git.commit_created"] = "git.commit_created"
    sha: str
    message: str


class GitPRCreated(BonfireEvent):
    event_type: Literal["git.pr_created"] = "git.pr_created"
    pr_number: int
    pr_url: str


class GitPRMerged(BonfireEvent):
    event_type: Literal["git.pr_merged"] = "git.pr_merged"
    pr_number: int


# ---------------------------------------------------------------------------
# Cost events (3)
# ---------------------------------------------------------------------------


class CostAccrued(BonfireEvent):
    event_type: Literal["cost.accrued"] = "cost.accrued"
    amount_usd: float
    source: str
    running_total_usd: float


class CostBudgetWarning(BonfireEvent):
    event_type: Literal["cost.budget_warning"] = "cost.budget_warning"
    current_usd: float
    budget_usd: float
    percent: float


class CostBudgetExceeded(BonfireEvent):
    event_type: Literal["cost.budget_exceeded"] = "cost.budget_exceeded"
    current_usd: float
    budget_usd: float


# ---------------------------------------------------------------------------
# Session events (2)
# ---------------------------------------------------------------------------


class SessionStarted(BonfireEvent):
    event_type: Literal["session.started"] = "session.started"
    task: str
    workflow: str


class SessionEnded(BonfireEvent):
    event_type: Literal["session.ended"] = "session.ended"
    status: str
    total_cost_usd: float


# ---------------------------------------------------------------------------
# XP events (3)
# ---------------------------------------------------------------------------


class XPAwarded(BonfireEvent):
    event_type: Literal["xp.awarded"] = "xp.awarded"
    amount: int
    reason: str


class XPPenalty(BonfireEvent):
    event_type: Literal["xp.penalty"] = "xp.penalty"
    amount: int
    reason: str


class XPRespawn(BonfireEvent):
    event_type: Literal["xp.respawn"] = "xp.respawn"
    checkpoint: str
    reason: str


# ---------------------------------------------------------------------------
# Axiom events (1)
# ---------------------------------------------------------------------------


class AxiomLoaded(BonfireEvent):
    """Emitted when an axiom is loaded during prompt compilation.

    Defaults for session_id/sequence allow emission outside session context.
    """

    event_type: Literal["axiom.loaded"] = "axiom.loaded"
    session_id: str = ""
    sequence: int = 0
    role: str
    axiom_version: str
    cognitive_pattern: Literal[
        "observe",
        "contract",
        "execute",
        "synthesize",
        "audit",
        "publish",
        "announce",
    ] = "observe"


# ---------------------------------------------------------------------------
# Security events (1)
# ---------------------------------------------------------------------------


class SecurityDenied(BonfireEvent):
    """Emitted when the pre-exec security hook denies (or warns on) a tool call.

    Covers both DENY and WARN paths. WARN emissions prefix ``reason`` with
    ``"WARN: "``; consumers filtering DENY-only check ``not reason.startswith("WARN:")``.
    """

    event_type: Literal["security.denial"] = "security.denial"
    tool_name: str
    reason: str
    pattern_id: str
    agent_name: str = ""


# ---------------------------------------------------------------------------
# Discriminated union — manual, explicit, every type listed
# ---------------------------------------------------------------------------

BonfireEventUnion = Annotated[
    PipelineStarted
    | PipelineCompleted
    | PipelineFailed
    | PipelinePaused
    | StageStarted
    | StageCompleted
    | StageFailed
    | StageSkipped
    | DispatchStarted
    | DispatchCompleted
    | DispatchFailed
    | DispatchRetry
    | QualityPassed
    | QualityFailed
    | QualityBypassed
    | GitBranchCreated
    | GitCommitCreated
    | GitPRCreated
    | GitPRMerged
    | CostAccrued
    | CostBudgetWarning
    | CostBudgetExceeded
    | SessionStarted
    | SessionEnded
    | XPAwarded
    | XPPenalty
    | XPRespawn
    | AxiomLoaded
    | SecurityDenied,
    Field(discriminator="event_type"),
]

event_adapter: TypeAdapter[BonfireEventUnion] = TypeAdapter(BonfireEventUnion)

# ---------------------------------------------------------------------------
# Registry — plain dict, hand-built, grep-friendly
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[str, type[BonfireEvent]] = {
    "pipeline.started": PipelineStarted,
    "pipeline.completed": PipelineCompleted,
    "pipeline.failed": PipelineFailed,
    "pipeline.paused": PipelinePaused,
    "stage.started": StageStarted,
    "stage.completed": StageCompleted,
    "stage.failed": StageFailed,
    "stage.skipped": StageSkipped,
    "dispatch.started": DispatchStarted,
    "dispatch.completed": DispatchCompleted,
    "dispatch.failed": DispatchFailed,
    "dispatch.retry": DispatchRetry,
    "quality.passed": QualityPassed,
    "quality.failed": QualityFailed,
    "quality.bypassed": QualityBypassed,
    "git.branch_created": GitBranchCreated,
    "git.commit_created": GitCommitCreated,
    "git.pr_created": GitPRCreated,
    "git.pr_merged": GitPRMerged,
    "cost.accrued": CostAccrued,
    "cost.budget_warning": CostBudgetWarning,
    "cost.budget_exceeded": CostBudgetExceeded,
    "session.started": SessionStarted,
    "session.ended": SessionEnded,
    "xp.awarded": XPAwarded,
    "xp.penalty": XPPenalty,
    "xp.respawn": XPRespawn,
    "axiom.loaded": AxiomLoaded,
    "security.denial": SecurityDenied,
}
