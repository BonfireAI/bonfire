"""Canonical RED — ``bonfire.engine.gates`` (BON-334).

Synthesized from Knight-A orchestration + Knight-B contract fidelity.

Six built-in gates + GateChain composition. Gates are binary pass/fail
checkpoints between stages. Every gate class satisfies the QualityGate
runtime_checkable protocol.

Gate-name strings LOCKED (Sage D9):
    completion, test_pass, red_phase, verification, review_approval, cost_limit

GateChain exception policy LOCKED (Sage D5, option a):
    GateChain does NOT wrap individual gate.evaluate calls. A raising gate
    propagates out of evaluate_all. The Pipeline's outer try/except catches
    it and returns PipelineResult(success=False). Gate exception safety is
    the Pipeline's responsibility, not GateChain's.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.models.plan import GateContext, GateResult
from bonfire.protocols import QualityGate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(result: str = "") -> Envelope:
    """A COMPLETED envelope carrying a result string."""
    return Envelope(task="test").with_result(result)


def _failed() -> Envelope:
    return Envelope(task="test", status=TaskStatus.FAILED)


def _pending() -> Envelope:
    return Envelope(task="test")


def _ctx(cost: float = 0.0) -> GateContext:
    return GateContext(pipeline_cost_usd=cost)


# ===========================================================================
# 1. Imports — all 6 gates + GateChain from both paths; gates.__all__ locked
# ===========================================================================


class TestImports:
    """All 6 gates and GateChain importable; gates.__all__ is the V1 7-name set."""

    def test_import_all_from_gates_module(self) -> None:
        from bonfire.engine.gates import (
            CompletionGate,
            CostLimitGate,
            GateChain,
            RedPhaseGate,
            ReviewApprovalGate,
            TestPassGate,
            VerificationGate,
        )

        assert all(
            x is not None
            for x in (
                CompletionGate,
                CostLimitGate,
                GateChain,
                RedPhaseGate,
                ReviewApprovalGate,
                TestPassGate,
                VerificationGate,
            )
        )

    def test_import_all_from_engine_package(self) -> None:
        from bonfire.engine import (
            CompletionGate,
            CostLimitGate,
            GateChain,
            RedPhaseGate,
            ReviewApprovalGate,
            TestPassGate,
            VerificationGate,
        )

        assert all(
            x is not None
            for x in (
                CompletionGate,
                CostLimitGate,
                GateChain,
                RedPhaseGate,
                ReviewApprovalGate,
                TestPassGate,
                VerificationGate,
            )
        )

    def test_gates_module_has_dunder_all(self) -> None:
        import bonfire.engine.gates as g

        assert hasattr(g, "__all__")

    def test_gates_dunder_all_matches_v1(self) -> None:
        """V1 gates.py __all__ is the 7 canonical names plus the v0.1
        MergePreflightGate and the sage-correction-bounce gate."""
        import bonfire.engine.gates as g

        expected = {
            "CompletionGate",
            "CostLimitGate",
            "GateChain",
            "MergePreflightGate",
            "RedPhaseGate",
            "ReviewApprovalGate",
            "SageCorrectionResolvedGate",
            "TestPassGate",
            "VerificationGate",
        }
        assert set(g.__all__) == expected


# ===========================================================================
# 2. CompletionGate — passes iff status == COMPLETED
# ===========================================================================


class TestCompletionGate:
    """CompletionGate passes only on COMPLETED envelopes (V1 28-38)."""

    def test_evaluate_is_async(self) -> None:
        from bonfire.engine.gates import CompletionGate

        assert inspect.iscoroutinefunction(CompletionGate().evaluate)

    async def test_passes_on_completed(self) -> None:
        from bonfire.engine.gates import CompletionGate

        result = await CompletionGate().evaluate(_completed("done"), _ctx())
        assert result.passed is True
        assert result.gate_name == "completion"
        assert result.severity == "info"

    async def test_fails_on_failed_status(self) -> None:
        from bonfire.engine.gates import CompletionGate

        result = await CompletionGate().evaluate(_failed(), _ctx())
        assert result.passed is False
        assert result.severity == "error"

    async def test_fails_on_pending_status(self) -> None:
        from bonfire.engine.gates import CompletionGate

        result = await CompletionGate().evaluate(_pending(), _ctx())
        assert result.passed is False

    async def test_message_populated_on_failure(self) -> None:
        from bonfire.engine.gates import CompletionGate

        result = await CompletionGate().evaluate(_failed(), _ctx())
        assert isinstance(result.message, str)
        assert result.message  # non-empty


# ===========================================================================
# 3. TestPassGate — passes on "passed" with no non-zero "failed"
# ===========================================================================


class TestTestPassGate:
    """TestPassGate: pass iff result has pass marker AND no N-failed (V1 41-54)."""

    async def test_gate_name_is_test_pass(self) -> None:
        from bonfire.engine.gates import TestPassGate

        r = await TestPassGate().evaluate(_completed("3 passed"), _ctx())
        assert r.gate_name == "test_pass"

    async def test_passes_on_all_passed(self) -> None:
        from bonfire.engine.gates import TestPassGate

        result = await TestPassGate().evaluate(_completed("10 passed, 0 failed"), _ctx())
        assert result.passed is True

    async def test_fails_when_failures_reported(self) -> None:
        from bonfire.engine.gates import TestPassGate

        result = await TestPassGate().evaluate(_completed("3 failed, 2 passed"), _ctx())
        assert result.passed is False
        assert result.severity == "error"

    async def test_fails_on_empty_result(self) -> None:
        from bonfire.engine.gates import TestPassGate

        result = await TestPassGate().evaluate(_completed(""), _ctx())
        assert result.passed is False

    async def test_case_insensitive_pass_detection(self) -> None:
        from bonfire.engine.gates import TestPassGate

        result = await TestPassGate().evaluate(_completed("ALL PASSED"), _ctx())
        assert result.passed is True

    async def test_zero_failed_is_not_a_failure(self) -> None:
        """'0 failed' must NOT trigger the failure regex."""
        from bonfire.engine.gates import TestPassGate

        result = await TestPassGate().evaluate(_completed("5 passed, 0 failed"), _ctx())
        assert result.passed is True


# ===========================================================================
# 4. RedPhaseGate — inverse of TestPassGate
# ===========================================================================


class TestRedPhaseGate:
    """RedPhaseGate passes only when test failures are observed (V1 57-70)."""

    async def test_gate_name_is_red_phase(self) -> None:
        from bonfire.engine.gates import RedPhaseGate

        r = await RedPhaseGate().evaluate(_completed("2 failed"), _ctx())
        assert r.gate_name == "red_phase"

    async def test_passes_on_failures(self) -> None:
        from bonfire.engine.gates import RedPhaseGate

        result = await RedPhaseGate().evaluate(_completed("3 failed, exit code 1"), _ctx())
        assert result.passed is True

    async def test_fails_when_all_passed(self) -> None:
        from bonfire.engine.gates import RedPhaseGate

        result = await RedPhaseGate().evaluate(_completed("10 passed"), _ctx())
        assert result.passed is False
        assert result.severity == "error"

    async def test_passes_on_exit_code_1_alone(self) -> None:
        """'exit code 1' alone is enough to confirm RED."""
        from bonfire.engine.gates import RedPhaseGate

        result = await RedPhaseGate().evaluate(_completed("exit code 1"), _ctx())
        assert result.passed is True


# ===========================================================================
# 5. VerificationGate — passes on "verified" or "checks passed"
# ===========================================================================


class TestVerificationGate:
    """VerificationGate passes on 'verified' or 'checks passed' (V1 73-84)."""

    async def test_gate_name_is_verification(self) -> None:
        from bonfire.engine.gates import VerificationGate

        r = await VerificationGate().evaluate(_completed("verified"), _ctx())
        assert r.gate_name == "verification"

    async def test_passes_on_verified(self) -> None:
        from bonfire.engine.gates import VerificationGate

        result = await VerificationGate().evaluate(_completed("all verified"), _ctx())
        assert result.passed is True

    async def test_passes_on_checks_passed(self) -> None:
        from bonfire.engine.gates import VerificationGate

        result = await VerificationGate().evaluate(_completed("all checks passed"), _ctx())
        assert result.passed is True

    async def test_is_case_insensitive(self) -> None:
        from bonfire.engine.gates import VerificationGate

        result = await VerificationGate().evaluate(_completed("VERIFIED"), _ctx())
        assert result.passed is True

    async def test_fails_on_check_failed(self) -> None:
        from bonfire.engine.gates import VerificationGate

        result = await VerificationGate().evaluate(
            _completed("check failed: type mismatch"), _ctx()
        )
        assert result.passed is False


# ===========================================================================
# 6. ReviewApprovalGate — passes on "approve" or "approved"
# ===========================================================================


class TestReviewApprovalGate:
    """ReviewApprovalGate passes on 'approve' or 'approved' (V1 87-98)."""

    async def test_gate_name_is_review_approval(self) -> None:
        from bonfire.engine.gates import ReviewApprovalGate

        r = await ReviewApprovalGate().evaluate(_completed("approve"), _ctx())
        assert r.gate_name == "review_approval"

    async def test_passes_on_approve(self) -> None:
        from bonfire.engine.gates import ReviewApprovalGate

        result = await ReviewApprovalGate().evaluate(_completed("APPROVE: looks good"), _ctx())
        assert result.passed is True

    async def test_passes_on_approved(self) -> None:
        from bonfire.engine.gates import ReviewApprovalGate

        result = await ReviewApprovalGate().evaluate(_completed("Approved after one round"), _ctx())
        assert result.passed is True

    async def test_fails_on_request_changes(self) -> None:
        from bonfire.engine.gates import ReviewApprovalGate

        result = await ReviewApprovalGate().evaluate(
            _completed("REQUEST_CHANGES: fix types"), _ctx()
        )
        assert result.passed is False


# ===========================================================================
# 7. CostLimitGate — compares pipeline_cost_usd to configured budget
# ===========================================================================


class TestCostLimitGate:
    """CostLimitGate compares pipeline_cost_usd to budget (V1 101-118)."""

    def test_default_budget_is_ten(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        g = CostLimitGate()
        assert g.budget_usd == 10.0

    def test_custom_budget_accepted_via_kwarg(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        g = CostLimitGate(budget_usd=2.5)
        assert g.budget_usd == 2.5

    async def test_gate_name_is_cost_limit(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        r = await CostLimitGate().evaluate(_completed("done"), _ctx(1.0))
        assert r.gate_name == "cost_limit"

    async def test_passes_under_budget(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        result = await CostLimitGate(budget_usd=10.0).evaluate(_completed("done"), _ctx(cost=5.0))
        assert result.passed is True

    async def test_passes_exactly_at_budget(self) -> None:
        """Equal to budget should pass (<=, not <)."""
        from bonfire.engine.gates import CostLimitGate

        result = await CostLimitGate(budget_usd=10.0).evaluate(_completed("done"), _ctx(cost=10.0))
        assert result.passed is True

    async def test_fails_over_budget(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        result = await CostLimitGate(budget_usd=10.0).evaluate(_completed("done"), _ctx(cost=15.0))
        assert result.passed is False
        assert result.severity == "error"

    async def test_default_budget_enforces_ten(self) -> None:
        """CostLimitGate() with no args caps at $10."""
        from bonfire.engine.gates import CostLimitGate

        gate = CostLimitGate()
        r_under = await gate.evaluate(_completed("done"), _ctx(cost=5.0))
        r_over = await gate.evaluate(_completed("done"), _ctx(cost=11.0))
        assert r_under.passed is True
        assert r_over.passed is False


# ===========================================================================
# 8. GateChain — composition, short-circuit, warning propagation
# ===========================================================================


class TestGateChainBasics:
    """GateChain composes gates, evaluating in order."""

    async def test_empty_chain_returns_empty_list(self) -> None:
        from bonfire.engine.gates import GateChain

        results = await GateChain([]).evaluate_all(_completed("done"), _ctx())
        assert results == []

    async def test_single_gate_chain(self) -> None:
        from bonfire.engine.gates import CompletionGate, GateChain

        results = await GateChain([CompletionGate()]).evaluate_all(_completed("done"), _ctx())
        assert len(results) == 1
        assert results[0].passed is True

    async def test_all_pass_returns_all_results(self) -> None:
        from bonfire.engine.gates import CompletionGate, GateChain, TestPassGate

        chain = GateChain([CompletionGate(), TestPassGate()])
        results = await chain.evaluate_all(_completed("10 passed"), _ctx())
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_evaluate_all_is_async(self) -> None:
        from bonfire.engine.gates import GateChain

        assert inspect.iscoroutinefunction(GateChain([]).evaluate_all)

    def test_chain_stores_gates_attribute(self) -> None:
        from bonfire.engine.gates import CompletionGate, GateChain, VerificationGate

        g1, g2 = CompletionGate(), VerificationGate()
        c = GateChain([g1, g2])
        assert g1 in c.gates
        assert g2 in c.gates


class TestGateChainShortCircuit:
    """Error-severity failures stop the chain (V1 line 132-133)."""

    async def test_first_error_halts_chain(self) -> None:
        from bonfire.engine.gates import CompletionGate, GateChain, TestPassGate

        # PENDING envelope: CompletionGate fails with error; TestPassGate must not run.
        chain = GateChain([CompletionGate(), TestPassGate()])
        results = await chain.evaluate_all(_pending(), _ctx())
        assert len(results) == 1
        assert results[0].gate_name == "completion"
        assert results[0].passed is False

    async def test_all_pass_runs_every_gate(self) -> None:
        from bonfire.engine.gates import (
            CompletionGate,
            CostLimitGate,
            GateChain,
            VerificationGate,
        )

        chain = GateChain([CompletionGate(), VerificationGate(), CostLimitGate(budget_usd=100.0)])
        results = await chain.evaluate_all(_completed("verified"), _ctx(cost=1.0))
        assert len(results) == 3


class TestGateChainResultShape:
    """GateChain returns list[GateResult], preserving order."""

    async def test_results_are_gate_result_instances(self) -> None:
        from bonfire.engine.gates import CompletionGate, GateChain

        chain = GateChain([CompletionGate()])
        results = await chain.evaluate_all(_completed("done"), _ctx())
        assert all(isinstance(r, GateResult) for r in results)

    async def test_results_preserve_order(self) -> None:
        from bonfire.engine.gates import CompletionGate, GateChain, VerificationGate

        chain = GateChain([CompletionGate(), VerificationGate()])
        results = await chain.evaluate_all(_completed("verified"), _ctx())
        assert [r.gate_name for r in results] == ["completion", "verification"]


# ===========================================================================
# 9. Protocol compliance — every gate satisfies QualityGate
# ===========================================================================


class TestProtocolCompliance:
    """Every gate class satisfies the QualityGate runtime_checkable protocol."""

    def test_completion_gate_is_quality_gate(self) -> None:
        from bonfire.engine.gates import CompletionGate

        assert isinstance(CompletionGate(), QualityGate)

    def test_test_pass_gate_is_quality_gate(self) -> None:
        from bonfire.engine.gates import TestPassGate

        assert isinstance(TestPassGate(), QualityGate)

    def test_red_phase_gate_is_quality_gate(self) -> None:
        from bonfire.engine.gates import RedPhaseGate

        assert isinstance(RedPhaseGate(), QualityGate)

    def test_verification_gate_is_quality_gate(self) -> None:
        from bonfire.engine.gates import VerificationGate

        assert isinstance(VerificationGate(), QualityGate)

    def test_review_approval_gate_is_quality_gate(self) -> None:
        from bonfire.engine.gates import ReviewApprovalGate

        assert isinstance(ReviewApprovalGate(), QualityGate)

    def test_cost_limit_gate_is_quality_gate(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        assert isinstance(CostLimitGate(budget_usd=1.0), QualityGate)


# ===========================================================================
# 10. Gate-name canonicalisation (Sage D9)
# ===========================================================================


class TestGateNames:
    """Each gate returns the documented gate_name string (Sage D9)."""

    @pytest.mark.parametrize(
        ("cls_path", "expected_name"),
        [
            ("CompletionGate", "completion"),
            ("TestPassGate", "test_pass"),
            ("RedPhaseGate", "red_phase"),
            ("VerificationGate", "verification"),
            ("ReviewApprovalGate", "review_approval"),
        ],
    )
    async def test_canonical_gate_name(self, cls_path: str, expected_name: str) -> None:
        import bonfire.engine.gates as g

        cls = getattr(g, cls_path)
        result = await cls().evaluate(_completed("passed verified APPROVE"), _ctx())
        assert result.gate_name == expected_name

    async def test_cost_limit_name(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        result = await CostLimitGate(budget_usd=100.0).evaluate(_completed("done"), _ctx())
        assert result.gate_name == "cost_limit"


# ===========================================================================
# 11. GateResult shape — correctly-typed fields, immutable
# ===========================================================================


class TestGateResultShape:
    """Every gate returns a GateResult with correctly-typed fields."""

    async def test_fields_are_correct_types(self) -> None:
        from bonfire.engine.gates import CompletionGate

        result = await CompletionGate().evaluate(_completed("done"), _ctx())
        assert isinstance(result, GateResult)
        assert isinstance(result.gate_name, str)
        assert isinstance(result.passed, bool)
        assert isinstance(result.severity, str)
        assert isinstance(result.message, str)

    async def test_severity_is_info_when_passed(self) -> None:
        from bonfire.engine.gates import CompletionGate

        result = await CompletionGate().evaluate(_completed("done"), _ctx())
        assert result.severity == "info"

    async def test_gate_result_is_frozen(self) -> None:
        from bonfire.engine.gates import CompletionGate

        r = await CompletionGate().evaluate(_completed("x"), _ctx())
        with pytest.raises(ValidationError):
            r.passed = False  # type: ignore[misc]


# ===========================================================================
# 12. Never-raise discipline per gate (C19)
# ===========================================================================


class TestGatesNeverRaise:
    """Every built-in gate returns a GateResult on empty input — never raises."""

    async def test_completion_gate_never_raises(self) -> None:
        from bonfire.engine.gates import CompletionGate

        r = await CompletionGate().evaluate(_completed(""), _ctx())
        assert isinstance(r, GateResult)

    async def test_test_pass_gate_never_raises(self) -> None:
        from bonfire.engine.gates import TestPassGate

        r = await TestPassGate().evaluate(_completed(""), _ctx())
        assert isinstance(r, GateResult)

    async def test_red_phase_gate_never_raises(self) -> None:
        from bonfire.engine.gates import RedPhaseGate

        r = await RedPhaseGate().evaluate(_completed(""), _ctx())
        assert isinstance(r, GateResult)

    async def test_verification_gate_never_raises(self) -> None:
        from bonfire.engine.gates import VerificationGate

        r = await VerificationGate().evaluate(_completed(""), _ctx())
        assert isinstance(r, GateResult)

    async def test_review_approval_gate_never_raises(self) -> None:
        from bonfire.engine.gates import ReviewApprovalGate

        r = await ReviewApprovalGate().evaluate(_completed(""), _ctx())
        assert isinstance(r, GateResult)

    async def test_cost_limit_gate_never_raises(self) -> None:
        from bonfire.engine.gates import CostLimitGate

        r = await CostLimitGate().evaluate(_completed(""), _ctx())
        assert isinstance(r, GateResult)
