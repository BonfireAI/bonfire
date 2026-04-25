"""XP calculator — pure-math module for pipeline quality signals."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class XPResult(BaseModel):
    """Immutable result of an XP calculation."""

    model_config = ConfigDict(frozen=True)

    xp_base: int
    xp_bonus: int
    xp_penalty: int
    xp_total: int
    respawn: bool
    respawn_reason: str | None = None


class XPCalculator:
    """Pure static XP calculation — no I/O."""

    @staticmethod
    def calculate(
        success: bool,
        stages_completed: int,
        stages_failed: int,
        tdd_iterations_used: int = 0,
        prover_bounces: int = 0,
        wizard_approved_clean: bool = False,
    ) -> XPResult:
        """Calculate XP from pipeline quality signals.

        Formula:
            - +100 base on success, 0 on failure
            - +50 bonus if tdd_iterations_used == 1 (first-try green)
            - +25 bonus if prover_bounces == 0 (no bounces)
            - +25 bonus if wizard_approved_clean (clean Wizard review)
            - -10 penalty per extra TDD iteration beyond 1
            - Respawn if stages_failed >= 3 (zero bonus, penalty still applies)
            - xp_total = xp_base + xp_bonus - xp_penalty (minimum 0)
        """
        # --- Base ---
        xp_base = 100 if success else 0

        # --- Respawn check ---
        respawn = stages_failed >= 3
        respawn_reason: str | None = None
        if respawn:
            respawn_reason = f"Too many stage failures: {stages_failed} stages failed"

        # --- Bonus pool ---
        if respawn:
            xp_bonus = 0
        else:
            xp_bonus = 0
            if tdd_iterations_used == 1:
                xp_bonus += 50
            if prover_bounces == 0:
                xp_bonus += 25
            if wizard_approved_clean:
                xp_bonus += 25

        # --- Penalty ---
        extra_iterations = max(0, tdd_iterations_used - 1)
        xp_penalty = extra_iterations * 10

        # --- Total (floor at 0) ---
        xp_total = max(0, xp_base + xp_bonus - xp_penalty)

        return XPResult(
            xp_base=xp_base,
            xp_bonus=xp_bonus,
            xp_penalty=xp_penalty,
            xp_total=xp_total,
            respawn=respawn,
            respawn_reason=respawn_reason,
        )
