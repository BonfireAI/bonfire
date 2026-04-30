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
from typing import TYPE_CHECKING

from bonfire.models.envelope import (
    META_CLASSIFIER_VERDICT,
    META_CORRECTION_ESCALATED,
    META_CORRECTION_VERDICT,
    META_PREFLIGHT_TEST_DEBT_NOTED,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import GateContext, GateResult

if TYPE_CHECKING:
    from bonfire.protocols import QualityGate

# Pattern matching a non-zero count followed by "failed" (case-insensitive).
_NONZERO_FAILED_RE = re.compile(r"[1-9]\d*\s+failed", re.IGNORECASE)

# Gate name string -- locked per Sage §D-CL.6 #5 (line 1071) for the merge-preflight gate.
_MERGE_PREFLIGHT_GATE_NAME: str = "merge_preflight_passed"

# Gate name string -- locked per Sage §D-CL.6 #5 + §A Q3 line 124 for the
# sage-correction-bounce stage.
_SAGE_CORRECTION_GATE_NAME: str = "sage_correction_resolved"

# Verdict-routing tables for SageCorrectionResolvedGate (frozen so wrong
# states are unrepresentable; missing keys fall through to the default
# "info" rule). why: dict-dispatch keeps the four-row Sage matrix on a
# single screen; an if/elif chain spreads the rules across 30+ lines.
_AMBIGUOUS_VERDICT: str = "ambiguous"
_WARRIOR_BUG_VERDICT: str = "warrior_bug"
_PASSING_WARNING_VERDICTS: frozenset[str] = frozenset({_WARRIOR_BUG_VERDICT})

__all__ = [
    "CompletionGate",
    "CostLimitGate",
    "GateChain",
    "MergePreflightGate",
    "RedPhaseGate",
    "ReviewApprovalGate",
    "SageCorrectionResolvedGate",
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
        error_type = envelope.error.error_type if envelope.error is not None else "unknown"
        message = envelope.error.message if envelope.error is not None else "preflight blocked"
        return GateResult(
            gate_name=_MERGE_PREFLIGHT_GATE_NAME,
            passed=False,
            severity="error",
            message=f"Preflight blocked merge: {error_type} -- {message}",
        )


class SageCorrectionResolvedGate:
    """Gate adapter for :class:`SageCorrectionBounceHandler` envelopes.

    Translates the handler's correction-cycle envelope into a
    :class:`GateResult`. Verdict-routing matrix (Sage §D-CL.1 lines 93-97
    + Anta-ratified §A Q9a):

        | envelope shape                                      | passed | severity |
        |-----------------------------------------------------|--------|----------|
        | COMPLETED + classifier_verdict="ambiguous"          | False  | error    |
        | COMPLETED + correction_verdict="ambiguous"          | False  | error    |
        | COMPLETED + correction_verdict="warrior_bug"        | True   | warning  |
        | COMPLETED + correction_escalated=True               | True   | warning  |
        | COMPLETED + correction_verdict="corrected"          | True   | info     |
        | COMPLETED + correction_verdict="not_needed_*"       | True   | info     |
        | COMPLETED + (missing both keys; skip path)          | True   | info     |
        | FAILED + any error_type                             | False  | error    |

    The gate is a pure function of the envelope -- same envelope, same
    result. Gate name is locked at ``"sage_correction_resolved"``.
    """

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        del context  # gate is envelope-only
        # FAILED short-circuits to error (any error_type).
        if envelope.status != TaskStatus.COMPLETED:
            error_type = envelope.error.error_type if envelope.error is not None else "unknown"
            message = (
                envelope.error.message if envelope.error is not None else "sage_correction blocked"
            )
            return GateResult(
                gate_name=_SAGE_CORRECTION_GATE_NAME,
                passed=False,
                severity="error",
                message=f"Sage correction blocked: {error_type} -- {message}",
            )

        # COMPLETED. Read both verdict keys; ambiguous on either blocks.
        classifier_verdict = envelope.metadata.get(META_CLASSIFIER_VERDICT, "")
        correction_verdict = envelope.metadata.get(META_CORRECTION_VERDICT, "")
        escalated = envelope.metadata.get(META_CORRECTION_ESCALATED) is True

        if classifier_verdict == _AMBIGUOUS_VERDICT or correction_verdict == _AMBIGUOUS_VERDICT:
            return GateResult(
                gate_name=_SAGE_CORRECTION_GATE_NAME,
                passed=False,
                severity="error",
                message=(
                    "Sage correction blocked: ambiguous classifier verdict "
                    "(forces Wizard inspection)."
                ),
            )

        if correction_verdict in _PASSING_WARNING_VERDICTS or escalated:
            return GateResult(
                gate_name=_SAGE_CORRECTION_GATE_NAME,
                passed=True,
                severity="warning",
                message=(
                    "Sage correction escalated to Wizard "
                    f"(verdict={correction_verdict or 'escalated'})."
                ),
            )

        # Default: passed + info (corrected, not_needed_*, or skip path).
        return GateResult(
            gate_name=_SAGE_CORRECTION_GATE_NAME,
            passed=True,
            severity="info",
            message=(
                f"Sage correction resolved cleanly (verdict={correction_verdict or 'skipped'})."
            ),
        )


class GateChain:
    """Sequential gate evaluator with short-circuit on error-severity failure."""

    def __init__(self, gates: list[QualityGate]) -> None:
        self.gates = gates

    async def evaluate_all(self, envelope: Envelope, context: GateContext) -> list[GateResult]:
        results: list[GateResult] = []
        for gate in self.gates:
            result = await gate.evaluate(envelope, context)
            results.append(result)
            if not result.passed and result.severity == "error":
                break
        return results
