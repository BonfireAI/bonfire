# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract tests for the Falcor scan-discovery narration engine.

``bonfire.onboard.narration.NarrationEngine`` is an exported public class
(listed in that module's ``__all__``) with fully deterministic, testable
behavior that had no test coverage before this file. These tests pin the
four observable contracts that the onboarding theater depends on:

  1. Tier classification (``get_tier``) — a discovery is sorted into
     Tier 3 (surprising), Tier 2 (notable), or Tier 1 (common).
  2. Frequency gating (``should_narrate``) — how often each tier is allowed
     to speak, driven by the running discovery count.
  3. No-reuse + escalation (``get_narration``) — within one session the
     engine never repeats a line it has already emitted, and a category
     seen more than once escalates to a different line pool.
  4. Skip semantics (``get_narration``) — a gated-out discovery yields
     ``None`` rather than a message.

Each test carries a one-line gloss of the exact narration rule it locks so a
future reader (human or LLM) understands the contract without reading source.

Determinism note: line selection uses a module-level ``random.SystemRandom``
(non-seedable, cosmetic context), so no test asserts on WHICH line is picked.
The no-reuse and escalation assertions are structural — ``_used`` filtering
and disjoint pools guarantee them for every possible draw, never the seed.
"""

from __future__ import annotations

from bonfire.onboard.narration import NarrationEngine
from bonfire.onboard.protocol import FalcorMessage, ScanUpdate


def _event(panel: str, label: str, value: str) -> ScanUpdate:
    """Build a ScanUpdate the way the scanner emits one (detail optional)."""
    return ScanUpdate(panel=panel, label=label, value=value)


# ---------------------------------------------------------------------------
# (1) Tier classification — get_tier sorts each discovery into 3 / 2 / 1.
# ---------------------------------------------------------------------------


class TestGetTier:
    """Locks: get_tier reads label/value (lowercased) and returns the tier."""

    def test_tier_3_matches_value_in_tier_3_set(self) -> None:
        # Rule: a value in TIER_3_VALUES (docker/terraform/kubectl/cargo/go/rust)
        # is "surprising" and always classifies as Tier 3.
        engine = NarrationEngine()
        assert engine.get_tier(_event("languages", "Language", "go")) == 3
        assert engine.get_tier(_event("languages", "Language", "rust")) == 3

    def test_tier_3_matches_label_in_tier_3_set(self) -> None:
        # Rule: a label in TIER_3_VALUES also classifies as Tier 3 — the
        # check is on either label or value, case-insensitively.
        engine = NarrationEngine()
        assert engine.get_tier(_event("cli_toolchain", "docker", "27.0")) == 3
        assert engine.get_tier(_event("cli_toolchain", "Terraform", "1.7")) == 3
        assert engine.get_tier(_event("cli_toolchain", "kubectl", "1.30")) == 3
        assert engine.get_tier(_event("cli_toolchain", "cargo", "1.78")) == 3

    def test_tier_2_matches_label_in_tier_2_set(self) -> None:
        # Rule: a label in TIER_2_LABELS (framework/ci/test config/mcp) is
        # "notable" and classifies as Tier 2.
        engine = NarrationEngine()
        assert engine.get_tier(_event("project_structure", "framework", "FastAPI")) == 2
        assert engine.get_tier(_event("project_structure", "ci", "github actions")) == 2
        assert engine.get_tier(_event("project_structure", "test config", "pytest")) == 2
        assert engine.get_tier(_event("mcp_servers", "mcp", "filesystem")) == 2

    def test_tier_2_is_label_only_not_value(self) -> None:
        # Rule: Tier 2 keys off the LABEL only. A Tier-2 word appearing in the
        # value (not the label) does not by itself promote to Tier 2.
        engine = NarrationEngine()
        assert engine.get_tier(_event("git_state", "branch", "ci")) == 1

    def test_tier_1_is_the_default(self) -> None:
        # Rule: anything not matching Tier 3 or Tier 2 is "common" — Tier 1.
        engine = NarrationEngine()
        assert engine.get_tier(_event("git_state", "branch", "main")) == 1
        assert engine.get_tier(_event("cli_toolchain", "ripgrep", "14.0")) == 1


# ---------------------------------------------------------------------------
# (2) Frequency gating — should_narrate uses the running _discovery_count.
# ---------------------------------------------------------------------------


class TestShouldNarrate:
    """Locks: each tier's speaking cadence, driven by _discovery_count."""

    def test_tier_3_always_narrates(self) -> None:
        # Rule: Tier 3 (surprising) speaks on every discovery, regardless of
        # the running count.
        engine = NarrationEngine()
        event = _event("cli_toolchain", "docker", "27.0")
        for count in (0, 1, 2, 3, 7, 11):
            engine._discovery_count = count
            assert engine.should_narrate(event) is True

    def test_tier_2_narrates_every_third_discovery(self) -> None:
        # Rule: Tier 2 (notable) speaks only when _discovery_count % 3 == 0.
        engine = NarrationEngine()
        event = _event("project_structure", "ci", "github actions")
        expected = {0: True, 1: False, 2: False, 3: True, 6: True}
        for count, should in expected.items():
            engine._discovery_count = count
            assert engine.should_narrate(event) is should

    def test_tier_1_narrates_every_fourth_discovery(self) -> None:
        # Rule: Tier 1 (common) speaks only when _discovery_count % 4 == 0 —
        # the rarest cadence.
        engine = NarrationEngine()
        event = _event("git_state", "branch", "main")
        expected = {0: True, 1: False, 2: False, 3: False, 4: True, 8: True}
        for count, should in expected.items():
            engine._discovery_count = count
            assert engine.should_narrate(event) is should


# ---------------------------------------------------------------------------
# (3) No-reuse + escalation — get_narration never repeats an emitted line,
#     and a repeated category escalates to a different pool.
# ---------------------------------------------------------------------------


class TestGetNarrationNoReuseAndEscalation:
    """Locks: per-session line uniqueness and repeat-category escalation."""

    def test_emitted_lines_are_never_reused_across_a_run(self) -> None:
        # Rule: within one engine instance, no line in _used is ever emitted
        # twice — _select_line draws only from lines not already in _used.
        # Tier 3 always narrates, so a stream of docker events exercises the
        # selection path on every call with no gating noise.
        engine = NarrationEngine()
        event = _event("cli_toolchain", "docker", "27.0")

        emitted: list[str] = []
        for _ in range(6):
            message = engine.get_narration(event)
            assert message is not None  # Tier 3 always speaks
            emitted.append(message.text)

        assert len(emitted) == len(set(emitted)), (
            f"narration reused a line within one session: {emitted}"
        )
        # Every emitted line is recorded in _used so a future call cannot pick it.
        assert set(emitted) <= engine._used

    def test_repeated_category_escalates_to_a_different_line(self) -> None:
        # Rule: the first time a category is seen it draws from that category's
        # own pool; on repeat (seen count > 1) it escalates to the escalation
        # pool, so the second emission is a distinct line, not a duplicate.
        engine = NarrationEngine()
        event = _event("cli_toolchain", "docker", "27.0")

        first = engine.get_narration(event)
        second = engine.get_narration(event)
        assert first is not None
        assert second is not None
        assert engine._seen_categories["docker"] == 2  # category was repeated
        assert first.text != second.text  # escalation produced a different line

    def test_emitted_messages_are_narration_subtype(self) -> None:
        # Rule: every non-skipped emission is a FalcorMessage tagged
        # subtype="narration" (distinct from question/reflection messages).
        engine = NarrationEngine()
        message = engine.get_narration(_event("cli_toolchain", "docker", "27.0"))
        assert isinstance(message, FalcorMessage)
        assert message.subtype == "narration"


# ---------------------------------------------------------------------------
# (4) Skip semantics — a gated-out discovery returns None.
# ---------------------------------------------------------------------------


class TestGetNarrationSkip:
    """Locks: get_narration returns None when the tier cadence skips it."""

    def test_first_tier_1_discovery_is_skipped(self) -> None:
        # Rule: get_narration increments _discovery_count first, then gates.
        # A fresh engine's first Tier-1 discovery lands at count 1, and
        # 1 % 4 != 0, so the engine stays silent and returns None.
        engine = NarrationEngine()
        result = engine.get_narration(_event("git_state", "branch", "feature"))
        assert result is None

    def test_skipped_discovery_emits_no_line_into_used(self) -> None:
        # Rule: a skipped discovery selects no line, so _used stays empty —
        # the engine does not silently consume a line it never spoke.
        engine = NarrationEngine()
        engine.get_narration(_event("git_state", "branch", "feature"))
        assert engine._used == set()
