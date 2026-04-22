"""RED tests for built-in personas via the shipped package — importlib.resources.

Complement to test_persona_defaults.py
--------------------------------------
``test_persona_defaults.py`` reads built-ins by repo-relative path
(``<repo>/src/bonfire/persona/builtins``). That is the right shape
during local development.

This file additionally loads built-ins via ``importlib.resources`` so
the tests also pass once the package is installed through a wheel,
where the ``src/`` layout is absent. It is the packaging contract for
bonfire-public.

Every built-in that ships MUST:

1. Pass ``PersonaLoader.validate(name)`` (schema strict).
2. Cover all eight AgentRole values in [display_names].
3. Satisfy PersonaProtocol structurally after ``load(name)``.
4. ``display_name(role)`` returns a non-empty string for every role.

The ``minimal`` persona additionally must:
- Have exactly one phrase per event type (no anti-repeat variance).
- Contain no personality markers (sire, milord, chamber, forge, ...).
"""

from __future__ import annotations

import importlib.resources
import tomllib
from pathlib import Path

import pytest

from bonfire.agent.roles import AgentRole
from bonfire.persona import (
    BasePersona,
    PersonaLoader,
    PersonaProtocol,
    PersonaSchemaError,
)

# ---------------------------------------------------------------------------
# Discovery of the shipped built-in directory (through importlib.resources)
# ---------------------------------------------------------------------------


def _builtin_dir() -> Path:
    """Return the package-shipped built-in persona directory."""
    return Path(str(importlib.resources.files("bonfire") / "persona" / "builtins"))


def _fake_user_dir() -> Path:
    """User dir that does not exist — we only want built-in discovery."""
    return Path(__file__).resolve().parent / "_nonexistent_user_personas"


@pytest.fixture()
def loader() -> PersonaLoader:
    return PersonaLoader(builtin_dir=_builtin_dir(), user_dir=_fake_user_dir())


def _load_phrases_toml(persona_name: str) -> dict[str, list[str]]:
    """Load and flatten phrases.toml for a built-in persona."""
    phrases_path = _builtin_dir() / persona_name / "phrases.toml"
    with phrases_path.open("rb") as f:
        raw = tomllib.load(f)
    result: dict[str, list[str]] = {}
    for category, events in raw.items():
        if isinstance(events, dict):
            for event_name, value in events.items():
                if isinstance(value, dict) and "phrases" in value:
                    key = f"{category}.{event_name}"
                    result[key] = value["phrases"]
    return result


