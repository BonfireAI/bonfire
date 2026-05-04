"""RED tests for bonfire.persona core — PersonaProtocol, PhraseBank, BasePersona.

Scope of this file
------------------
1. PersonaProtocol is importable, a typing.Protocol, @runtime_checkable,
   and NOT an ABC.
2. PhraseBank (renamed from v1's ``PhrasePool``) is importable from
   ``bonfire.persona``, lives in a module whose final segment is
   ``phrase_bank``, and selects phrases with anti-repeat + variant
   fallback semantics.
3. BasePersona satisfies PersonaProtocol, accepts an optional
   ``display_names={}`` kwarg, and exposes
   ``display_name(role: AgentRole) -> str`` — gamified-wins-else-
   professional-fallback. NEVER raises for any of the eight canonical
   AgentRole values.

Sage-locked convergences enforced here
--------------------------------------
* ``PhraseBank`` is the class name (NOT ``PhrasePool``).
* The module filename is ``phrase_bank.py`` (NOT ``pool.py``).
* ``bonfire.persona`` must not re-export a stale ``PhrasePool``.
* ``display_name(role)`` is part of the public contract (D2 in the
  Sage decision log).

Every import below should fail with ImportError in RED state.
"""

from __future__ import annotations

import abc
import importlib
from typing import Protocol

import pytest

from bonfire.agent.roles import AgentRole
from bonfire.models.events import BonfireEvent, StageCompleted, StageStarted
from bonfire.naming import ROLE_DISPLAY
from bonfire.persona import BasePersona, PersonaProtocol, PhraseBank

# All 8 AgentRole values — used for parametrisation of display_name tests.
ALL_AGENT_ROLES: list[AgentRole] = list(AgentRole)


# ---------------------------------------------------------------------------
# PersonaProtocol — importability and shape
# ---------------------------------------------------------------------------


class TestPersonaProtocolImport:
    """PersonaProtocol is importable, a Protocol, runtime-checkable, not an ABC."""

    def test_persona_protocol_importable(self) -> None:
        assert PersonaProtocol is not None

    def test_persona_protocol_is_typing_protocol(self) -> None:
        assert issubclass(PersonaProtocol, Protocol)

    def test_persona_protocol_is_runtime_checkable(self) -> None:
        """isinstance() must not raise TypeError — requires @runtime_checkable."""
        assert isinstance(object(), PersonaProtocol) is False

    def test_persona_protocol_is_not_abc(self) -> None:
        assert not issubclass(PersonaProtocol, abc.ABC)


# ---------------------------------------------------------------------------
# PersonaProtocol — structural conformance
# ---------------------------------------------------------------------------


class TestPersonaProtocolConformance:
    """A class with ``name`` + ``format_event`` + ``format_summary`` conforms."""

    def test_conforming_class_passes_isinstance(self) -> None:
        class _Good:
            @property
            def name(self) -> str:
                return "test"

            def format_event(self, event: BonfireEvent):
                return None

            def format_summary(self, stats: dict) -> str:
                return ""

        assert isinstance(_Good(), PersonaProtocol)

    def test_missing_name_fails_isinstance(self) -> None:
        class _NoName:
            def format_event(self, event: BonfireEvent):
                return None

            def format_summary(self, stats: dict) -> str:
                return ""

        assert not isinstance(_NoName(), PersonaProtocol)

    def test_missing_format_event_fails_isinstance(self) -> None:
        class _NoFormatEvent:
            @property
            def name(self) -> str:
                return "test"

            def format_summary(self, stats: dict) -> str:
                return ""

        assert not isinstance(_NoFormatEvent(), PersonaProtocol)

    def test_missing_format_summary_fails_isinstance(self) -> None:
        class _NoFormatSummary:
            @property
            def name(self) -> str:
                return "test"

            def format_event(self, event: BonfireEvent):
                return None

        assert not isinstance(_NoFormatSummary(), PersonaProtocol)

    def test_name_property_returns_str(self) -> None:
        """A conforming instance's ``name`` is a str."""

        class _Named:
            @property
            def name(self) -> str:
                return "default"

            def format_event(self, event: BonfireEvent):
                return None

            def format_summary(self, stats: dict) -> str:
                return ""

        obj = _Named()
        assert isinstance(obj.name, str)
        assert obj.name == "default"


