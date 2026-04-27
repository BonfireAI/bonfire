"""CONTRACT-LOCKED — BON-350 — RED tests for the role-tier maps.

Sage §D8 file 2 / 4 — locks the two frozen tables shipped by
``bonfire.agent.tiers``:

  * §D4 — ``DEFAULT_ROLE_TIER: Mapping[AgentRole, ModelTier]`` covers ALL
    nine canonical ``AgentRole`` members with the locked tier per §D4
    (4× ticket-cited bindings + 5× extended bindings inferred from role
    function).
  * §D-CL.7 — Implementation uses ``MappingProxyType`` (immutable).
  * §D2 — ``GAMIFIED_TO_GENERIC: Mapping[str, AgentRole]`` exposes ten
    workflow-emitted aliases (scout/knight/warrior/assayer/prover/bard/
    wizard/herald/sage/architect) → canonical ``AgentRole``.
  * §D-CL.1 — Both ``prover`` AND ``assayer`` map to ``AgentRole.VERIFIER``
    (workflow alias retention).

Drift-guards (cross-vocabulary parametrize, no-canonical-gamified-collision,
default-tier-distribution lock) extend the floor with adversarial coverage
citing §D3 + §D4 + the ``naming.py`` and ``agent/roles.py`` source-of-truth.

These tests are RED until BON-350 Warrior GREEN ships ``tiers.py``.
"""

from __future__ import annotations

from collections import Counter

import pytest


# ---------------------------------------------------------------------------
# DEFAULT_ROLE_TIER — shape over all nine canonical roles
# ---------------------------------------------------------------------------


class TestDefaultRoleTierShape:
    """``DEFAULT_ROLE_TIER`` is exhaustive, well-typed, and immutable."""

    def test_every_agentrole_has_a_tier(self) -> None:
        """Every value in ``AgentRole`` is a key in ``DEFAULT_ROLE_TIER``."""
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER

        assert set(DEFAULT_ROLE_TIER.keys()) == set(AgentRole)

    def test_tiers_are_modeltier_instances(self) -> None:
        """Every value in the map is a ``ModelTier`` member."""
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        for role, tier in DEFAULT_ROLE_TIER.items():
            assert isinstance(tier, ModelTier), (
                f"{role!r} maps to {tier!r}, expected ModelTier instance"
            )

    def test_no_extra_keys_beyond_agentrole(self) -> None:
        """The map has exactly nine entries — one per canonical role."""
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER

        assert len(DEFAULT_ROLE_TIER) == 9

    def test_mapping_is_immutable(self) -> None:
        """``DEFAULT_ROLE_TIER`` rejects assignment (MappingProxyType)."""
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        with pytest.raises(TypeError):
            DEFAULT_ROLE_TIER[AgentRole.TESTER] = ModelTier.REASONING  # type: ignore[index]


# ---------------------------------------------------------------------------
# Ticket-cited defaults — explicit bindings from BON-350 prose
# ---------------------------------------------------------------------------


class TestTicketCitedDefaults:
    """The four bindings cited in BON-350 prose are byte-exact (§D4)."""

    def test_researcher_maps_to_reasoning(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.RESEARCHER] is ModelTier.REASONING

    def test_tester_maps_to_fast(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.TESTER] is ModelTier.FAST

    def test_implementer_maps_to_fast(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.IMPLEMENTER] is ModelTier.FAST

    def test_reviewer_maps_to_reasoning(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.REVIEWER] is ModelTier.REASONING


# ---------------------------------------------------------------------------
# Extended defaults — Sage memo §D4 inferences for the other five roles
# ---------------------------------------------------------------------------


class TestExtendedDefaults:
    """The five non-ticket-cited bindings are locked per §D4 rationale."""

    def test_verifier_maps_to_fast(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.VERIFIER] is ModelTier.FAST

    def test_publisher_maps_to_fast(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.PUBLISHER] is ModelTier.FAST

    def test_closer_maps_to_fast(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.CLOSER] is ModelTier.FAST

    def test_synthesizer_maps_to_reasoning(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.SYNTHESIZER] is ModelTier.REASONING

    def test_analyst_maps_to_reasoning(self) -> None:
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        assert DEFAULT_ROLE_TIER[AgentRole.ANALYST] is ModelTier.REASONING


# ---------------------------------------------------------------------------
# GAMIFIED_TO_GENERIC — ten alias entries, immutable, well-typed
# ---------------------------------------------------------------------------


