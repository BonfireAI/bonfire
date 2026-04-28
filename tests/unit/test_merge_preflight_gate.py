"""RED tests for MergePreflightGate.

Per Sage memo bon-519-sage-20260428T033101Z.md §D-CL.1 (lines 845-848)
and §D6 surface map / §D10 line 751.

Knight A FULL OWNERSHIP — gate translates handler envelope to GateResult.

Q6 ratified: ALLOW-WITH-ANNOTATION for pre_existing_debt. The gate
returns passed=True with severity='warning' when the envelope carries
META_PREFLIGHT_TEST_DEBT_NOTED=True. All other failure verdicts produce
passed=False with severity='error'.
"""

from __future__ import annotations

import pytest

# --- v0.1-tolerant imports (RED state: all of these fail today) -------------
try:
    from bonfire.engine.gates import MergePreflightGate  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MergePreflightGate = None  # type: ignore[assignment,misc]

try:
    from bonfire.models.envelope import (  # type: ignore[attr-defined]
        META_PREFLIGHT_TEST_DEBT_NOTED,
    )

    _PREFLIGHT_META_PRESENT = True
except ImportError:  # pragma: no cover
    META_PREFLIGHT_TEST_DEBT_NOTED = "preflight_test_debt_noted"
    _PREFLIGHT_META_PRESENT = False

from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.plan import GateContext, GateResult


pytestmark = pytest.mark.skipif(
    MergePreflightGate is None,
    reason="v0.1 RED: MergePreflightGate not yet implemented",
)


