"""Envelope model and supporting types for task dispatch.

Every agent dispatch, every pipeline stage, every result flows through an
Envelope. All models are frozen (immutable). Mutations return new instances
via ``model_copy(update=...)``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path  # noqa: TC003 — Pydantic needs Path at runtime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(StrEnum):
    """Lifecycle status of an envelope."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel, frozen=True):
    """Structured error information attached to a failed envelope."""

    error_type: str
    message: str
    traceback: str | None = None
    stage_name: str | None = None


class Artifact(BaseModel, frozen=True):
    """Named output produced during task execution."""

    name: str
    content: str
    artifact_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope_id() -> str:
    return uuid4().hex[:12]


class Envelope(BaseModel):
    """Immutable unit of work flowing through Bonfire pipelines.

    Frozen (immutable). All transitions return new instances via copy-on-write.
    """

    model_config = ConfigDict(frozen=True)

    envelope_id: str = Field(default_factory=_envelope_id)
    task: str
    context: str = ""
    agent_name: str = ""
    model: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: ErrorDetail | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    cost_usd: float = 0.0
    parent_id: str | None = None
    working_dir: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # -- validators --

    @field_validator("cost_usd")
    @classmethod
    def _cost_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            msg = "cost_usd must be >= 0"
            raise ValueError(msg)
        return v

    # -- mutation helpers (return new instances) --

    def with_status(self, status: TaskStatus) -> Envelope:
        """Return a copy with a new status."""
        return self.model_copy(update={"status": status})

    def with_result(self, result: str, cost_usd: float = 0.0) -> Envelope:
        """Return a copy with the result set and status COMPLETED.

        Validates cost_usd explicitly since model_copy skips validators.
        """
        if cost_usd < 0:
            msg = "cost_usd must be >= 0"
            raise ValueError(msg)
        return self.model_copy(
            update={"result": result, "cost_usd": cost_usd, "status": TaskStatus.COMPLETED},
        )

    def with_error(self, error: ErrorDetail) -> Envelope:
        """Return a copy with the error set and status FAILED."""
        return self.model_copy(update={"error": error, "status": TaskStatus.FAILED})

    def with_metadata(self, **kwargs: Any) -> Envelope:
        """Return a copy with new metadata keys merged into existing metadata.

        Existing keys are preserved; colliding keys are overridden by kwargs
        (last-write-wins). Frozen invariant preserved via model_copy.
        """
        return self.model_copy(
            update={"metadata": {**self.metadata, **kwargs}},
        )

    @classmethod
    def chain(cls, parent: Envelope, **overrides: Any) -> Envelope:
        """Create a child envelope inheriting task/context from parent.

        Resets status to PENDING, generates a new ID, sets parent_id.
        """
        defaults = {
            "task": parent.task,
            "context": parent.context,
            "working_dir": parent.working_dir,
            "envelope_id": _envelope_id(),
            "parent_id": parent.envelope_id,
            "status": TaskStatus.PENDING,
            "result": "",
            "error": None,
            "artifacts": [],
            "cost_usd": 0.0,
        }
        defaults.update(overrides)
        return cls(**defaults)

    # -- debug repr --

    def __repr__(self) -> str:
        task_preview = self.task[:40] + "..." if len(self.task) > 40 else self.task
        parts = [
            f"Envelope({self.envelope_id}",
            f"status={self.status.name}",
            f"task={task_preview!r}",
        ]
        if self.agent_name:
            parts.append(f"agent={self.agent_name}")
        if self.cost_usd > 0:
            parts.append(f"cost=${self.cost_usd:.4f}")
        return ", ".join(parts) + ")"


# ---------------------------------------------------------------------------
# Well-known metadata keys
# ---------------------------------------------------------------------------

META_PR_NUMBER: str = "pr_number"
META_PR_URL: str = "pr_url"
META_REVIEW_SEVERITY: str = "review_severity"
META_REVIEW_VERDICT: str = "review_verdict"
META_TICKET_REF: str = "ticket_ref"
# Preflight metadata (Sage §D10 line 753 — merge-preflight pipeline stage).
META_PREFLIGHT_CLASSIFICATION: str = "preflight_classification"
META_PREFLIGHT_TEST_DEBT_NOTED: str = "preflight_test_debt_noted"
# Sage-correction-bounce metadata (Sage §A Q3 line 132, §B line 327 —
# the sage_correction_bounce pipeline stage). Six keys cover the verdict,
# the lifecycle counter, the cherry-picked branch / commit reference, the
# escalation flag, the skip-reason sentinel, and the upstream classifier
# verdict (kept distinct from the handler's own correction verdict so a
# gate can read both).
META_CLASSIFIER_VERDICT: str = "classifier_verdict"
META_CORRECTION_BRANCH: str = "correction_branch"
META_CORRECTION_CYCLES: str = "correction_cycles"
META_CORRECTION_ESCALATED: str = "correction_escalated"
META_CORRECTION_SKIPPED_REASON: str = "correction_skipped_reason"
META_CORRECTION_VERDICT: str = "correction_verdict"
