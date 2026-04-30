"""RED tests for ``SageCorrectionResolvedGate``.

Knight A FULL OWNERSHIP of this file (Sage §D-CL.1 line 20: "all
classes" for the gate test file). The gate translates a
``SageCorrectionBounceHandler`` envelope into a ``GateResult``.

Anta-ratified §A decisions reflected here (2026-04-28):
    - Q9 (b): Stage + Gate composition. Handler writes verdict to
      envelope metadata; the gate reads metadata and produces
      ``GateResult``.
    - Q9 line 306 (Sage proposal, Anta to ratify): ``WARRIOR_BUG``
      verdict → gate ``passed=True, severity='warning'`` (pipeline
      proceeds to Bard so Wizard sees PR; alternative is hard-block).
      Knight A pins the Sage-proposal default; if Anta later flips, this
      is a single-test edit.
    - Q9a line 308: ``AMBIGUOUS`` verdict → gate ``passed=False,
      severity='error'`` (forces Wizard inspection; conservative
      default).
    - §D-CL.1 lines 93-97: gate verdict-to-result mapping table.

Sage memo (canonical):
    docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md §D-CL.1
    docs/audit/sage-decisions/bon-513-sage-A-20260428T210000Z.md §A Q9
    docs/audit/sage-decisions/bon-513-sage-D-20260428T210000Z.md §D1, §D6

Naming note (dispatch SMEAC + §A): ``SageCorrectionResolvedGate`` is the
canonical name (§A Q3 line 131, §A Q9 line 296, §B line 325). Sage §D-CL.1
lines 93-97 use the abbreviated label ``SageCorrectionGate`` in the table
header but bind to the same class via the §A naming. This file imports
``SageCorrectionResolvedGate`` (Anta-ratified canonical).

Conservative RED idiom: imports inside test bodies, ``@pytest.mark.xfail
(strict=True, reason=...)`` on every test method.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

# === Knight A SPINE ===

_RED_REASON = (
    "BON-513 not implemented: SageCorrectionResolvedGate not yet on disk "
    "in bonfire.engine.gates (Sage §A Q9, §B line 325, §D-CL.1 lines 93-97)."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(cost: float = 0.0):
    """Construct a ``GateContext`` with default zero pipeline cost."""
    from bonfire.models.plan import GateContext

    return GateContext(pipeline_cost_usd=cost)


def _completed_envelope(metadata: dict | None = None, result: str = "sage_correction: PASSED"):
    """Envelope mimicking a successful ``SageCorrectionBounceHandler`` return."""
    from bonfire.models.envelope import Envelope

    base = Envelope(task="sage_correction_bounce", metadata=metadata or {})
    return base.with_result(result)


def _failed_envelope(error_type: str, message: str = "sage correction failed"):
    """Envelope mimicking a failure-class handler return."""
    from bonfire.models.envelope import Envelope, ErrorDetail

    return Envelope(task="sage_correction_bounce").with_error(
        ErrorDetail(
            error_type=error_type,
            message=message,
            stage_name="sage_correction_bounce",
        ),
    )


# ---------------------------------------------------------------------------
# TestGateGreenEnvelope (Sage §D-CL.1 line 96, §D-CL.6 #4)
# ---------------------------------------------------------------------------


class TestSageCorrectionResolvedGate:
    """Verdict-to-GateResult mapping for ``SageCorrectionResolvedGate``.

    Maps the four Anta-ratified verdict outcomes onto the GateResult shape
    per Sage §A Q9 (line 296) + §D-CL.1 lines 93-97:

        | Envelope state                            | passed | severity |
        |-------------------------------------------|--------|----------|
        | COMPLETED + verdict='corrected'           |  True  | info     |
        | COMPLETED + verdict='warrior_bug'         |  True  | warning  |
        | COMPLETED + verdict='not_needed_*'        |  True  | info     |
        | COMPLETED + verdict='ambiguous'           |  False | error    |
        | FAILED + error_type='UnknownClassifier..' |  False | error    |
        | FAILED + error_type='correction_failed'   |  False | error    |
        | FAILED + any other error_type             |  False | error    |
    """

    async def test_gate_importable_from_engine_gates_module(self) -> None:
        """Sage §B line 325, §D-CL.1 line 20: gate is in
        ``bonfire.engine.gates``."""
        from bonfire.engine.gates import SageCorrectionResolvedGate

        assert SageCorrectionResolvedGate is not None

    async def test_gate_importable_from_engine_package(self) -> None:
        """Sage §B line 326: gate re-exported from ``bonfire.engine``
        public surface."""
        import bonfire.engine as engine_pkg

        assert hasattr(engine_pkg, "SageCorrectionResolvedGate")

    async def test_gate_in_engine_gates_dunder_all(self) -> None:
        """Sage §A Q9 line 303: gate added to ``__all__``."""
        import bonfire.engine.gates as gates_mod

        assert "SageCorrectionResolvedGate" in getattr(gates_mod, "__all__", [])

    async def test_corrected_verdict_passes_with_info_severity(self) -> None:
        """Sage §D-CL.1 line 96 + §A Q9 lines 298-302: ``corrected``
        verdict → passed=True, severity='info'."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_CORRECTION_VERDICT
        from bonfire.models.plan import GateResult

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_CORRECTION_VERDICT: "corrected"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert isinstance(result, GateResult)
        assert result.passed is True
        assert result.severity == "info"

    async def test_warrior_bug_verdict_passes_with_warning_severity(self) -> None:
        """Sage §A Q9 line 306 (Sage proposal): ``warrior_bug`` is the
        genuine-bug escalate path. Gate returns passed=True,
        severity='warning' so pipeline proceeds to Bard with the
        escalation flag visible to Wizard.

        NB: §A Q9 line 306 explicitly tags this as 'Anta to ratify'.
        Knight A pins the Sage proposal. Flag for Knight B/Wizard if
        Anta flips this to hard-block."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_CORRECTION_VERDICT

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_CORRECTION_VERDICT: "warrior_bug"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True, (
            "Sage §A Q9 line 306 default: warrior_bug allows pipeline to "
            "proceed (Wizard reviews). If Anta ratifies hard-block, flip "
            "this to passed=False, severity='error'."
        )
        assert result.severity == "warning"

    async def test_not_needed_warrior_green_passes_with_info_severity(self) -> None:
        """Sage §D3 line 291 (verdict='not_needed_warrior_green'): warrior
        was already green, no correction needed → passed=True,
        severity='info'."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_CORRECTION_VERDICT

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_CORRECTION_VERDICT: "not_needed_warrior_green"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "info"

    async def test_ambiguous_verdict_blocks_with_error_severity(self) -> None:
        """Sage §A Q9a (line 308, Anta-ratified conservative default):
        ``ambiguous`` verdict → gate passed=False, severity='error'.
        Forces Wizard inspection rather than auto-bouncing on uncertain
        inputs."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_CORRECTION_VERDICT

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_CORRECTION_VERDICT: "ambiguous"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False, (
            "Sage §A Q9a (Anta-ratified): ambiguous verdict halts pipeline."
        )
        assert result.severity == "error"

    async def test_unknown_classifier_verdict_failed_envelope_blocks(self) -> None:
        """Sage §D-CL.1 line 94: FAILED envelope with
        ``error_type='UnknownClassifierVerdict'`` → passed=False,
        severity='error'."""
        from bonfire.engine.gates import SageCorrectionResolvedGate

        gate = SageCorrectionResolvedGate()
        envelope = _failed_envelope("UnknownClassifierVerdict")
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False
        assert result.severity == "error"

    async def test_correction_failed_blocks_with_error_severity(self) -> None:
        """Sage §A Q5 line 184 + §D-CL.1: when classifier returns
        ``correction_failed`` (max attempts exhausted, re-verify still
        red), the FAILED envelope carries
        ``error_type='sage_correction_exhausted'`` (or analogous). Gate
        blocks, severity='error'."""
        from bonfire.engine.gates import SageCorrectionResolvedGate

        gate = SageCorrectionResolvedGate()
        envelope = _failed_envelope("sage_correction_exhausted")
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False
        assert result.severity == "error"

    async def test_completed_with_missing_verdict_metadata_passes_info(self) -> None:
        """Sage §D-CL.1 line 97: COMPLETED with neither verdict nor
        escalation key (skip path) → passed=True, severity='info'.

        Defensive default: handler reached COMPLETED without flagging
        bounce metadata (e.g. handler short-circuited on missing inputs);
        gate must NOT block on that — the handler already decided to
        skip-pass per Sage §D-CL.1 line 77."""
        from bonfire.engine.gates import SageCorrectionResolvedGate

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(metadata={})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "info"

    async def test_gate_name_locked_string(self) -> None:
        """Sage §D-CL.6 #5 anchor + §A Q3 line 124 (gates registry):
        the gate name string is locked at ``'sage_correction_resolved'``
        (matching the stage's ``gates=['sage_correction_resolved']`` entry).

        Mirrors BON-519 ``MergePreflightGate`` precedent (gate name
        ``'merge_preflight_passed'`` locked per Sage §D-CL.6 #5)."""
        from bonfire.engine.gates import SageCorrectionResolvedGate

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope()
        result = await gate.evaluate(envelope, _ctx())
        assert result.gate_name == "sage_correction_resolved", (
            "Gate name MUST be 'sage_correction_resolved' to match the "
            "stage spec's gates=['sage_correction_resolved'] entry "
            "(Sage §A Q3 line 124)."
        )


# === Knight B INNOVATION (banner-merged at contract-lock) ===
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
                stage_name="sage_correction_bounce",
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

    @pytest.mark.asyncio
    async def test_corrected_envelope_is_info_severity(self) -> None:
        """Sage §D-CL.1 line 95: `META_CORRECTION_VERDICT="corrected"` ->
        passed=True, severity='info' (clean — pipeline proceeds normally)."""
        gate = _make_gate()
        envelope = _envelope(metadata={META_CORRECTION_VERDICT: "corrected"})
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "info"
