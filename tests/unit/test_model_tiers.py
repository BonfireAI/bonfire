"""CONTRACT-LOCKED — BON-350 — RED tests for the ``ModelTier`` enum.

Sage §D8 file 1 / 4 — locks the capability-tier vocabulary delivered by
``bonfire.agent.tiers``:

  * §D3 — ``ModelTier(StrEnum)`` with three values exactly:
      ``REASONING = "reasoning"``, ``FAST = "fast"``, ``BALANCED = "balanced"``.
  * §D3 — Iteration order is ``[REASONING, FAST, BALANCED]``.
  * §D3 — Values are lowercase, ASCII, no separators (grep-friendly invariants
    mirroring ``test_roles.py`` for ``AgentRole``).
  * §D3 — Serialization roundtrip via ``StrEnum`` semantics.
  * §D3 — No ordering semantics (tiers are categorical, not ordinal).
  * §D2 / §D-CL.3 — ``ModelTier`` is importable from BOTH
    ``bonfire.agent.tiers`` and ``bonfire.agent``; both paths resolve to
    the same class object.

Drift-guards (byte-exact value lock, StrEnum cardinality, JSONL portability)
extend the floor with adversarial coverage citing §D3.

These tests are RED until BON-350 Warrior GREEN ships ``tiers.py`` and
the package re-export wiring.
"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Import surface — module + package re-export
# ---------------------------------------------------------------------------


class TestModelTierEnumExists:
    """``ModelTier`` is importable from the module and re-exported by the package."""

    def test_modeltier_imports_from_module(self) -> None:
        """``from bonfire.agent.tiers import ModelTier`` resolves."""
        from bonfire.agent.tiers import ModelTier

        assert ModelTier is not None

    def test_modeltier_imports_from_package(self) -> None:
        """``from bonfire.agent import ModelTier`` resolves (re-export)."""
        from bonfire.agent import ModelTier

        assert ModelTier is not None

    def test_module_and_package_export_same_class(self) -> None:
        """Both import paths resolve to the SAME class object."""
        from bonfire.agent import ModelTier as PackageModelTier
        from bonfire.agent.tiers import ModelTier as ModuleModelTier

        assert PackageModelTier is ModuleModelTier


# ---------------------------------------------------------------------------
# Values — three locked tiers
# ---------------------------------------------------------------------------


class TestModelTierValues:
    """The enum has exactly three members with locked string values."""

    def test_three_values_exist(self) -> None:
        """``ModelTier`` has exactly three members."""
        from bonfire.agent.tiers import ModelTier

        assert len(list(ModelTier)) == 3

    def test_reasoning_value(self) -> None:
        """``ModelTier.REASONING.value == "reasoning"``."""
        from bonfire.agent.tiers import ModelTier

        assert ModelTier.REASONING.value == "reasoning"

    def test_fast_value(self) -> None:
        """``ModelTier.FAST.value == "fast"``."""
        from bonfire.agent.tiers import ModelTier

        assert ModelTier.FAST.value == "fast"

    def test_balanced_value(self) -> None:
        """``ModelTier.BALANCED.value == "balanced"``."""
        from bonfire.agent.tiers import ModelTier

        assert ModelTier.BALANCED.value == "balanced"


# ---------------------------------------------------------------------------
# Shape — invariants over the enum
# ---------------------------------------------------------------------------


class TestModelTierShape:
    """Invariants on the enum's shape, ordering, and value formatting."""

    def test_iteration_order_is_reasoning_fast_balanced(self) -> None:
        """Declaration order must be REASONING -> FAST -> BALANCED (§D3)."""
        from bonfire.agent.tiers import ModelTier

        assert list(ModelTier) == [
            ModelTier.REASONING,
            ModelTier.FAST,
            ModelTier.BALANCED,
        ]

    def test_values_are_lowercase_strings(self) -> None:
        """Every value is a lowercase ASCII string (StrEnum invariant)."""
        from bonfire.agent.tiers import ModelTier

        for member in ModelTier:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()
            assert member.value.isascii()

    def test_grep_friendly_no_separators(self) -> None:
        """No underscores, hyphens, or whitespace in any value."""
        from bonfire.agent.tiers import ModelTier

        for member in ModelTier:
            assert "_" not in member.value
            assert "-" not in member.value
            assert " " not in member.value

    def test_serialization_roundtrip(self) -> None:
        """``ModelTier(value)`` round-trips through string form."""
        from bonfire.agent.tiers import ModelTier

        for member in ModelTier:
            assert ModelTier(member.value) is member
            # StrEnum semantics: equality with the raw string.
            assert member == member.value

    def test_no_ordering_semantics_assertion(self) -> None:
        """Tiers are categorical, not ordinal — ``<`` / ``>`` must not be used.

        ``StrEnum`` inherits ``str`` comparison, which compares lexicographically
        — that's a footgun. This test pins that no production code may rely
        on a meaningful ordinal interpretation by asserting that the
        lexicographic order does NOT match the canonical iteration order.
        """
        from bonfire.agent.tiers import ModelTier

        canonical = [ModelTier.REASONING, ModelTier.FAST, ModelTier.BALANCED]
        lexicographic = sorted(canonical, key=lambda m: m.value)
        # Iteration order is reasoning, fast, balanced.
        # Lexicographic order is balanced, fast, reasoning.
        # They MUST differ — asserting that proves no one can rely on
        # natural string ordering meaning anything tier-wise.
        assert canonical != lexicographic


