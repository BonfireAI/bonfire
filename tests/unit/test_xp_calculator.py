"""RED tests — BON-344 W5.5 — `bonfire.xp.calculator` (conservative lens).

Sage D6 Row 1 locks: 13 tests across five TestXPCalculator* classes pinning
the +100/+50/+25/+25/-10 formula, respawn@3 behavior, XPResult frozen contract,
and default-param total invariant. Sage D4 locks XPResult field order and
`frozen=True`; Sage D8 locks XPCalculator.calculate as @staticmethod with
positional-or-keyword parameters.

Adjudication: ``docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bonfire.xp.calculator import XPCalculator


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
