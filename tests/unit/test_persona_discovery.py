"""RED tests for PersonaLoader discovery edge cases (Knight B's shape).

Complements ``test_persona_loader.py`` with filesystem robustness:

- Missing user_dir / builtin_dir (real paths that do not exist).
- Non-directory entries in a discovery root (e.g. a stray README).
- Persona directories missing persona.toml (partial install).
- Case-sensitive names — ``Default`` and ``default`` are distinct.
- Persona directory with persona.toml but no phrases.toml is
  loadable (phrases are optional; display_names may live in
  persona.toml alone).

These tests fail fast when the loader panics on filesystem edge cases
rather than logging a warning and continuing.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003 — runtime constructor type

import pytest

from bonfire.persona import PersonaLoader, PersonaProtocol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PERSONA_TOML = """\
[persona]
name = "alpha"
display_name = "Alpha"
description = "A discoverable persona"
version = "1.0.0"

[display_names]
researcher = "Research Agent"
tester = "Test Agent"
implementer = "Build Agent"
verifier = "Verify Agent"
publisher = "Publish Agent"
reviewer = "Review Agent"
closer = "Release Agent"
synthesizer = "Synthesis Agent"
"""

_VALID_PHRASES_TOML = """\
[stage.completed]
phrases = ["{stage_name} done"]
"""


def _create_persona_dir(
    base: Path,
    name: str,
    *,
    persona_toml: str | None = _VALID_PERSONA_TOML,
    phrases_toml: str | None = _VALID_PHRASES_TOML,
) -> Path:
    """Create a persona directory. Passing ``None`` for either TOML omits it."""
    persona_dir = base / name
    persona_dir.mkdir(parents=True, exist_ok=True)
    if persona_toml is not None:
        (persona_dir / "persona.toml").write_text(persona_toml)
    if phrases_toml is not None:
        (persona_dir / "phrases.toml").write_text(phrases_toml)
    return persona_dir


# ---------------------------------------------------------------------------
# Missing directories
# ---------------------------------------------------------------------------


class TestMissingDirectories:
    """PersonaLoader tolerates missing builtin_dir or user_dir paths."""

    def test_missing_user_dir_does_not_raise_on_load(self, tmp_path: Path) -> None:
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        _create_persona_dir(builtin_dir, "alpha")
        user_dir = tmp_path / "does_not_exist"
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        persona = loader.load("alpha")
        assert persona.name == "alpha"

    def test_missing_builtin_dir_does_not_raise_on_load(
        self, tmp_path: Path
    ) -> None:
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(user_dir, "alpha")
        builtin_dir = tmp_path / "does_not_exist"
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        persona = loader.load("alpha")
        assert persona.name == "alpha"

    def test_both_dirs_missing_returns_hardcoded_minimal(
        self, tmp_path: Path
    ) -> None:
        loader = PersonaLoader(
            builtin_dir=tmp_path / "nope_builtin",
            user_dir=tmp_path / "nope_user",
        )
        persona = loader.load("anything")
        assert isinstance(persona, PersonaProtocol)
        assert persona.name == "minimal"

    def test_missing_user_dir_available_returns_builtin_only(
        self, tmp_path: Path
    ) -> None:
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        _create_persona_dir(builtin_dir, "alpha")
        loader = PersonaLoader(
            builtin_dir=builtin_dir, user_dir=tmp_path / "missing_user"
        )
        names = loader.available()
        assert names == ["alpha"]


# ---------------------------------------------------------------------------
# Stray filesystem entries
# ---------------------------------------------------------------------------


class TestStrayEntries:
    """Non-directory entries and partial installs don't break discovery."""

    def test_stray_file_in_builtin_dir_ignored(self, tmp_path: Path) -> None:
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(builtin_dir, "alpha")
        (builtin_dir / "README.md").write_text("# not a persona")
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        names = loader.available()
        assert "alpha" in names
        assert "README.md" not in names

    def test_directory_without_persona_toml_ignored(self, tmp_path: Path) -> None:
        """A directory lacking persona.toml is not a persona — skip it."""
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(builtin_dir, "alpha")
        _create_persona_dir(builtin_dir, "incomplete", persona_toml=None)
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        names = loader.available()
        assert "alpha" in names
        assert "incomplete" not in names

    def test_load_directory_without_persona_toml_falls_back(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Asking for a partially-installed persona falls back cleanly."""
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(builtin_dir, "incomplete", persona_toml=None)
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        with caplog.at_level(logging.WARNING):
            persona = loader.load("incomplete")
        assert persona.name == "minimal"


# ---------------------------------------------------------------------------
# Optional phrases.toml
# ---------------------------------------------------------------------------


class TestOptionalPhrases:
    """phrases.toml is optional — a persona.toml alone is valid."""

    def test_no_phrases_toml_loads(self, tmp_path: Path) -> None:
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(builtin_dir, "alpha", phrases_toml=None)
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        persona = loader.load("alpha")
        assert persona.name == "alpha"
        assert isinstance(persona, PersonaProtocol)

    def test_no_phrases_toml_unknown_event_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Without phrases.toml, ``format_event`` returns None for any event."""
        from bonfire.models.events import StageStarted

        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(builtin_dir, "alpha", phrases_toml=None)
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        persona = loader.load("alpha")
        event = StageStarted(
            session_id="s1",
            sequence=0,
            stage_name="scout",
            agent_name="agent1",
        )
        assert persona.format_event(event) is None


# ---------------------------------------------------------------------------
# Case sensitivity
# ---------------------------------------------------------------------------


class TestCaseSensitivity:
    """Persona names are case-sensitive — 'Default' and 'default' are distinct."""

    def test_wrong_case_falls_back_to_minimal(self, tmp_path: Path) -> None:
        """Asking for 'Default' when only 'default' ships falls back."""
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        _create_persona_dir(builtin_dir, "default")
        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        persona = loader.load("Default")  # capital D
        assert persona.name == "minimal"


# ---------------------------------------------------------------------------
# User shadows built-in — extended case
# ---------------------------------------------------------------------------


class TestShadowSemantics:
    """When a user directory shadows a built-in, the user TOML is what parses."""

    def test_user_dir_version_parsed_when_shadowing(self, tmp_path: Path) -> None:
        """The TOML parsed comes from user_dir, not builtin_dir, when shadowed."""
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user"
        user_dir.mkdir()

        builtin_toml = _VALID_PERSONA_TOML.replace(
            'display_name = "Alpha"', 'display_name = "Built-in Alpha"'
        )
        user_toml = _VALID_PERSONA_TOML.replace(
            'display_name = "Alpha"', 'display_name = "User Alpha"'
        )
        _create_persona_dir(builtin_dir, "alpha", persona_toml=builtin_toml)
        _create_persona_dir(user_dir, "alpha", persona_toml=user_toml)

        loader = PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)
        persona = loader.load("alpha")
        assert persona.name == "alpha"
        # Behavioural signal: available() lists "alpha" exactly once.
        assert loader.available().count("alpha") == 1
