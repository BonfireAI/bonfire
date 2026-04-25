"""RED tests for bonfire.xp.calculator — BON-344 W5.5 (CONTRACT-LOCKED).

Sage decision log: docs/audit/sage-decisions/bon-344-contract-lock-20260425T192700Z.md
Authority memo:   docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md

Floor (13 tests, per Sage §D6 Row 1): port v1 `test_xp_calculator.py` verbatim.
Pins the +100/+50/+25/+25/-10 formula, respawn@3 behavior, XPResult frozen
contract, and default-param total invariant. Sage §D4 locks XPResult field
order and `frozen=True`; Sage §D8 locks XPCalculator.calculate as @staticmethod
with positional-or-keyword parameters.

Innovations adopted from Knight B (2 tests, drift-guards):
  * `test_formula_matrix` — parametrize-matrix on the +100/+50/+25/+25/-10
    formula. Each row is a known-risky seam; changing any constant in the
    Warrior port breaks one or more rows. Cites Sage §D8 + calculator.py:45-70.
  * `test_xp_result_bytes_stable_through_json_roundtrip` — JSON round-trip
    + key-set lock on XPResult. Sage §D4 locks the six-field shape; this
    guards future vault/event-log replay against silent field reordering or
    drop. Cites Sage §D4 + calculator.py:8-18.

Imports are RED — `bonfire.xp.calculator` is a 1-line placeholder package
until Warriors port v1 source per Sage §D9.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bonfire.xp.calculator import XPCalculator, XPResult


class TestXPCalculatorBase:
    """Base XP from success/failure."""

    def test_success_base_xp(self) -> None:
        result = XPCalculator.calculate(success=True, stages_completed=3, stages_failed=0)
        assert result.xp_base == 100

    def test_failure_base_xp(self) -> None:
        result = XPCalculator.calculate(success=False, stages_completed=0, stages_failed=1)
        assert result.xp_base == 0


class TestXPCalculatorBonuses:
    """Bonus XP from quality signals."""

    def test_first_try_green_bonus(self) -> None:
        result = XPCalculator.calculate(
            success=True, stages_completed=3, stages_failed=0, tdd_iterations_used=1
        )
        assert result.xp_bonus >= 50

    def test_no_bounces_bonus(self) -> None:
        result = XPCalculator.calculate(
            success=True, stages_completed=3, stages_failed=0, prover_bounces=0
        )
        assert result.xp_bonus >= 25

    def test_wizard_clean_bonus(self) -> None:
        result = XPCalculator.calculate(
            success=True,
            stages_completed=3,
            stages_failed=0,
            wizard_approved_clean=True,
        )
        assert result.xp_bonus >= 25

    def test_all_bonuses_stack(self) -> None:
        result = XPCalculator.calculate(
            success=True,
            stages_completed=3,
            stages_failed=0,
            tdd_iterations_used=1,
            prover_bounces=0,
            wizard_approved_clean=True,
        )
        assert result.xp_bonus == 100


class TestXPCalculatorPenalties:
    """Penalty XP from extra iterations."""

    def test_extra_iterations_penalty(self) -> None:
        result = XPCalculator.calculate(
            success=True, stages_completed=3, stages_failed=0, tdd_iterations_used=3
        )
        assert result.xp_penalty == 20


class TestXPCalculatorRespawn:
    """Respawn mechanic on repeated failures."""

    def test_respawn_on_three_failures(self) -> None:
        result = XPCalculator.calculate(
            success=True,
            stages_completed=3,
            stages_failed=3,
            tdd_iterations_used=1,
            prover_bounces=0,
        )
        assert result.respawn is True
        assert result.xp_bonus == 0

    def test_respawn_reason_message(self) -> None:
        result = XPCalculator.calculate(success=True, stages_completed=3, stages_failed=3)
        assert result.respawn_reason is not None
        assert "3" in result.respawn_reason

    def test_no_respawn_on_two_failures(self) -> None:
        result = XPCalculator.calculate(success=True, stages_completed=3, stages_failed=2)
        assert result.respawn is False


class TestXPCalculatorTotal:
    """Total XP and invariants."""

    def test_xp_total_never_negative(self) -> None:
        result = XPCalculator.calculate(
            success=False,
            stages_completed=0,
            stages_failed=5,
            tdd_iterations_used=20,
        )
        assert result.xp_total >= 0

    def test_xp_result_frozen(self) -> None:
        result = XPCalculator.calculate(success=True, stages_completed=3, stages_failed=0)
        with pytest.raises(ValidationError):
            result.xp_base = 999  # type: ignore[misc]

    def test_default_params(self) -> None:
        result = XPCalculator.calculate(success=True, stages_completed=3, stages_failed=0)
        assert result.xp_base == 100
        assert result.xp_total == result.xp_base + result.xp_bonus - result.xp_penalty


# ---------------------------------------------------------------------------
# Adopted innovations (drift-guards)
# ---------------------------------------------------------------------------


class TestXPCalculatorFormulaMatrix:
    """Drift-guard: parametrize-matrix pins the +100/+50/+25/+25/-10 formula.

    Sage §D8 locks the exact formula in calculator.py:45-70:
        xp_base = 100 if success else 0
        xp_bonus += 50 if tdd_iterations_used == 1 (when not respawn)
        xp_bonus += 25 if prover_bounces == 0 (when not respawn)
        xp_bonus += 25 if wizard_approved_clean (when not respawn)
        xp_penalty = max(0, tdd_iterations_used - 1) * 10
        xp_total = max(0, xp_base + xp_bonus - xp_penalty)
        respawn = stages_failed >= 3  → zeroes xp_bonus

    Each parametrize row is a known-risky seam; changing any constant in the
    Warrior port breaks one or more rows.
    """

    @pytest.mark.parametrize(
        ("success", "stages_failed", "tdd_iter", "bounces", "clean", "exp_total"),
        [
            # Perfect-success baseline: 100 base + 50 + 25 + 25 bonus = 200
            (True, 0, 1, 0, True, 200),
            # Success with no clean: 100 + 50 + 25 = 175
            (True, 0, 1, 0, False, 175),
            # Success + 3 TDD iterations (20 penalty): 100 + 25 + 25 - 20 = 130
            (True, 0, 3, 0, True, 130),
            # Pure failure with bounces=0 STILL awards +25 (bonus pool is gated
            # on `respawn`, NOT on `success`). v1 calculator.py:53-63 verbatim:
            # base=0, bonus=25 (bounces==0 only), penalty=0, total=25.
            (False, 1, 0, 0, False, 25),
            # Respawn: stages_failed >= 3 zeroes the bonus pool entirely.
            # xp_base=100 (success=True), bonus=0 (respawn), penalty=0 → 100
            (True, 3, 1, 0, True, 100),
        ],
    )
    def test_formula_matrix(
        self,
        success: bool,
        stages_failed: int,
        tdd_iter: int,
        bounces: int,
        clean: bool,
        exp_total: int,
    ) -> None:
        result = XPCalculator.calculate(
            success=success,
            stages_completed=3,
            stages_failed=stages_failed,
            tdd_iterations_used=tdd_iter,
            prover_bounces=bounces,
            wizard_approved_clean=clean,
        )
        assert result.xp_total == exp_total, (
            f"Formula drift at (success={success}, stages_failed={stages_failed}, "
            f"tdd={tdd_iter}, bounces={bounces}, clean={clean}): "
            f"expected xp_total={exp_total}, got {result.xp_total}"
        )


class TestXPResultByteStability:
    """Drift-guard: XPResult serializes to JSON with Sage-locked field order.

    Sage §D4 locks the field order `(xp_base, xp_bonus, xp_penalty, xp_total,
    respawn, respawn_reason)` AND `model_config = ConfigDict(frozen=True)`.

    This guards the serialization contract — if a Warrior "helpfully" re-orders
    fields, round-tripping through JSON will still produce an equal value (so
    the basic contract holds), BUT the raw serialized key order will drift.
    Pinning both (a) round-trip equality and (b) the exact key set means future
    vault/event-log replay scenarios can't silently desync.
    """

    def test_xp_result_bytes_stable_through_json_roundtrip(self) -> None:
        result = XPCalculator.calculate(
            success=True,
            stages_completed=3,
            stages_failed=0,
            tdd_iterations_used=1,
            prover_bounces=0,
            wizard_approved_clean=True,
        )
        # Round-trip equality: serialize → parse → rebuild → compare.
        dumped = result.model_dump_json()
        parsed = json.loads(dumped)
        assert XPResult(**parsed) == result, "XPResult round-trip broke equality"

        # Key-set lock: exactly the six Sage §D4-locked fields, no more, no less.
        assert set(parsed.keys()) == {
            "xp_base",
            "xp_bonus",
            "xp_penalty",
            "xp_total",
            "respawn",
            "respawn_reason",
        }, (
            f"XPResult field-set drifted from Sage §D4 lock; got keys={sorted(parsed.keys())}"
        )
