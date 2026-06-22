# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract — ``DefaultToolPolicy.tools_for`` accepts either vocabulary.

ADR-001 § Ratified Exceptions promises a "planned forward-compat patch" that
teaches ``DefaultToolPolicy.tools_for`` to accept either the gamified
(``scout``, ``knight``, ``warrior``, ...) OR the generic (``researcher``,
``tester``, ``implementer``, ...) role string. The floor table's internal
keys stay gamified to preserve the W4.1 contract; the public surface absorbs
either vocabulary.

This file pins the new behavior. The 1352-LOC byte-for-byte contract in
``test_tool_policy.py`` MUST stay green — every gamified row continues to
match. New behavior: each generic alias resolves to the SAME list.

Source of truth for aliases: ``bonfire.agent.tiers.GAMIFIED_TO_GENERIC``.
"""

from __future__ import annotations

import pytest

from bonfire.dispatch.tool_policy import DefaultToolPolicy

# Authoritative gamified -> generic mapping, kept in sync with the
# enumerated _FLOOR keys.
GAMIFIED_TO_GENERIC_FLOOR = {
    "scout": "researcher",
    "knight": "tester",
    "warrior": "implementer",
    "prover": "verifier",
    "bard": "publisher",
    "wizard": "reviewer",
    "steward": "closer",
    "sage": "synthesizer",
}


class TestGenericNamesResolveToGamifiedFloor:
    """Each generic alias returns the same list as its gamified key."""

    @pytest.mark.parametrize(
        ("gamified", "generic"),
        sorted(GAMIFIED_TO_GENERIC_FLOOR.items()),
    )
    def test_generic_matches_gamified_floor(self, gamified: str, generic: str) -> None:
        policy = DefaultToolPolicy()
        assert policy.tools_for(generic) == policy.tools_for(gamified), (
            f"{generic!r} (generic) and {gamified!r} (gamified) must resolve identically"
        )

    def test_scout_and_researcher_same_list(self) -> None:
        """Cited contract — scout (gamified) and researcher (generic) MUST match."""
        policy = DefaultToolPolicy()
        expected = ["Read", "Write", "Grep", "WebSearch", "WebFetch"]
        assert policy.tools_for("scout") == expected
        assert policy.tools_for("researcher") == expected

    def test_warrior_and_implementer_same_list(self) -> None:
        policy = DefaultToolPolicy()
        expected = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert policy.tools_for("warrior") == expected
        assert policy.tools_for("implementer") == expected

    def test_knight_and_tester_same_list(self) -> None:
        policy = DefaultToolPolicy()
        expected = ["Read", "Write", "Edit", "Grep", "Glob"]
        assert policy.tools_for("knight") == expected
        assert policy.tools_for("tester") == expected

    def test_prover_and_verifier_same_list(self) -> None:
        """``cleric`` and ``prover`` both alias to ``verifier`` in
        ``GAMIFIED_TO_GENERIC``; ``prover`` is the floor key.
        ``tools_for("verifier")`` MUST return the prover floor."""
        policy = DefaultToolPolicy()
        expected = ["Read", "Bash", "Grep", "Glob"]
        assert policy.tools_for("prover") == expected
        assert policy.tools_for("verifier") == expected


class TestNormalizationIsStringFriendly:
    """Whitespace + case forgiveness on the generic alias path."""

    def test_empty_string_returns_empty(self) -> None:
        assert DefaultToolPolicy().tools_for("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert DefaultToolPolicy().tools_for("   ") == []

    def test_uppercase_generic_resolves(self) -> None:
        """``RESEARCHER`` is normalized to lowercase and resolves to scout floor."""
        policy = DefaultToolPolicy()
        assert policy.tools_for("RESEARCHER") == policy.tools_for("scout")

    def test_padded_generic_resolves(self) -> None:
        """Surrounding whitespace is stripped before lookup."""
        policy = DefaultToolPolicy()
        assert policy.tools_for("  implementer  ") == policy.tools_for("warrior")


class TestUnknownGenericReturnsEmpty:
    """Generics without a floor entry (analyst / architect) MUST return []."""

    def test_analyst_returns_empty(self) -> None:
        """The Analyst role has no floor entry (no architect/analyst in _FLOOR)."""
        assert DefaultToolPolicy().tools_for("analyst") == []

    def test_nonexistent_role_returns_empty(self) -> None:
        assert DefaultToolPolicy().tools_for("nonexistent_role") == []


class TestNormalizationDoesNotMutateFloor:
    """Calling tools_for via either alias must not mutate state visible to
    the other path."""

    def test_mutating_generic_result_isolated(self) -> None:
        policy = DefaultToolPolicy()
        researcher_list = policy.tools_for("researcher")
        researcher_list.append("Bash")
        # The gamified path is untouched.
        assert policy.tools_for("scout") == [
            "Read",
            "Write",
            "Grep",
            "WebSearch",
            "WebFetch",
        ]
        # And re-querying the generic also returns a fresh list.
        assert policy.tools_for("researcher") == [
            "Read",
            "Write",
            "Grep",
            "WebSearch",
            "WebFetch",
        ]

    def test_purity_via_generic(self) -> None:
        """100 calls via the generic alias return the same list each time."""
        policy = DefaultToolPolicy()
        baseline = policy.tools_for("implementer")
        for _ in range(100):
            assert policy.tools_for("implementer") == baseline


class TestPolicyRemainsProtocolSatisfied:
    """The Protocol contract is unchanged — DefaultToolPolicy still has
    ``tools_for(role: str) -> list[str]``."""

    def test_tools_for_returns_list_for_generic(self) -> None:
        assert isinstance(DefaultToolPolicy().tools_for("researcher"), list)

    def test_tools_for_returns_list_for_unknown(self) -> None:
        assert isinstance(DefaultToolPolicy().tools_for("xyz"), list)
