"""RED tests — BON-344 W5.5 — `bonfire.xp.session` (conservative lens).

Sage D6 Row 5 locks: 10 tests across TestRenderSessionGreeting and
TestRenderSessionSummary classes pinning the pure-bridge contract —
render_session_greeting reads tracker state and delegates to
display.render_session_start; render_session_summary reads tracker
state and delegates to display.render_session_end. Sage D8 locks both
functions as keyword-only; `temperature_before` is REQUIRED keyword in
render_session_summary (after `cost_usd: float = 0.0` in the keyword-only
section per Python 3.12 semantics). Sage D8 also locks the exact keyword
arguments forwarded to the display methods.

Adjudication: ``docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bonfire.xp.session import render_session_greeting, render_session_summary

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tracker() -> MagicMock:
    t = MagicMock()
    t.level.return_value = (2, "Flame")
    t.temperature.return_value = 63
    t.total_xp.return_value = 1500
    t.session_count.return_value = 14
    return t


@pytest.fixture()
def display() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# render_session_greeting
# ---------------------------------------------------------------------------


class TestRenderSessionGreeting:
    """Tests for render_session_greeting."""

    def test_greeting_calls_render_session_start(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_greeting(tracker=tracker, display=display)
        display.render_session_start.assert_called_once()

    def test_greeting_passes_level_name(self, tracker: MagicMock, display: MagicMock) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["level_name"] == "Flame"

    def test_greeting_passes_temperature(self, tracker: MagicMock, display: MagicMock) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["temperature"] == 63

    def test_greeting_passes_total_xp(self, tracker: MagicMock, display: MagicMock) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["total_xp"] == 1500

    def test_greeting_passes_session_count(self, tracker: MagicMock, display: MagicMock) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["session_count"] == 14


# ---------------------------------------------------------------------------
# render_session_summary
# ---------------------------------------------------------------------------


class TestRenderSessionSummary:
    """Tests for render_session_summary."""

    def test_summary_calls_render_session_end(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_summary(
            tracker=tracker,
            display=display,
            xp_earned=120,
            cost_usd=0.42,
            temperature_before=50,
        )
        display.render_session_end.assert_called_once()

    def test_summary_passes_xp_earned(self, tracker: MagicMock, display: MagicMock) -> None:
        render_session_summary(
            tracker=tracker,
            display=display,
            xp_earned=120,
            cost_usd=0.42,
            temperature_before=50,
        )
        kwargs = display.render_session_end.call_args.kwargs
        assert kwargs["xp_earned"] == 120

    def test_summary_passes_temperature_before(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_summary(
            tracker=tracker,
            display=display,
            xp_earned=120,
            cost_usd=0.42,
            temperature_before=50,
        )
        kwargs = display.render_session_end.call_args.kwargs
        assert kwargs["temperature_before"] == 50

    def test_summary_passes_temperature_after(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_summary(
            tracker=tracker,
            display=display,
            xp_earned=120,
            cost_usd=0.42,
            temperature_before=50,
        )
        kwargs = display.render_session_end.call_args.kwargs
        assert kwargs["temperature_after"] == 63  # tracker.temperature()

    def test_summary_passes_cost(self, tracker: MagicMock, display: MagicMock) -> None:
        render_session_summary(
            tracker=tracker,
            display=display,
            xp_earned=120,
            cost_usd=0.42,
            temperature_before=50,
        )
        kwargs = display.render_session_end.call_args.kwargs
        assert kwargs["cost_usd"] == 0.42
