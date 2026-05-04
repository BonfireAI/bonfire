# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""XP display consumer — renders XP events with persona phrases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class XPDisplayConsumer:
    """Renders XP events to a display callback using persona phrases."""

    def __init__(
        self,
        *,
        persona: Any,
        display_callback: Callable[[object], None],
        quiet: bool = False,
    ) -> None:
        self._persona = persona
        self._display = display_callback
        self._quiet = quiet

    def _select_phrase(self, category: str, context: dict[str, Any]) -> str:
        """Safely select a phrase, falling back to empty string if unavailable."""
        pool = getattr(self._persona, "phrase_pool", None)
        if pool is not None:
            return pool.select(category, context)
        return category.rsplit(".", 1)[-1].replace("_", " ").title()

    def render_xp_awarded(
        self,
        *,
        amount: int,
        reason: str,
        level_name: str,
        level_up: bool = False,
        new_level: str | None = None,
    ) -> None:
        if self._quiet:
            return
        phrase = self._select_phrase("xp.awarded", {"reason": reason})
        self._display(f"+{amount} XP — {phrase}")
        if level_up and new_level:
            self._display(f"⬆ LEVEL UP: {level_name} → {new_level}")

    def render_xp_penalty(self, *, amount: int, reason: str) -> None:
        if self._quiet:
            return
        phrase = self._select_phrase("xp.penalty", {"reason": reason})
        self._display(f"-{amount} XP — {phrase}")

    def render_xp_respawn(
        self,
        *,
        stage_name: str,
        reason: str,
        checkpoint: str,
        attempt_count: int = 1,
    ) -> None:
        if self._quiet:
            return
        phrase = self._select_phrase("xp.respawn", {"reason": reason})
        self._display(f"💀 RESPAWN at {stage_name}\nCheckpoint: {checkpoint}\n{phrase}")

    def render_session_start(
        self,
        *,
        level_name: str,
        temperature: int,
        total_xp: int,
        session_count: int,
    ) -> None:
        if self._quiet:
            return
        phrase = self._select_phrase("session.greeting", {"session_count": session_count})
        self._display(
            f"Level: {level_name} | Temperature: {temperature} | XP: {total_xp}\n{phrase}"
        )

    def render_session_end(
        self,
        *,
        xp_earned: int,
        level_name: str,
        temperature_before: int,
        temperature_after: int,
        cost_usd: float = 0.0,
    ) -> None:
        if self._quiet:
            return
        phrase = self._select_phrase("session.farewell", {})
        self._display(
            f"XP earned: {xp_earned} | "
            f"Temperature: {temperature_before} → {temperature_after}\n"
            f"{phrase}"
        )
