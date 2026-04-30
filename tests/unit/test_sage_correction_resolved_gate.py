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

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_gate_importable_from_engine_gates_module(self) -> None:
        """Sage §B line 325, §D-CL.1 line 20: gate is in
        ``bonfire.engine.gates``."""
        from bonfire.engine.gates import SageCorrectionResolvedGate

        assert SageCorrectionResolvedGate is not None

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_gate_importable_from_engine_package(self) -> None:
        """Sage §B line 326: gate re-exported from ``bonfire.engine``
        public surface."""
        import bonfire.engine as engine_pkg

        assert hasattr(engine_pkg, "SageCorrectionResolvedGate")

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_gate_in_engine_gates_dunder_all(self) -> None:
        """Sage §A Q9 line 303: gate added to ``__all__``."""
        import bonfire.engine.gates as gates_mod

        assert "SageCorrectionResolvedGate" in getattr(gates_mod, "__all__", [])

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_corrected_verdict_passes_with_info_severity(self) -> None:
        """Sage §D-CL.1 line 96 + §A Q9 lines 298-302: ``corrected``
        verdict → passed=True, severity='info'."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_BOUNCE_VERDICT
        from bonfire.models.plan import GateResult

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_BOUNCE_VERDICT: "corrected"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert isinstance(result, GateResult)
        assert result.passed is True
        assert result.severity == "info"

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_warrior_bug_verdict_passes_with_warning_severity(self) -> None:
        """Sage §A Q9 line 306 (Sage proposal): ``warrior_bug`` is the
        genuine-bug escalate path. Gate returns passed=True,
        severity='warning' so pipeline proceeds to Bard with the
        escalation flag visible to Wizard.

        NB: §A Q9 line 306 explicitly tags this as 'Anta to ratify'.
        Knight A pins the Sage proposal. Flag for Knight B/Wizard if
        Anta flips this to hard-block."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_BOUNCE_VERDICT

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_BOUNCE_VERDICT: "warrior_bug"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True, (
            "Sage §A Q9 line 306 default: warrior_bug allows pipeline to "
            "proceed (Wizard reviews). If Anta ratifies hard-block, flip "
            "this to passed=False, severity='error'."
        )
        assert result.severity == "warning"

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_not_needed_warrior_green_passes_with_info_severity(self) -> None:
        """Sage §D3 line 291 (verdict='not_needed_warrior_green'): warrior
        was already green, no correction needed → passed=True,
        severity='info'."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_BOUNCE_VERDICT

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_BOUNCE_VERDICT: "not_needed_warrior_green"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is True
        assert result.severity == "info"

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_ambiguous_verdict_blocks_with_error_severity(self) -> None:
        """Sage §A Q9a (line 308, Anta-ratified conservative default):
        ``ambiguous`` verdict → gate passed=False, severity='error'.
        Forces Wizard inspection rather than auto-bouncing on uncertain
        inputs."""
        from bonfire.engine.gates import SageCorrectionResolvedGate
        from bonfire.models.envelope import META_BOUNCE_VERDICT

        gate = SageCorrectionResolvedGate()
        envelope = _completed_envelope(
            metadata={META_BOUNCE_VERDICT: "ambiguous"},
        )
        result = await gate.evaluate(envelope, _ctx())
        assert result.passed is False, (
            "Sage §A Q9a (Anta-ratified): ambiguous verdict halts pipeline."
        )
        assert result.severity == "error"

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
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

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
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

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
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

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
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