# ---------------------------------------------------------------------------
# PhraseBank — importability, rename sanity, construction
# ---------------------------------------------------------------------------


class TestPhraseBankImport:
    """PhraseBank is importable from ``bonfire.persona`` (was: PhrasePool)."""

    def test_phrase_bank_importable(self) -> None:
        assert PhraseBank is not None

    def test_phrase_bank_class_name_is_exactly_phrase_bank(self) -> None:
        """The class is named ``PhraseBank`` — not PhrasePool, not PhrasePoolBank."""
        assert PhraseBank.__name__ == "PhraseBank"

    def test_phrase_bank_lives_in_phrase_bank_module(self) -> None:
        """PhraseBank must be defined in a module ending in ``.phrase_bank``.

        Guards against accidental survival of ``pool.py``.
        """
        final_segment = PhraseBank.__module__.rsplit(".", 1)[-1]
        assert final_segment == "phrase_bank", (
            f"PhraseBank.__module__={PhraseBank.__module__!r}; "
            f"expected final segment 'phrase_bank', got {final_segment!r}"
        )

    def test_constructor_accepts_dict(self) -> None:
        """PhraseBank takes a dict[str, list[str]] of categorised phrases."""
        bank = PhraseBank(
            {
                "stage.started": ["The {stage_name} awakens", "Summoning {stage_name}"],
                "stage.completed": ["{stage_name} done", "Finished {stage_name}"],
            }
        )
        assert bank is not None


# ---------------------------------------------------------------------------
# PhraseBank — select() behaviour
# ---------------------------------------------------------------------------


class TestPhraseBankSelect:
    """PhraseBank.select() formats with context and avoids consecutive repeats."""

    def _make_bank(self) -> PhraseBank:
        return PhraseBank(
            {
                "stage.started": [
                    "The {stage_name} awakens",
                    "Summoning {stage_name}",
                ],
                "stage.completed": [
                    "{stage_name} done",
                    "Finished {stage_name}",
                ],
                "stage.failed": [
                    "only one phrase here",
                ],
            }
        )

    def test_select_returns_formatted_string(self) -> None:
        bank = self._make_bank()
        result = bank.select("stage.completed", {"stage_name": "scout"})
        assert isinstance(result, str)
        assert "scout" in result

    def test_select_formats_context_dict(self) -> None:
        """Phrases format with context dict:
        ``'{stage_name} done'`` + context → ``'scout done'``.
        """
        bank = PhraseBank({"stage.completed": ["{stage_name} done"]})
        result = bank.select("stage.completed", {"stage_name": "scout"})
        assert result == "scout done"

    def test_select_returns_none_for_unknown_event_type(self) -> None:
        bank = self._make_bank()
        result = bank.select("unknown.event", {"stage_name": "scout"})
        assert result is None

    def test_select_returns_none_for_empty_bank(self) -> None:
        """An event type mapped to an empty list returns None."""
        bank = PhraseBank({"stage.started": []})
        result = bank.select("stage.started", {})
        assert result is None

    def test_select_never_repeats_consecutively(self) -> None:
        """Given a bank of >= 2 phrases, consecutive calls never repeat."""
        bank = self._make_bank()
        ctx = {"stage_name": "scout"}
        previous = bank.select("stage.started", ctx)
        for _ in range(20):
            current = bank.select("stage.started", ctx)
            assert current != previous, f"Anti-repeat violated: got '{current}' twice in a row"
            previous = current

    def test_select_single_item_bank_always_returns_it(self) -> None:
        """A bank with exactly one phrase always returns it (no anti-repeat needed)."""
        bank = self._make_bank()
        result = bank.select("stage.failed", {})
        assert result == "only one phrase here"
        # Call again — same phrase is fine for size-1 bank.
        result2 = bank.select("stage.failed", {})
        assert result2 == "only one phrase here"

    def test_select_with_variant(self) -> None:
        """``select(..., variant=X)`` uses the ``event:X`` bank if present."""
        bank = PhraseBank(
            {
                "stage.completed": ["{stage_name} done"],
                "stage.completed:after_failure": ["recovered from {stage_name}"],
            }
        )
        result = bank.select("stage.completed", {"stage_name": "scout"}, variant="after_failure")
        assert result == "recovered from scout"

    def test_select_with_missing_variant_falls_back(self) -> None:
        """``select(..., variant=X)`` falls back to the base bank when X missing."""
        bank = PhraseBank({"stage.completed": ["{stage_name} done"]})
        result = bank.select("stage.completed", {"stage_name": "scout"}, variant="nonexistent")
        assert result == "scout done"

    def test_select_missing_placeholder_is_safe(self) -> None:
        """Missing context keys do not raise — placeholder preserved or safe-formatted."""
        bank = PhraseBank({"stage.completed": ["{stage_name} done in {missing_key}"]})
        result = bank.select("stage.completed", {"stage_name": "scout"})
        assert isinstance(result, str)
        assert "scout" in result


