"""Built-in quality gates and GateChain composition.

Six gate classes implementing the QualityGate protocol, plus GateChain for
sequential evaluation with short-circuit on error severity. Gate-name strings
are locked per Sage D9.

Sage D5: GateChain does NOT wrap individual gate exceptions. A raising gate
propagates out of ``evaluate_all``. The PipelineEngine.run() outer try/except
catches it and returns ``PipelineResult(success=False)``.
"""

from __future__ import annotations

import re

from bonfire.models.envelope import (
    META_PREFLIGHT_TEST_DEBT_NOTED,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import GateContext, GateResult

# Pattern matching a non-zero count followed by "failed" (case-insensitive).
_NONZERO_FAILED_RE = re.compile(r"[1-9]\d*\s+failed", re.IGNORECASE)

# Gate name string -- locked per Sage §D-CL.6 #5 (line 1071) for the merge-preflight gate.
_MERGE_PREFLIGHT_GATE_NAME: str = "merge_preflight_passed"

__all__ = [
    "CompletionGate",
    "CostLimitGate",
    "GateChain",
    "MergePreflightGate",
    "RedPhaseGate",
    "ReviewApprovalGate",
    "TestPassGate",
    "VerificationGate",
]


class CompletionGate:
    """Passes when envelope status is COMPLETED."""

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        passed = envelope.status == TaskStatus.COMPLETED
        return GateResult(
            gate_name="completion",
            passed=passed,
            severity="info" if passed else "error",
            message="Task completed" if passed else f"Task not completed: {envelope.status}",
        )


class TestPassGate:
    """Passes when result contains pass indicators and no failure indicators."""

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        text = envelope.result
        has_pass = "passed" in text.lower()
        has_fail = bool(_NONZERO_FAILED_RE.search(text))
        passed = has_pass and not has_fail
        return GateResult(
            gate_name="test_pass",
            passed=passed,
            severity="info" if passed else "error",
            message="Tests passed" if passed else "Tests did not pass",
        )


class RedPhaseGate:
    """Passes when result contains failure indicators (inverse of TestPassGate)."""

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        text = envelope.result
        has_nonzero_fail = bool(_NONZERO_FAILED_RE.search(text))
        has_exit_code = "exit code 1" in text.lower()
        passed = has_nonzero_fail or has_exit_code
        return GateResult(
            gate_name="red_phase",
            passed=passed,
            severity="info" if passed else "error",
            message="Red phase confirmed" if passed else "No failure indicators found",
        )


class VerificationGate:
    """Passes when result contains 'verified' or 'checks passed'."""

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        text = envelope.result.lower()
        passed = "verified" in text or "checks passed" in text
        return GateResult(
            gate_name="verification",
            passed=passed,
            severity="info" if passed else "error",
            message="Verification passed" if passed else "Verification not confirmed",
        )


class ReviewApprovalGate:
    """Passes when result contains 'approve' or 'approved'."""

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        text = envelope.result.lower()
        passed = "approve" in text or "approved" in text
        return GateResult(
            gate_name="review_approval",
            passed=passed,
            severity="info" if passed else "error",
            message="Review approved" if passed else "Review not approved",
        )


class CostLimitGate:
    """Passes when pipeline cost is within the configured budget."""

    def __init__(self, budget_usd: float = 10.0) -> None:
        self.budget_usd = budget_usd

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        passed = context.pipeline_cost_usd <= self.budget_usd
        return GateResult(
            gate_name="cost_limit",
            passed=passed,
            severity="info" if passed else "error",
            message=(
                f"Cost ${context.pipeline_cost_usd:.2f} within budget ${self.budget_usd:.2f}"
                if passed
                else f"Cost ${context.pipeline_cost_usd:.2f} exceeds budget ${self.budget_usd:.2f}"
            ),
        )


class MergePreflightGate:
    """Gate adapter for :class:`MergePreflightHandler` envelopes.

    Per Sage memo bon-519-sage-20260428T033101Z.md §D-CL.1 lines 845-848,
    §D-CL.6 #5 (line 1071), and §A Q6 (ALLOW-WITH-ANNOTATION ratified).

    Severity table:
        - COMPLETED + clean metadata
              -> ``passed=True, severity="info"``
        - COMPLETED + ``META_PREFLIGHT_TEST_DEBT_NOTED is True``
              -> ``passed=True, severity="warning"`` (Q6)
        - FAILED with ``error_type`` ∈ {cross_wave_interaction,
          pure_warrior_bug, pytest_collection_error, merge_conflict}
              -> ``passed=False, severity="error"``
        - Any other shape (defensive)
              -> ``passed=False, severity="error"``

    Gate name is locked at ``"merge_preflight_passed"``.
    """

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        del context  # gate is envelope-only
        if envelope.status == TaskStatus.COMPLETED:
            debt = envelope.metadata.get(META_PREFLIGHT_TEST_DEBT_NOTED)
            if debt is True:
                return GateResult(
                    gate_name=_MERGE_PREFLIGHT_GATE_NAME,
                    passed=True,
                    severity="warning",
                    message=(
                        "Preflight passed with pre-existing test debt "
                        "(allow-with-annotation per Q6)."
                    ),
                )
            return GateResult(
                gate_name=_MERGE_PREFLIGHT_GATE_NAME,
                passed=True,
                severity="info",
                message="Preflight passed.",
            )

        # FAILED (or any non-COMPLETED) -> blocking gate.
        error_type = (
            envelope.error.error_type if envelope.error is not None else "unknown"
        )
        message = (
            envelope.error.message if envelope.error is not None else "preflight blocked"
        )
        return GateResult(
            gate_name=_MERGE_PREFLIGHT_GATE_NAME,
            passed=False,
            severity="error",
            message=f"Preflight blocked merge: {error_type} -- {message}",
        )


class GateChain:
    """Sequential gate evaluator with short-circuit on error-severity failure."""

    def __init__(self, gates: list) -> None:
        self.gates = gates

    async def evaluate_all(self, envelope: Envelope, context: GateContext) -> list[GateResult]:
        results: list[GateResult] = []
        for gate in self.gates:
            result = await gate.evaluate(envelope, context)
            results.append(result)
            if not result.passed and result.severity == "error":
                break
        return results