class TestGamifiedAliasMap:
    """``GAMIFIED_TO_GENERIC`` exposes the ten workflow-emitted aliases (§D2)."""

    def test_all_ten_gamified_aliases_resolve_to_agentroles(self) -> None:
        """The map has exactly ten entries with the locked alias set."""
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        expected_keys = {
            "scout",
            "knight",
            "warrior",
            "assayer",
            "prover",
            "bard",
            "wizard",
            "herald",
            "sage",
            "architect",
        }
        assert set(GAMIFIED_TO_GENERIC.keys()) == expected_keys
        assert len(GAMIFIED_TO_GENERIC) == 10

    def test_alias_values_are_agentroles(self) -> None:
        """Every value in the alias map is an ``AgentRole`` member."""
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        for alias, role in GAMIFIED_TO_GENERIC.items():
            assert isinstance(role, AgentRole), (
                f"{alias!r} maps to {role!r}, expected AgentRole instance"
            )

    def test_alias_keys_are_lowercase(self) -> None:
        """Every alias key is lowercase (workflows emit lowercase)."""
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        for alias in GAMIFIED_TO_GENERIC.keys():
            assert alias == alias.lower(), f"alias {alias!r} is not lowercase"

    def test_prover_aliases_to_verifier(self) -> None:
        """``prover`` AND ``assayer`` both map to ``AgentRole.VERIFIER`` (§D-CL.1)."""
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        assert GAMIFIED_TO_GENERIC["prover"] is AgentRole.VERIFIER
        assert GAMIFIED_TO_GENERIC["assayer"] is AgentRole.VERIFIER

    def test_alias_mapping_is_immutable(self) -> None:
        """``GAMIFIED_TO_GENERIC`` rejects assignment (MappingProxyType)."""
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        with pytest.raises(TypeError):
            GAMIFIED_TO_GENERIC["new"] = AgentRole.TESTER  # type: ignore[index]


# ---------------------------------------------------------------------------
# Drift-guards — cross-vocabulary parametrize, collision, distribution
# (CONTRACT-LOCKED)
# ---------------------------------------------------------------------------


_GAMIFIED_RESOLUTION_CASES: list[tuple[str, str]] = [
    # gamified-key -> AgentRole.value (as string for parametrize)
    ("scout", "researcher"),
    ("knight", "tester"),
    ("warrior", "implementer"),
    ("assayer", "verifier"),
    ("prover", "verifier"),
    ("bard", "publisher"),
    ("wizard", "reviewer"),
    ("herald", "closer"),
    ("sage", "synthesizer"),
    ("architect", "analyst"),
]


class TestCrossVocabularyParametrize:
    """Every gamified alias resolves to its expected canonical role.

    Cites Sage §D3 (alias table) + ``src/bonfire/naming.py:40-50`` for the
    professional<->gamified pairing. Guards against: a vocabulary-rename
    sweep silently re-mapping ``wizard`` to a different generic role
    (e.g. someone refactors wizard -> 'auditor' and forgets to update the
    GAMIFIED_TO_GENERIC entry).
    """

    @pytest.mark.parametrize(("gamified", "expected_role"), _GAMIFIED_RESOLUTION_CASES)
    def test_every_alias_resolves_to_expected_canonical_role(
        self, gamified: str, expected_role: str
    ):
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        assert GAMIFIED_TO_GENERIC[gamified] == AgentRole(expected_role)


class TestNoCanonicalGamifiedCollision:
    """No canonical AgentRole.value appears as a gamified alias key.

    Cites Sage §D3 (gamified vs canonical are TWO disjoint vocabularies)
    and ``src/bonfire/agent/roles.py:33-41`` for the canonical values.
    Guards against: a future contributor accidentally adding ``"researcher"``
    as a gamified alias (which would shadow the canonical-name path in the
    resolver and silently change semantics).
    """

    def test_no_canonical_role_value_appears_as_gamified_alias_key(self):
        from bonfire.agent.roles import AgentRole
        from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

        canonical_values = {role.value for role in AgentRole}
        gamified_keys = set(GAMIFIED_TO_GENERIC.keys())
        collision = canonical_values & gamified_keys
        assert collision == set(), (
            f"Vocabulary collision: {collision} appears as both canonical "
            "and gamified key; the resolver would short-circuit."
        )


class TestDefaultTierDistribution:
    """BALANCED is a fallback-only tier; canonical default is FAST/REASONING.

    Cites Sage §D4 (locked tier counts: 5x FAST, 4x REASONING, 0x BALANCED)
    and the rationale block at lines 357-369 of the memo. Guards against:
    a regression that quietly maps ``analyst -> BALANCED`` (one of the
    'Open questions for Anta', §D4 Q3) without updating this contract test.
    """

    def test_distribution_is_five_fast_four_reasoning_zero_balanced(self):
        from bonfire.agent.tiers import DEFAULT_ROLE_TIER, ModelTier

        counts = Counter(DEFAULT_ROLE_TIER.values())
        assert counts[ModelTier.FAST] == 5
        assert counts[ModelTier.REASONING] == 4
        assert counts[ModelTier.BALANCED] == 0
