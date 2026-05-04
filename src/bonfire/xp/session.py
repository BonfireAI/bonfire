# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Session boundary hooks — bridge XPTracker state to XPDisplayConsumer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.xp.display import XPDisplayConsumer
    from bonfire.xp.tracker import XPTracker


def render_session_greeting(*, tracker: XPTracker, display: XPDisplayConsumer) -> None:
    """Read tracker state and render a session start greeting."""
    _level_num, level_name = tracker.level()
    display.render_session_start(
        level_name=level_name,
        temperature=tracker.temperature(),
        total_xp=tracker.total_xp(),
        session_count=tracker.session_count(),
    )


def render_session_summary(
    *,
    tracker: XPTracker,
    display: XPDisplayConsumer,
    xp_earned: int,
    cost_usd: float = 0.0,
    temperature_before: int,
) -> None:
    """Read current tracker state and render a session end summary."""
    _level_num, level_name = tracker.level()
    display.render_session_end(
        xp_earned=xp_earned,
        level_name=level_name,
        temperature_before=temperature_before,
        temperature_after=tracker.temperature(),
        cost_usd=cost_usd,
    )