_PREFLIGHT_META_XFAIL = pytest.mark.xfail(
    condition=not _PREFLIGHT_META_PRESENT,
    reason=(
        "v0.1 RED gap: META_PREFLIGHT_* keys not yet in bonfire.models.envelope "
        "(Sage §D10 line 753 — Warrior adds after line 173)."
    ),
    strict=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(cost: float = 0.0) -> GateContext:
    return GateContext(pipeline_cost_usd=cost)


def _completed_envelope(metadata: dict | None = None, result: str = "preflight: PASSED") -> Envelope:
    """Envelope mimicking a successful MergePreflightHandler return."""
    base = Envelope(task="preflight", metadata=metadata or {})
    return base.with_result(result)


def _failed_envelope(error_type: str, message: str = "preflight failure") -> Envelope:
    """Envelope mimicking a failure-class MergePreflightHandler return."""
    return Envelope(task="preflight").with_error(
        ErrorDetail(error_type=error_type, message=message, stage_name="merge_preflight"),
    )


# ---------------------------------------------------------------------------
# TestGateGreenEnvelope (Sage §D-CL.1 line 848)
# ---------------------------------------------------------------------------


class TestGateGreenEnvelope:
    """COMPLETED + clean metadata -> passed=True, severity='info'."""

    @pytest.mark.asyncio
    async def test_clean_completed_envelope_passes(self) -> None:
        """Sage §D-CL.1 line 848: COMPLETED clean -> passed=True, severity='info'."""
        gate = MergePreflightGate()
        envelope = _completed_envelope()
        result = await gate.evaluate(envelope, _ctx())
        assert isinstance(result, GateResult)
        assert result.passed is True
        assert result.severity == "info"

    @pytest.mark.asyncio
    async def test_gate_name_is_merge_preflight_passed(self) -> None:
        """Sage §D-CL.6 #5 (line 1071): the gate is named 'merge_preflight_passed'."""
        gate = MergePreflightGate()
        envelope = _completed_envelope()
        result = await gate.evaluate(envelope, _ctx())
        assert result.gate_name == "merge_preflight_passed"


# ---------------------------------------------------------------------------
# TestGateDebtEnvelope (Q6 ALLOW-WITH-ANNOTATION, Sage §D-CL.1 line 847)
# ---------------------------------------------------------------------------


class TestGateDebtEnvelope:
    """COMPLETED + META_PREFLIGHT_TEST_DEBT_NOTED -> passed=True, severity='warning'.

    Q6 ratified by Anta: pre_existing_debt is ALLOW-WITH-ANNOTATION. The
    pipeline does NOT block, but the gate flags severity='warning' so
    the human reviewer sees the debt note in surfaced output.
    """

    @_PREFLIGHT_META_XFAIL
    @pytest.mark.asyncio
    async def test_debt_envelope_passes_with_warning_severity(self) -> None:
        """Sage §D-CL.1 line 847 + Q6 ratified: warning, not error."""
        gate = MergePreflightGate()
        envelope = _completed_envelope(metadata={META_PREFLIGHT_TEST_DEBT_NOTED: True})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True, (
            "Q6 ALLOW-WITH-ANNOTATION: pre_existing_debt does NOT block merge."
        )
        assert result.severity == "warning", (
            "Q6 ratified: severity='warning' (not 'info' clean, not 'error' block)."
        )

    @_PREFLIGHT_META_XFAIL
    @pytest.mark.asyncio
    async def test_debt_false_value_does_not_trigger_warning(self) -> None:
        """META_PREFLIGHT_TEST_DEBT_NOTED=False is treated as clean (info)."""
        gate = MergePreflightGate()
        envelope = _completed_envelope(metadata={META_PREFLIGHT_TEST_DEBT_NOTED: False})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "info"


# ---------------------------------------------------------------------------
# TestGateBlockedCrossWave (Sage §D-CL.1 line 846)
# ---------------------------------------------------------------------------


class TestGateBlockedCrossWave:
    """FAILED + ErrorDetail(error_type='cross_wave_interaction') -> passed=False, severity='error'."""

    @pytest.mark.asyncio
    async def test_cross_wave_blocks_merge(self) -> None:
        """Sage §D-CL.1 line 846: cross_wave_interaction blocks (severity='error')."""
        gate = MergePreflightGate()
        envelope = _failed_envelope("cross_wave_interaction", "Failure intersects sibling PR #43")
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False
        assert result.severity == "error"


# ---------------------------------------------------------------------------
# TestGateBlockedPureWarriorBug
# ---------------------------------------------------------------------------


class TestGateBlockedPureWarriorBug:
    """FAILED + ErrorDetail(error_type='pure_warrior_bug') -> passed=False, severity='error'."""

    @pytest.mark.asyncio
    async def test_pure_warrior_bug_blocks_merge(self) -> None:
        """Sage §D6 surface map: pure_warrior_bug blocks (severity='error')."""
        gate = MergePreflightGate()
        envelope = _failed_envelope("pure_warrior_bug", "Novel failure introduced by this PR")
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False
        assert result.severity == "error"


# ---------------------------------------------------------------------------
# TestGateBlockedPytestCollectionError
# ---------------------------------------------------------------------------


class TestGateBlockedPytestCollectionError:
    """FAILED + ErrorDetail(error_type='pytest_collection_error') -> passed=False, severity='error'."""

    @pytest.mark.asyncio
    async def test_collection_error_blocks_merge(self) -> None:
        """Sage §D4 line 449 + §D6: pytest_collection_error blocks merge."""
        gate = MergePreflightGate()
        envelope = _failed_envelope("pytest_collection_error", "pytest crashed before collection")
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False
        assert result.severity == "error"


# ---------------------------------------------------------------------------
# TestGateBlockedMergeConflict
# ---------------------------------------------------------------------------


class TestGateBlockedMergeConflict:
    """FAILED + ErrorDetail(error_type='merge_conflict') -> passed=False, severity='error'."""

    @pytest.mark.asyncio
    async def test_merge_conflict_blocks_merge(self) -> None:
        """Sage §D2 line 277 + §D4: merge_conflict (5th-class) blocks merge."""
        gate = MergePreflightGate()
        envelope = _failed_envelope("merge_conflict", "git apply --3way failed for PR #42")
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False
        assert result.severity == "error"
