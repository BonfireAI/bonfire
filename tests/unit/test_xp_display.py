"""RED tests for bonfire.xp.display — BON-344 W5.5 (CONTRACT-LOCKED).

Sage decision log: docs/audit/sage-decisions/bon-344-contract-lock-20260425T192700Z.md
Authority memo:   docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md

Floor (17 tests, per Sage §D6 Row 4): port v1 `test_xp_display.py` verbatim.
Pins the keyword-only render signatures, quiet-mode suppression, level-up
second-line emit, and the phrase-pool fallback path
(`category.rsplit(".", 1)[-1].replace("_", " ").title()`). Sage §D3 locks
`phrase_pool` attribute name (NOT `phrase_bank`); Sage §D8 locks all render
methods as keyword-only; Sage Appendix §5 locks the
`"— " in output[0] and output[0].strip().endswith("Awarded")` fallback
assertion.

Innovations adopted from Knight B (2 tests, drift-guards):
  * `test_render_xp_awarded_level_up_byte_stable` — byte-equality lock on the
    two-line render_xp_awarded(level_up=True) output. Pins TWO separate
    `_display(...)` calls per Sage §D8 + display.py:43-46. Guards against
    em-dash/arrow glyph drift and single-string collapse refactors. Cites
    Sage §D8 + display.py:43-46.
  * `test_select_phrase_fallback_matrix` — parametrize-sweep on `_select_phrase`
    fallback for all six categories the rendering surface uses. v0.1 personas
    expose `phrase_bank` not `phrase_pool` so the fallback IS the v0.1 happy
    path until Ticket A wires phrases. Cites Sage §D3 phrase_pool divergence
    + §D8 fallback lock + display.py:25-30.

Imports are RED — `bonfire.xp.display` does not exist until Warriors port v1
source per Sage §D9.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bonfire.xp.display import XPDisplayConsumer


def _make_consumer(
    *,
    quiet: bool = False,
) -> tuple[XPDisplayConsumer, MagicMock, list[str]]:
    """Build an XPDisplayConsumer with a mock persona and list-based callback."""
    persona = MagicMock()
    persona.phrase_pool.select.return_value = "The forge notes your deeds."

    output: list[str] = []

    def capture(text: object) -> None:
        output.append(str(text))

    consumer = XPDisplayConsumer(
        persona=persona,
        display_callback=capture,
        quiet=quiet,
    )
    return consumer, persona, output


# --- render_xp_awarded ---


class TestRenderXPAwarded:
    """XP awarded rendering."""

    def test_render_xp_awarded_calls_callback(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_awarded(amount=100, reason="pipeline success", level_name="Ember")
        assert len(output) > 0

    def test_render_xp_awarded_includes_amount(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_awarded(amount=75, reason="clean run", level_name="Ember")
        combined = "\n".join(output)
        assert "75" in combined


# --- render_xp_penalty ---


class TestRenderXPPenalty:
    """XP penalty rendering."""

    def test_render_xp_penalty_calls_callback(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_penalty(amount=20, reason="extra iterations")
        assert len(output) > 0

    def test_render_xp_penalty_includes_amount(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_penalty(amount=30, reason="bounced twice")
        combined = "\n".join(output)
        assert "30" in combined


# --- render_xp_respawn ---


class TestRenderXPRespawn:
    """XP respawn rendering."""

    def test_render_xp_respawn_calls_callback(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_respawn(
            stage_name="warrior",
            reason="3 failures",
            checkpoint="last green",
            attempt_count=2,
        )
        assert len(output) > 0

    def test_render_xp_respawn_includes_stage_name(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_respawn(
            stage_name="warrior",
            reason="3 failures",
            checkpoint="last green",
        )
        combined = "\n".join(output)
        assert "warrior" in combined

    def test_render_xp_respawn_includes_checkpoint(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_respawn(
            stage_name="warrior",
            reason="3 failures",
            checkpoint="commit-abc123",
        )
        combined = "\n".join(output)
        assert "commit-abc123" in combined


# --- render_session_start ---


class TestRenderSessionStart:
    """Session start rendering."""

    def test_render_session_start_calls_callback(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_session_start(
            level_name="Ember",
            temperature=42,
            total_xp=1500,
            session_count=7,
        )
        assert len(output) > 0

    def test_render_session_start_includes_level(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_session_start(
            level_name="Ember",
            temperature=42,
            total_xp=1500,
            session_count=7,
        )
        combined = "\n".join(output)
        assert "Ember" in combined

    def test_render_session_start_includes_temperature(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_session_start(
            level_name="Ember",
            temperature=42,
            total_xp=1500,
            session_count=7,
        )
        combined = "\n".join(output)
        assert "42" in combined


# --- render_session_end ---


class TestRenderSessionEnd:
    """Session end rendering."""

    def test_render_session_end_calls_callback(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_session_end(
            xp_earned=250,
            level_name="Ember",
            temperature_before=42,
            temperature_after=55,
        )
        assert len(output) > 0

    def test_render_session_end_includes_xp_earned(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_session_end(
            xp_earned=250,
            level_name="Ember",
            temperature_before=42,
            temperature_after=55,
        )
        combined = "\n".join(output)
        assert "250" in combined

    def test_render_session_end_includes_temperature_change(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_session_end(
            xp_earned=250,
            level_name="Ember",
            temperature_before=42,
            temperature_after=55,
        )
        combined = "\n".join(output)
        assert "42" in combined
        assert "55" in combined


# --- quiet mode ---


class TestQuietMode:
    """Quiet mode suppresses all output."""

    def test_quiet_mode_suppresses_all(self) -> None:
        consumer, _persona, output = _make_consumer(quiet=True)

        consumer.render_xp_awarded(amount=100, reason="test", level_name="Ember")
        consumer.render_xp_penalty(amount=20, reason="test")
        consumer.render_xp_respawn(
            stage_name="warrior",
            reason="test",
            checkpoint="cp",
        )
        consumer.render_session_start(
            level_name="Ember",
            temperature=50,
            total_xp=1000,
            session_count=5,
        )
        consumer.render_session_end(
            xp_earned=100,
            level_name="Ember",
            temperature_before=50,
            temperature_after=60,
        )

        assert len(output) == 0


# --- level up ---


class TestLevelUp:
    """Level-up panel rendering."""

    def test_level_up_renders_panel(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_awarded(
            amount=100,
            reason="pipeline success",
            level_name="Ember",
            level_up=True,
            new_level="Flame",
        )
        combined = "\n".join(output)
        assert "LEVEL UP" in combined
        assert "Ember" in combined
        assert "Flame" in combined

    def test_no_level_up_no_panel(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_awarded(
            amount=100,
            reason="pipeline success",
            level_name="Ember",
            level_up=False,
        )
        combined = "\n".join(output)
        assert "LEVEL UP" not in combined


# --- phrase fallback ---


class TestPhraseFallback:
    """When persona has no phrase_pool, display uses the category name."""

    def test_fallback_produces_readable_text(self) -> None:
        """Without phrase_pool, _select_phrase returns the category tail as title case."""
        persona = MagicMock(spec=[])  # no phrase_pool attribute
        output: list[str] = []
        consumer = XPDisplayConsumer(
            persona=persona,
            display_callback=lambda t: output.append(str(t)),
            quiet=False,
        )
        consumer.render_xp_awarded(amount=50, reason="test", level_name="Spark")
        # Should contain the fallback text "Awarded" (from "xp.awarded")
        assert "Awarded" in output[0]
        # Should NOT have trailing dash with empty string
        assert "— " in output[0] and output[0].strip().endswith("Awarded")


# ---------------------------------------------------------------------------
# Adopted innovations (drift-guards)
# ---------------------------------------------------------------------------


class TestRenderXPAwardedByteStability:
    """Drift-guard: render_xp_awarded(level_up=True) emits two byte-stable lines.

    Sage §D8 locks the v1-verbatim output contract in display.py:43-46:
        Line 1: f"+{amount} XP — {phrase}"
        Line 2: f"⬆ LEVEL UP: {level_name} → {new_level}"

    The two lines are emitted as TWO separate `self._display(...)` calls (so
    the output list has exactly 2 entries). Drift surfaces:
      - Dash glyph drift (em-dash `—` vs. hyphen `-`).
      - Arrow glyph drift (`→` vs. `->`).
      - Word ordering ("LEVEL UP" before / after the colon).
      - Single concatenated line instead of two `_display()` calls.

    Future refactor guard: a "helpful" Warrior collapse to one f-string would
    halve the output list and break this test.
    """

    def test_render_xp_awarded_level_up_byte_stable(self) -> None:
        consumer, _persona, output = _make_consumer()
        consumer.render_xp_awarded(
            amount=120,
            reason="leveled up",
            level_name="Ember",
            level_up=True,
            new_level="Flame",
        )
        # Exactly two lines from two `_display()` calls per Sage §D8.
        assert len(output) == 2, (
            f"render_xp_awarded(level_up=True) drift: expected 2 separate display "
            f"calls, got {len(output)}. Sage §D8 + display.py:44-46 lock two-call form."
        )
        # Line 1 byte-stable per display.py:44.
        assert output[0] == "+120 XP — The forge notes your deeds.", (
            f"Line 1 drift: got {output[0]!r}"
        )
        # Line 2 byte-stable per display.py:46.
        assert output[1] == "⬆ LEVEL UP: Ember → Flame", f"Line 2 drift: got {output[1]!r}"


class TestSelectPhraseFallbackMatrix:
    """Drift-guard: parametrize-matrix pins _select_phrase fallback for all categories.

    Sage §D8 (display.py:25-30) + Sage §D3 lock the fallback formula:
        category.rsplit(".", 1)[-1].replace("_", " ").title()

    v0.1 personas expose `phrase_bank` (not `phrase_pool`). Per Sage §D3,
    XPDisplayConsumer keeps `getattr(self._persona, "phrase_pool", None)` so the
    fallback IS the v0.1 happy path until Ticket A enriches phrases. This matrix
    sweeps all six categories the public surface uses:
        xp.awarded → "Awarded"
        xp.penalty → "Penalty"
        xp.respawn → "Respawn"
        session.greeting → "Greeting"
        session.farewell → "Farewell"
        xp.level_up.flame → "Flame" (underscore branch)
    """

    @pytest.mark.parametrize(
        ("category", "expected_tail"),
        [
            ("xp.awarded", "Awarded"),
            ("xp.penalty", "Penalty"),
            ("xp.respawn", "Respawn"),
            ("session.greeting", "Greeting"),
            ("session.farewell", "Farewell"),
            # Underscore-branch coverage: title-case the post-underscore segment.
            ("xp.level_up.flame", "Flame"),
        ],
    )
    def test_select_phrase_fallback_matrix(self, category: str, expected_tail: str) -> None:
        persona = MagicMock(spec=[])  # no phrase_pool attribute
        consumer = XPDisplayConsumer(
            persona=persona,
            display_callback=lambda _t: None,
            quiet=False,
        )
        result = consumer._select_phrase(category, {})
        assert result == expected_tail, (
            f"Fallback drift at category={category!r}: expected {expected_tail!r}, "
            f"got {result!r}. Sage §D8 locks "
            f'category.rsplit(".", 1)[-1].replace("_", " ").title().'
        )
