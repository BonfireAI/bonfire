"""RED tests for `bonfire.engine.gates.SageCorrectionResolvedGate` —
INNOVATION coverage (Knight B).

Per Sage memo
`docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md` §D-CL.2
("Knight B INNOVATION") + §D-CL.1 line 93-97 (gate verdict table) +
user-prompt Q9 (b) (Stage + Gate) + Q9a (`AMBIGUOUS` verdict -> gate
fails hard, severity='error', pipeline halts).

Knight B owns the *innovation* coverage in this file:
    - Parametrized verdict-to-gate-result table (4 verdict cases x
      passed/severity matrix).
    - Gate name and gate context shape verification.
    - Gate purity (pure-function evaluate, no I/O).

Knight A owns the spine (TestSageCorrectionGate) — single-test classes
mirroring `TestMergePreflightGate`. This file's Knight B section ADDS
parametrized coverage and edge cases. Banner-comment file split per
Sage §D-CL.1 lines 106-118.

This is RED. xfail(strict=True). xpass = bug.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

# === Knight B INNOVATION ===

# --- Dep-presence flags (over-specified per Sage §D-CL.1 line 27-50) --------


def _module_present(modname: str) -> bool:
    """Check importability, tolerating missing intermediate packages."""
    try:
        return importlib.util.find_spec(modname) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _safe_import(modname: str) -> Any | None:
    try:
        import importlib as _il

        return _il.import_module(modname)
    except ImportError:
        return None


_GATES_MODULE_PRESENT = _module_present("bonfire.engine.gates")
_gates_module = _safe_import("bonfire.engine.gates") if _GATES_MODULE_PRESENT else None
_GATE_PRESENT = _gates_module is not None and hasattr(_gates_module, "SageCorrectionResolvedGate")
_ENVELOPE_PRESENT = _module_present("bonfire.models.envelope")
_PLAN_PRESENT = _module_present("bonfire.models.plan")

_BOTH_LANDED = _GATE_PRESENT and _ENVELOPE_PRESENT and _PLAN_PRESENT

# Try to import the new META_* constants; xfail-condition them too.
try:
    from bonfire.models.envelope import (  # type: ignore[attr-defined]
        META_CLASSIFIER_VERDICT,
        META_CORRECTION_ESCALATED,
        META_CORRECTION_VERDICT,
    )

    _META_CONSTANTS_PRESENT = True
except ImportError:  # pragma: no cover
    META_CLASSIFIER_VERDICT = "classifier_verdict"
    META_CORRECTION_ESCALATED = "correction_escalated"
    META_CORRECTION_VERDICT = "correction_verdict"
    _META_CONSTANTS_PRESENT = False


_GATE_XFAIL = pytest.mark.xfail(
    condition=not (_BOTH_LANDED and _META_CONSTANTS_PRESENT),
    reason=(
        "v0.1 RED: bonfire.engine.gates.SageCorrectionResolvedGate AND "
        "META_CLASSIFIER_VERDICT/META_CORRECTION_VERDICT/"
        "META_CORRECTION_ESCALATED constants must all land. Deferred "
        "to BON-513-warrior-impl (Sage memo §D-CL.2 + §D-CL.1 lines "
        "93-97; user-prompt Q9a)."
    ),
    strict=True,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ctx(cost: float = 0.0) -> Any:
    """Build a `GateContext` (lazy-imported)."""
    from bonfire.models.plan import GateContext

    return GateContext(pipeline_cost_usd=cost)


def _envelope(
    *,
    metadata: dict | None = None,
    error_type: str | None = None,
) -> Any:
    """Build an Envelope; if `error_type` provided, the envelope is FAILED."""
    from bonfire.models.envelope import Envelope, ErrorDetail

    base = Envelope(task="sage_correction", metadata=metadata or {})
    if error_type is not None:
        return base.with_error(
            ErrorDetail(
                error_type=error_type,
                message=f"sage_correction failure: {error_type}",
                stage_name="sage_correction",
            ),
        )
    return base.with_result("sage_correction: ok")


def _make_gate() -> Any:
    """Construct the SageCorrectionResolvedGate (lazy import)."""
    from bonfire.engine.gates import SageCorrectionResolvedGate

    return SageCorrectionResolvedGate()


# ---------------------------------------------------------------------------
# Parametrized verdict -> gate-result matrix (Knight B INNOVATION)
# ---------------------------------------------------------------------------


# Per Sage §D-CL.1 lines 93-97 + user-prompt Q9a:
#
# | envelope shape                                       | passed | severity |
# |------------------------------------------------------|--------|----------|
# | COMPLETED + META_CORRECTION_VERDICT="corrected"      | True   | "info"   |
# | COMPLETED + META_CORRECTION_ESCALATED=True           | True   | "warning"|
# | COMPLETED + (skip path; missing both keys)           | True   | "info"   |
# | COMPLETED + META_CLASSIFIER_VERDICT="ambiguous"      | False  | "error"  |
# | FAILED + error.error_type="UnknownClassifierVerdict" | False  | "error"  |

_GATE_PARAMS = [
    pytest.param(
        {"metadata": {META_CORRECTION_VERDICT: "corrected"}},
        True,
        "info",
        id="corrected_passes_info",
    ),
    pytest.param(
        {"metadata": {META_CORRECTION_ESCALATED: True}},
        True,
        "warning",
        id="escalated_passes_warning",
    ),
    pytest.param(
        {"metadata": {}},
        True,
        "info",
        id="skip_path_passes_info",
    ),
    pytest.param(
        {"metadata": {META_CLASSIFIER_VERDICT: "ambiguous"}},
        False,
        "error",
        id="ambiguous_blocks_error",
    ),
    pytest.param(
        {"metadata": {}, "error_type": "UnknownClassifierVerdict"},
        False,
        "error",
        id="unknown_verdict_blocks_error",
    ),
]


class TestSageCorrectionResolvedGateMatrix:
    """Sage §D-CL.1 lines 93-97 verdict-to-gate matrix + user-prompt Q9a.

    Innovation pattern: parametrize over the full verdict matrix in ONE
    test method instead of 5 sibling test methods (Knight A-style).
    Each row encodes a contract row from the Sage memo table.
    """

    @pytest.mark.parametrize(
        "envelope_kwargs,expected_passed,expected_severity",
        _GATE_PARAMS,
    )
    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_gate_evaluates_envelope_to_expected_result(
        self,
        envelope_kwargs: dict,
        expected_passed: bool,
        expected_severity: str,
    ) -> None:
        gate = _make_gate()
        envelope = _envelope(**envelope_kwargs)
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is expected_passed, (
            f"Verdict-matrix row failed: expected passed={expected_passed} "
            f"for envelope kwargs {envelope_kwargs}; got {result.passed}."
        )
        assert result.severity == expected_severity, (
            f"Verdict-matrix row failed: expected severity={expected_severity!r} "
            f"for envelope kwargs {envelope_kwargs}; got {result.severity!r}."
        )


# ---------------------------------------------------------------------------
# Gate-shape contract (Knight B innovation: gate is a public surface that
# downstream stages key off; verify name + result shape)
# ---------------------------------------------------------------------------


class TestSageCorrectionResolvedGateShape:
    """Gate name, evaluate signature, and GateResult shape."""

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_gate_name_is_sage_correction_resolved(self) -> None:
        """Sage §D-CL.6 line 414 + user-prompt Q9 (b): the gate name is
        `sage_correction_resolved` (the gate emitted by the new stage).
        Mirrors the BON-519 `merge_preflight_passed` gate-name pattern."""
        gate = _make_gate()
        envelope = _envelope(metadata={META_CORRECTION_VERDICT: "corrected"})
        result = await gate.evaluate(envelope, _ctx())
        # Accept either "sage_correction_resolved" (this file's name) or
        # "sage_correction" (Sage §D6 line 581 spelling). Strict literal:
        # the user prompt's file name implies "resolved" suffix.
        assert result.gate_name in (
            "sage_correction_resolved",
            "sage_correction",
        )

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_gate_result_is_immutable_pydantic_model(self) -> None:
        """`GateResult` is `model_config=ConfigDict(frozen=True)` per
        `models/plan.py:38`. Defensive regression: gate result is frozen."""
        from bonfire.models.plan import GateResult

        gate = _make_gate()
        result = await gate.evaluate(_envelope(), _ctx())
        assert isinstance(result, GateResult)
        # Pydantic frozen=True -> setattr raises ValidationError.
        with pytest.raises(Exception):
            result.passed = not result.passed  # type: ignore[misc]

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_evaluate_is_async(self) -> None:
        """Gate.evaluate must be async (Sage protocols.py:178 contract)."""
        import inspect as _inspect

        gate = _make_gate()
        assert _inspect.iscoroutinefunction(gate.evaluate)


# ---------------------------------------------------------------------------
# Cross-cutting safety (Sage §D-CL.7 reviewer concerns applied here)
# ---------------------------------------------------------------------------


class TestSageCorrectionResolvedGateSafety:
    """Sage §D-CL.7 #6 (non-determinism) + #8 (gate-block path coverage)."""

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_gate_evaluate_is_pure_no_io_no_clock(self) -> None:
        """Sage §D-CL.7 #6 + §D-CL.6 #2: gate is a pure function over
        the envelope. Same envelope evaluated twice -> same result."""
        gate = _make_gate()
        envelope = _envelope(metadata={META_CORRECTION_VERDICT: "corrected"})
        first = await gate.evaluate(envelope, _ctx())
        second = await gate.evaluate(envelope, _ctx())
        assert first.passed == second.passed
        assert first.severity == second.severity
        assert first.gate_name == second.gate_name

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_ambiguous_verdict_blocks_pipeline_hard(self) -> None:
        """User-prompt Q9a: `AMBIGUOUS` verdict -> gate fails hard
        (severity='error'); pipeline halts.

        Sage §D-CL.7 #8 mitigation: gate-block path coverage. Without
        this assertion, an AMBIGUOUS verdict could slip through as
        warning (allow-with-annotation) and silently corrupt downstream
        stage choices."""
        gate = _make_gate()
        envelope = _envelope(metadata={META_CLASSIFIER_VERDICT: "ambiguous"})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False, (
            "AMBIGUOUS verdict MUST block (user-prompt Q9a). Allowing "
            "an ambiguous classification through silently is a "
            "self-corruption hazard."
        )
        assert result.severity == "error", (
            "AMBIGUOUS verdict MUST escalate to severity='error' "
            "(user-prompt Q9a 'gate fails hard'). 'warning' is "
            "insufficient — Wizard would not halt."
        )

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_escalated_envelope_is_warning_not_error(self) -> None:
        """Sage §D-CL.1 line 96: `META_CORRECTION_ESCALATED=True` ->
        passed=True, severity='warning' (escalation is allowed; Wizard
        still gets the bounce). User-prompt Q9a only escalates AMBIGUOUS
        to 'error', NOT plain `META_CORRECTION_ESCALATED`."""
        gate = _make_gate()
        envelope = _envelope(metadata={META_CORRECTION_ESCALATED: True})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "warning"

    @_GATE_XFAIL
    @pytest.mark.asyncio
    async def test_corrected_envelope_is_info_severity(self) -> None:
        """Sage §D-CL.1 line 95: `META_CORRECTION_VERDICT="corrected"` ->
        passed=True, severity='info' (clean — pipeline proceeds normally)."""
        gate = _make_gate()
        envelope = _envelope(metadata={META_CORRECTION_VERDICT: "corrected"})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "info"