def _load_persona_toml(persona_name: str) -> dict:
    """Load persona.toml for a built-in persona."""
    path = _builtin_dir() / persona_name / "persona.toml"
    with path.open("rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# The default persona ships
# ---------------------------------------------------------------------------


class TestDefaultPersonaShips:
    """A persona named ``default`` ships with the package."""

    def test_default_dir_exists(self) -> None:
        assert (_builtin_dir() / "default").is_dir(), (
            "bonfire-public must ship a built-in 'default' persona"
        )

    def test_default_has_persona_toml(self) -> None:
        assert (_builtin_dir() / "default" / "persona.toml").is_file()

    def test_default_has_phrases_toml(self) -> None:
        assert (_builtin_dir() / "default" / "phrases.toml").is_file()

    def test_default_loads_as_persona_protocol(self, loader: PersonaLoader) -> None:
        persona = loader.load("default")
        assert isinstance(persona, PersonaProtocol)

    def test_default_name(self, loader: PersonaLoader) -> None:
        persona = loader.load("default")
        assert persona.name == "default"

    def test_default_passes_schema_validation(self, loader: PersonaLoader) -> None:
        """Schema validation is strict; the default must pass it."""
        loader.validate("default")  # must not raise PersonaSchemaError

    def test_default_covers_all_agent_roles(self) -> None:
        """[display_names] lists every AgentRole value."""
        data = _load_persona_toml("default")
        display_names = data.get("display_names", {})
        for role in AgentRole:
            assert role.value in display_names, (
                f"default persona missing display name for role '{role.value}'"
            )

    @pytest.mark.parametrize("role", list(AgentRole), ids=lambda r: r.value)
    def test_default_display_name_returns_str_for_every_role(
        self, loader: PersonaLoader, role: AgentRole
    ) -> None:
        persona = loader.load("default")
        assert isinstance(persona, BasePersona)
        result = persona.display_name(role)
        assert isinstance(result, str)
        assert result != ""


# ---------------------------------------------------------------------------
# The minimal persona ships
# ---------------------------------------------------------------------------


class TestMinimalPersonaShips:
    """The ``minimal`` persona exists as a loadable fallback AND a discoverable built-in."""

    def test_minimal_dir_exists(self) -> None:
        assert (_builtin_dir() / "minimal").is_dir(), (
            "bonfire-public must ship a built-in 'minimal' persona"
        )

    def test_minimal_loads(self, loader: PersonaLoader) -> None:
        persona = loader.load("minimal")
        assert isinstance(persona, PersonaProtocol)
        assert persona.name == "minimal"

    def test_minimal_passes_schema_validation(self, loader: PersonaLoader) -> None:
        loader.validate("minimal")

    def test_minimal_covers_all_agent_roles(self) -> None:
        data = _load_persona_toml("minimal")
        display_names = data.get("display_names", {})
        for role in AgentRole:
            assert role.value in display_names, (
                f"minimal persona missing display name for role '{role.value}'"
            )

    def test_minimal_has_exactly_one_phrase_per_event(self) -> None:
        """Minimal is structural; no anti-repeat variance is intended."""
        phrases = _load_phrases_toml("minimal")
        assert len(phrases) > 0, "minimal persona must define some phrases"
        for event_type, phrase_list in phrases.items():
            assert len(phrase_list) == 1, (
                f"minimal {event_type!r} has {len(phrase_list)} phrases, expected 1"
            )

    def test_minimal_has_no_personality_markers(self) -> None:
        """Minimal phrases must be plain structural text."""
        personality_markers = [
            "sire",
            "milord",
            "chamber",
            "forge",
            "flame",
            "alas",
            "hark",
            "prithee",
            "decree",
            "summon",
        ]
        phrases = _load_phrases_toml("minimal")
        for event_type, phrase_list in phrases.items():
            for phrase in phrase_list:
                lower = phrase.lower()
                for marker in personality_markers:
                    assert marker not in lower, (
                        f"Personality marker '{marker}' in minimal "
                        f"{event_type}: {phrase!r}"
                    )


# ---------------------------------------------------------------------------
# Passelewe — optional named example; if present, must pass schema
# ---------------------------------------------------------------------------


class TestPasseleweIfPresent:
    """If ``passelewe`` ships, it MUST be schema-valid."""

    def _passelewe_present(self) -> bool:
        return (_builtin_dir() / "passelewe").is_dir()

    def test_passelewe_loads_if_present(self, loader: PersonaLoader) -> None:
        if not self._passelewe_present():
            pytest.skip("passelewe not shipped in this build")
        persona = loader.load("passelewe")
        assert isinstance(persona, PersonaProtocol)
        assert persona.name == "passelewe"

    def test_passelewe_passes_schema(self, loader: PersonaLoader) -> None:
        if not self._passelewe_present():
            pytest.skip("passelewe not shipped in this build")
        loader.validate("passelewe")

    def test_passelewe_covers_all_agent_roles(self) -> None:
        if not self._passelewe_present():
            pytest.skip("passelewe not shipped in this build")
        data = _load_persona_toml("passelewe")
        display_names = data.get("display_names", {})
        for role in AgentRole:
            assert role.value in display_names, (
                f"passelewe missing display name for role '{role.value}'"
            )


# ---------------------------------------------------------------------------
# Cross-built-in shape checks
# ---------------------------------------------------------------------------


class TestEveryShippedBuiltinPassesSchema:
    """Whatever ships MUST pass schema validation. No exceptions."""

    def _discover_shipped(self) -> list[str]:
        """Return the list of persona directories under the built-in root."""
        root = _builtin_dir()
        if not root.is_dir():
            return []
        return sorted(
            child.name
            for child in root.iterdir()
            if child.is_dir() and (child / "persona.toml").exists()
        )

    def test_at_least_default_and_minimal_ship(self) -> None:
        shipped = self._discover_shipped()
        assert "default" in shipped, (
            f"'default' must ship as a built-in persona; got {shipped}"
        )
        assert "minimal" in shipped, (
            f"'minimal' must ship as a built-in persona; got {shipped}"
        )

    def test_every_shipped_builtin_passes_schema(
        self, loader: PersonaLoader
    ) -> None:
        """Any built-in that ships is schema-valid."""
        for name in self._discover_shipped():
            try:
                loader.validate(name)
            except PersonaSchemaError as exc:
                pytest.fail(
                    f"Built-in persona '{name}' failed schema validation: {exc}"
                )
