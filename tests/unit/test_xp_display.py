"""RED tests — BON-344 W5.5 — `bonfire.xp.display` (conservative lens).

Sage D6 Row 4 locks: 17 tests across eight TestRender* / TestQuietMode /
TestLevelUp / TestPhraseFallback classes pinning the keyword-only render
signatures, quiet-mode suppression, level-up second-line emit, and the
phrase-pool fallback path (`category.rsplit(".", 1)[-1].replace("_", " ").title()`).
Sage D3 locks `phrase_pool` attribute name (NOT `phrase_bank`); Sage D8 locks
all render methods as keyword-only; Sage Appendix §5 locks the
`"— " in output[0] and output[0].strip().endswith("Awarded")` fallback assertion.

Adjudication: ``docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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
