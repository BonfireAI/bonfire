"""RED tests for bonfire.xp.session — BON-344 W5.5 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md

Floor (10 tests, per Sage §D6 Row 5): port v1 `test_xp_session.py` verbatim.
Innovations (2 tests, INNOVATIVE lens additions over Sage floor):

  * `test_render_session_greeting_keyword_only_typeerror` — drift-guard on the
    Sage §D8 keyword-only lock for `render_session_greeting`. Sage signature
    is `def render_session_greeting(*, tracker, display)` — calling it
    positionally MUST raise TypeError. Cites Sage §D8 + session.py:12.

  * `test_render_session_summary_temperature_before_required` — drift-guard
    on the required-keyword lock for `temperature_before`. Sage §D8 places
    `temperature_before: int` AFTER `cost_usd: float = 0.0` in the keyword-only
    section, with NO default — Python 3.12 accepts required-after-default in
    the keyword-only block. Omitting it MUST raise TypeError. Cites Sage §D8
    + session.py:23-30.

Imports are RED — `bonfire.xp.session` does not exist until Warriors port v1
source per Sage §D9.
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

    def test_greeting_passes_level_name(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["level_name"] == "Flame"

    def test_greeting_passes_temperature(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["temperature"] == 63

    def test_greeting_passes_total_xp(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        render_session_greeting(tracker=tracker, display=display)
        kwargs = display.render_session_start.call_args.kwargs
        assert kwargs["total_xp"] == 1500

    def test_greeting_passes_session_count(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
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

    def test_summary_passes_xp_earned(
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

    def test_summary_passes_cost(
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
        assert kwargs["cost_usd"] == 0.42


# ---------------------------------------------------------------------------
# INNOVATIVE-lens additions (Knight B, Sage-cited)
# ---------------------------------------------------------------------------


class TestRenderSessionGreetingKeywordOnly:
    """Drift-guard: render_session_greeting MUST be keyword-only.

    Sage §D8 locks session.py:12 as:
        def render_session_greeting(*, tracker, display) -> None: ...

    The leading `*,` separator forbids positional binding. A "helpful" Warrior
    that drops the `*,` would silently widen the contract — positional callers
    in the wild would then succeed, accumulating drift before any test fired.
    This pin: positional invocation MUST raise TypeError.
    """

    def test_render_session_greeting_keyword_only_typeerror(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        with pytest.raises(TypeError):
            render_session_greeting(tracker, display)  # type: ignore[misc]


class TestRenderSessionSummaryTemperatureBeforeRequired:
    """Drift-guard: temperature_before is a REQUIRED keyword on render_session_summary.

    Sage §D8 locks session.py:23-30 as:
        def render_session_summary(
            *,
            tracker, display, xp_earned,
            cost_usd: float = 0.0,
            temperature_before: int,  # required, AFTER a defaulted param
        ) -> None: ...

    Python 3.12 accepts required-after-default in the keyword-only section
    (Sage Appendix-equivalent). A Warrior that "fixes" the param order by
    moving `temperature_before` before `cost_usd` would not break this test —
    but a Warrior that adds `temperature_before: int = 0` (silently making it
    optional) WOULD break this test. That is the precise drift this guards.
    """

    def test_render_session_summary_temperature_before_required(
        self, tracker: MagicMock, display: MagicMock
    ) -> None:
        with pytest.raises(TypeError):
            render_session_summary(  # type: ignore[call-arg]
                tracker=tracker,
                display=display,
                xp_earned=120,
                cost_usd=0.42,
                # temperature_before deliberately omitted
            )
