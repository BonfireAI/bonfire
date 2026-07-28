# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Built-in quality gates and GateChain composition.

Six gate classes implementing the QualityGate protocol, plus GateChain for
sequential evaluation with short-circuit on error severity. Gate-name strings
are locked per Sage D9.

**Every gate here grades state, never narration.** A gate reads the
envelope's status, its metadata, the pipeline context, or -- for the three
suite-backed gates re-exported from :mod:`bonfire.engine.suite_gates` -- a
live observation of the project's test suite. None matches a substring
against ``envelope.result``: reading that field rejected correct work
described in unusual words while accepting "I do not approve this change" as
an approval -- one mechanism, both directions, so a longer word list would
have fixed neither. A gate that cannot reach its state raises
:class:`~bonfire.engine.gate_state.GateStateUnavailableError` instead.

Sage D5: GateChain does NOT wrap individual gate exceptions. A raising gate --
including :class:`UnknownGateError` for a gate a stage names but the registry
does not hold -- propagates out to PipelineEngine.run()'s outer try/except,
which returns ``PipelineResult(success=False)``: the loud path an unevaluatable
gate needs, and the reason a missing gate is never silently counted as a pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.engine.gate_state import GateStateUnavailableError
from bonfire.engine.suite_gates import RedPhaseGate, TestPassGate, VerificationGate
from bonfire.models.envelope import (
    META_CLASSIFIER_VERDICT,
    META_CORRECTION_ESCALATED,
    META_CORRECTION_VERDICT,
    META_PREFLIGHT_TEST_DEBT_NOTED,
    META_REVIEW_VERDICT,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import GateContext, GateResult

if TYPE_CHECKING:
    from bonfire.protocols import QualityGate

# The only reviewer verdict that clears the gate; WizardHandler writes it.
_APPROVED_VERDICT: str = "approve"

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


class UnknownGateError(LookupError):
    """A stage names a gate the registry lacks. Never evaluated, so never a pass."""


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


class ReviewApprovalGate:
    """Passes when the reviewer stage recorded an ``approve`` verdict.

    The state is ``envelope.metadata[META_REVIEW_VERDICT]``, which
    :class:`~bonfire.handlers.wizard.WizardHandler` writes from the
    canonical ``<verdict>`` tag *before* it calls GitHub, so a failed post
    cannot lose it, and whose parser fail-safes to ``request_changes`` --
    prose can never manufacture an approval here. ``docs/pipeline-stages.md``
    already specified this contract via ``prior_results``; metadata is the
    correct source, since ``prior_results`` holds result text keyed by stage
    name and could never carry a metadata key.

    A COMPLETED reviewer envelope with no verdict recorded is unevaluatable,
    not a rejection: guessing either way is the defect this replaces.
    """

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        del context  # gate is envelope-only
        if envelope.status != TaskStatus.COMPLETED:
            return GateResult(
                gate_name="review_approval",
                passed=False,
                severity="error",
                message=f"Review stage did not complete: {envelope.status}",
            )
        raw = envelope.metadata.get(META_REVIEW_VERDICT)
        if not isinstance(raw, str) or not raw.strip():
            msg = (
                f"gate 'review_approval': completed envelope carries no "
                f"{META_REVIEW_VERDICT!r}. The reviewer stage must record its verdict; "
                "this gate will not infer one from the review text."
            )
            raise GateStateUnavailableError(msg)
        verdict = raw.strip().lower()
        passed = verdict == _APPROVED_VERDICT
        return GateResult(
            gate_name="review_approval",
            passed=passed,
            severity="info" if passed else "error",
            message=(
                f"Review approved (verdict={verdict})"
                if passed
                else f"Review not approved (verdict={verdict})"
            ),
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

    Maps the four ``MergePreflightHandler`` envelope shapes onto the
    standard ``passed`` / ``severity`` gate vocabulary.

    Severity table:
        - COMPLETED + clean metadata
              -> ``passed=True, severity="info"``
        - COMPLETED + ``META_PREFLIGHT_TEST_DEBT_NOTED is True``
              -> ``passed=True, severity="warning"`` (allow-with-annotation
              path for pre-existing test debt)
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
                        "Preflight passed with pre-existing test debt (allow-with-annotation path)."
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