# ---------------------------------------------------------------------------
# BasePersona — importability and protocol conformance
# ---------------------------------------------------------------------------


class TestBasePersonaImport:
    """BasePersona is importable from ``bonfire.persona`` and conforms to Protocol."""

    def test_base_persona_importable(self) -> None:
        assert BasePersona is not None

    def test_base_persona_satisfies_protocol(self) -> None:
        persona = BasePersona(name="test")
        assert isinstance(persona, PersonaProtocol)


# ---------------------------------------------------------------------------
# BasePersona — behaviour on events/summaries
# ---------------------------------------------------------------------------


class TestBasePersonaBehavior:
    """BasePersona returns renderables for known events, None otherwise."""

    def test_name_returns_string(self) -> None:
        persona = BasePersona(name="default")
        assert persona.name == "default"

    def test_format_event_returns_none_for_unknown_event(self) -> None:
        """An event type the persona doesn't handle returns None."""
        persona = BasePersona(name="test")
        event = StageStarted(
            session_id="s1",
            sequence=0,
            stage_name="unknown_stage",
            agent_name="agent1",
        )
        assert persona.format_event(event) is None

    def test_format_event_returns_renderable_for_known_event(self) -> None:
        """A known event yields a non-None renderable."""
        persona = BasePersona(
            name="test",
            phrases={"stage.completed": ["{stage_name} is done"]},
        )
        event = StageCompleted(
            session_id="s1",
            sequence=0,
            stage_name="scout",
            agent_name="agent1",
            duration_seconds=1.5,
            cost_usd=0.01,
        )
        assert persona.format_event(event) is not None

    def test_format_summary_returns_renderable(self) -> None:
        persona = BasePersona(name="test")
        result = persona.format_summary({"total_cost": 0.42, "stages": 3})
        assert result is not None

    def test_base_persona_uses_phrase_bank_internally(self) -> None:
        """BasePersona is implemented via PhraseBank — not a stale PhrasePool.

        Defensive: reading the backing module must not expose ``PhrasePool``
        as a module-level attribute.
        """
        mod = importlib.import_module(BasePersona.__module__)
        assert not hasattr(mod, "PhrasePool"), (
            f"Stale attribute 'PhrasePool' found on {BasePersona.__module__}. "
            "Rename to PhraseBank must be total."
        )


# ---------------------------------------------------------------------------
# BasePersona.display_name(role) — parametrised over all 8 AgentRole values
# ---------------------------------------------------------------------------


