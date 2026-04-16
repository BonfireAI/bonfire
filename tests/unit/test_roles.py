"""Tests for AgentRole StrEnum and naming vocabulary."""

from bonfire.agent.roles import AgentRole
from bonfire.naming import ROLE_DISPLAY, DisplayNames


class TestAgentRole:
    """AgentRole StrEnum is the canonical identity for all agent roles."""

    def test_all_eight_roles_exist(self):
        assert len(AgentRole) == 8

    def test_values_are_lowercase_strings(self):
        for role in AgentRole:
            assert role.value == role.value.lower()
            assert "_" not in role.value or role.value.isidentifier()

    def test_researcher(self):
        assert AgentRole.RESEARCHER == "researcher"

    def test_tester(self):
        assert AgentRole.TESTER == "tester"

    def test_implementer(self):
        assert AgentRole.IMPLEMENTER == "implementer"

    def test_verifier(self):
        assert AgentRole.VERIFIER == "verifier"

    def test_publisher(self):
        assert AgentRole.PUBLISHER == "publisher"

    def test_reviewer(self):
        assert AgentRole.REVIEWER == "reviewer"

    def test_closer(self):
        assert AgentRole.CLOSER == "closer"

    def test_synthesizer(self):
        assert AgentRole.SYNTHESIZER == "synthesizer"

    def test_serialization_roundtrip(self):
        """StrEnum value serializes to string and deserializes back."""
        for role in AgentRole:
            serialized = role.value
            deserialized = AgentRole(serialized)
            assert deserialized is role

    def test_grep_friendly(self):
        """Every role value is a single word, no hyphens, no spaces."""
        for role in AgentRole:
            assert " " not in role.value
            assert "-" not in role.value


class TestNamingVocabulary:
    """Every role has professional and gamified display names."""

    def test_every_role_has_display_names(self):
        for role in AgentRole:
            assert role.value in ROLE_DISPLAY, f"Missing display name for {role.value}"

    def test_display_names_are_non_empty(self):
        for role_key, names in ROLE_DISPLAY.items():
            assert isinstance(names, DisplayNames)
            assert names.professional, f"Empty professional name for {role_key}"
            assert names.gamified, f"Empty gamified name for {role_key}"

    def test_no_generic_names_in_display(self):
        """Display names must not be identical to generic names."""
        for role_key, names in ROLE_DISPLAY.items():
            assert names.professional.lower() != role_key
            assert names.gamified.lower() != role_key

    def test_professional_names_contain_agent(self):
        """Professional role names follow 'X Agent' pattern."""
        for names in ROLE_DISPLAY.values():
            assert "Agent" in names.professional