# ---------------------------------------------------------------------------
# Drift-guards — byte-exact + StrEnum + JSONL portability (CONTRACT-LOCKED)
# ---------------------------------------------------------------------------


class TestModelTierByteEquality:
    """Byte-exact value lock (Sage §D3 'lowercase, ASCII').

    Guards against: a future contributor flipping ``REASONING = "Reasoning"``
    or ``REASONING = "reasoning "`` (trailing space) and a string-equality
    test still passing because StrEnum coerces. Length + ascii-encode
    checks catch both cases.
    """

    def test_reasoning_value_is_byte_exact(self):
        from bonfire.agent.tiers import ModelTier

        assert ModelTier.REASONING.value == "reasoning"
        assert len(ModelTier.REASONING.value) == 9
        assert ModelTier.REASONING.value.encode("ascii") == b"reasoning"

    def test_fast_value_is_byte_exact(self):
        from bonfire.agent.tiers import ModelTier

        assert ModelTier.FAST.value == "fast"
        assert len(ModelTier.FAST.value) == 4
        assert ModelTier.FAST.value.encode("ascii") == b"fast"

    def test_balanced_value_is_byte_exact(self):
        from bonfire.agent.tiers import ModelTier

        assert ModelTier.BALANCED.value == "balanced"
        assert len(ModelTier.BALANCED.value) == 8
        assert ModelTier.BALANCED.value.encode("ascii") == b"balanced"


class TestModelTierStrEnumSemantics:
    """StrEnum invariants (Sage §D3 'Type is StrEnum, not Literal').

    Guards against: a refactor changing ModelTier to a plain ``Enum`` or
    ``str | Literal[...]``. AgentRole precedent at
    ``src/bonfire/agent/roles.py:15`` is StrEnum; ModelTier MUST match.
    """

    def test_each_tier_isinstance_str(self):
        from bonfire.agent.tiers import ModelTier

        for tier in ModelTier:
            assert isinstance(tier, str), (
                f"{tier!r} must be a str instance (StrEnum invariant)"
            )

    def test_set_cardinality_no_fossils(self):
        """Sage §D3: 'Three values exactly.' Ratchet against fossil resurrection."""
        from bonfire.agent.tiers import ModelTier

        assert set(ModelTier) == {
            ModelTier.REASONING,
            ModelTier.FAST,
            ModelTier.BALANCED,
        }
        # Membership cardinality matches; no extra members introduced.
        assert len({t.value for t in ModelTier}) == 3


class TestModelTierJsonSerializable:
    """JSON-serializability (Sage §D3 'used in TOML, JSONL, CLI').

    Guards against: a refactor that wraps the value in a non-JSON-safe type.
    The Sage memo states tier values are 'used in TOML, JSONL, CLI output,
    and grep patterns' (lines 122-125 of the memo's package surface block) --
    JSONL is the loud loss-of-portability signal.
    """

    def test_each_tier_value_round_trips_through_json(self):
        from bonfire.agent.tiers import ModelTier

        for tier in ModelTier:
            payload = json.dumps({"tier": tier.value})
            decoded = json.loads(payload)
            assert decoded["tier"] == tier.value