class TestBasePersonaDisplayNameLookup:
    """``BasePersona.display_name(role: AgentRole) -> str`` for every role.

    Contract (Sage D2, adopted from Knight B):
      - Accepts any AgentRole value, returns str.
      - If the persona has a gamified name for that role, returns it.
      - Otherwise returns the professional name from ``naming.ROLE_DISPLAY``.
      - NEVER raises for any canonical AgentRole value.
    """

    def _persona_with_full_display_map(self) -> BasePersona:
        """BasePersona constructed with a complete gamified display-name map."""
        display_map = {role.value: ROLE_DISPLAY[role.value].gamified for role in AgentRole}
        return BasePersona(
            name="fullmap",
            phrases={},
            display_names=display_map,
        )

    def _persona_with_empty_display_map(self) -> BasePersona:
        """BasePersona constructed with no gamified display names."""
        return BasePersona(name="emptymap", phrases={}, display_names={})

    # ---- Full-map case ----------------------------------------------------

    @pytest.mark.parametrize("role", ALL_AGENT_ROLES, ids=lambda r: r.value)
    def test_display_name_returns_gamified_when_present(self, role: AgentRole) -> None:
        """When a persona has a gamified mapping, that wins over the professional."""
        persona = self._persona_with_full_display_map()
        expected = ROLE_DISPLAY[role.value].gamified
        assert persona.display_name(role) == expected

    @pytest.mark.parametrize("role", ALL_AGENT_ROLES, ids=lambda r: r.value)
    def test_display_name_returns_str(self, role: AgentRole) -> None:
        """Return type is str for every AgentRole."""
        persona = self._persona_with_full_display_map()
        assert isinstance(persona.display_name(role), str)

    @pytest.mark.parametrize("role", ALL_AGENT_ROLES, ids=lambda r: r.value)
    def test_display_name_nonempty_for_every_role(self, role: AgentRole) -> None:
        """No role ever returns an empty string."""
        persona = self._persona_with_full_display_map()
        assert persona.display_name(role) != ""

    # ---- Empty-map fallback ----------------------------------------------

    @pytest.mark.parametrize("role", ALL_AGENT_ROLES, ids=lambda r: r.value)
    def test_display_name_falls_back_to_professional(self, role: AgentRole) -> None:
        """Missing gamified names fall back to the professional name."""
        persona = self._persona_with_empty_display_map()
        expected_professional = ROLE_DISPLAY[role.value].professional
        assert persona.display_name(role) == expected_professional

    @pytest.mark.parametrize("role", ALL_AGENT_ROLES, ids=lambda r: r.value)
    def test_display_name_never_raises(self, role: AgentRole) -> None:
        """Lookup never raises for any AgentRole, with or without gamified map."""
        full = self._persona_with_full_display_map()
        empty = self._persona_with_empty_display_map()
        a = full.display_name(role)
        b = empty.display_name(role)
        assert a is not None
        assert b is not None

    # ---- Partial-map case ------------------------------------------------

    def test_display_name_partial_map_gamified_wins_where_present(self) -> None:
        """Partial map: gamified for mapped roles, professional for the rest."""
        partial = {AgentRole.RESEARCHER.value: "Scout"}
        persona = BasePersona(name="partial", phrases={}, display_names=partial)
        assert persona.display_name(AgentRole.RESEARCHER) == "Scout"
        assert (
            persona.display_name(AgentRole.TESTER)
            == ROLE_DISPLAY[AgentRole.TESTER.value].professional
        )

    def test_display_name_accepts_strenum_value(self) -> None:
        """Lookup accepts AgentRole directly (it's a StrEnum / str subclass)."""
        persona = self._persona_with_full_display_map()
        result = persona.display_name(AgentRole.TESTER)
        assert isinstance(result, str)
        assert result == ROLE_DISPLAY["tester"].gamified


# ---------------------------------------------------------------------------
# BasePersona.display_name — boundary cases
# ---------------------------------------------------------------------------


class TestDisplayNameBoundaries:
    """Edge cases for the display_name contract."""

    def test_display_names_default_to_empty_if_omitted(self) -> None:
        """Constructing BasePersona without ``display_names`` yields pure fallback."""
        persona = BasePersona(name="no_map", phrases={})
        for role in AgentRole:
            assert persona.display_name(role) == ROLE_DISPLAY[role.value].professional
