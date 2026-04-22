"""RED tests for persona TOML schema strictness (Sage D1 split policy).

The schema lock
---------------
persona.toml must declare a ``[persona]`` table with four required
fields — ALL strings, ALL non-empty:

    name         — str, persona identity (matches directory name)
    display_name — str, human-friendly label
    description  — str, one-line blurb
    version      — str (not int), semver-ish

persona.toml must also declare a ``[display_names]`` table mapping EVERY
canonical AgentRole value to a non-empty string. Missing any single
role is an invalid persona.

Extras policy (Sage D1 — SPLIT)
-------------------------------
Top-level unknown tables (``[metadata]``, ``[notes]``, ``[author]``,
etc.): **ACCEPTED WITH WARNING**. User-authored content should not be
bricked by harmless extra tables; the loader logs a warning naming
the table so the operator sees it.

Unknown role keys inside ``[display_names]``: **STRICT REJECT**.
Role keys are a shared wire contract — a typo like ``reasearcher``
would silently drop the translation. ``PersonaSchemaError`` is raised,
naming the bogus key so operators can fix their TOML.

The adversarial test
--------------------
``test_persona_missing_single_role_raises_with_role_name`` parametrises
over every AgentRole value, removing exactly ONE entry from
``[display_names]``. It asserts the error message mentions the missing
role by name. This is the counter-example that proves per-role
coverage is actually enforced (Knight B's crown jewel).
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003 — runtime constructor type

import pytest

from bonfire.agent.roles import AgentRole
from bonfire.persona import PersonaLoader, PersonaSchemaError

# ---------------------------------------------------------------------------
# Helpers — build valid / invalid TOML strings
# ---------------------------------------------------------------------------

_FULL_DISPLAY_NAMES_BLOCK = """\
[display_names]
researcher = "Scout"
tester = "Knight"
implementer = "Warrior"
verifier = "Assayer"
publisher = "Bard"
reviewer = "Wizard"
closer = "Herald"
synthesizer = "Sage"
"""


def _persona_toml(
    *,
    name: str = "testbot",
    display_name: str = "TestBot",
    description: str = "A test persona",
    version: str = "1.0.0",
    include_display_names: bool = True,
    extras_block: str = "",
) -> str:
    """Build a persona.toml content string with optional unknown-table extras."""
    body = (
        f'[persona]\n'
        f'name = "{name}"\n'
        f'display_name = "{display_name}"\n'
        f'description = "{description}"\n'
        f'version = "{version}"\n'
    )
    if include_display_names:
        body += "\n" + _FULL_DISPLAY_NAMES_BLOCK
    if extras_block:
        body += "\n" + extras_block
    return body


def _persona_toml_missing_field(field: str) -> str:
    """Build a persona.toml with exactly ONE required field removed."""
    parts = {
        "name": 'name = "testbot"',
        "display_name": 'display_name = "TestBot"',
        "description": 'description = "A test persona"',
        "version": 'version = "1.0.0"',
    }
    assert field in parts, f"Unknown field to omit: {field}"
    del parts[field]
    body = "[persona]\n" + "\n".join(parts.values()) + "\n"
    body += "\n" + _FULL_DISPLAY_NAMES_BLOCK
    return body


def _persona_toml_missing_role(missing: AgentRole) -> str:
    """Build a persona.toml with display_names missing exactly ONE role."""
    mapping = {
        AgentRole.RESEARCHER: "Scout",
        AgentRole.TESTER: "Knight",
        AgentRole.IMPLEMENTER: "Warrior",
        AgentRole.VERIFIER: "Assayer",
        AgentRole.PUBLISHER: "Bard",
        AgentRole.REVIEWER: "Wizard",
        AgentRole.CLOSER: "Herald",
        AgentRole.SYNTHESIZER: "Sage",
    }
    assert missing in mapping
    del mapping[missing]
    block = (
        "[display_names]\n"
        + "\n".join(f'{role.value} = "{name}"' for role, name in mapping.items())
        + "\n"
    )
    return _persona_toml(include_display_names=False) + "\n" + block


_MINIMAL_PHRASES_TOML = """\
[stage.completed]
phrases = ["{stage_name} done"]
"""


def _create_persona_dir(
    base: Path,
    name: str,
    *,
    persona_toml: str,
    phrases_toml: str = _MINIMAL_PHRASES_TOML,
) -> Path:
    """Create a persona directory with the supplied TOML content."""
    persona_dir = base / name
    persona_dir.mkdir(parents=True, exist_ok=True)
    (persona_dir / "persona.toml").write_text(persona_toml)
    (persona_dir / "phrases.toml").write_text(phrases_toml)
    return persona_dir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def builtin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "builtin"
    d.mkdir()
    return d


@pytest.fixture()
def user_dir(tmp_path: Path) -> Path:
    d = tmp_path / "user"
    d.mkdir()
    return d


@pytest.fixture()
def loader(builtin_dir: Path, user_dir: Path) -> PersonaLoader:
    return PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)


# ---------------------------------------------------------------------------
# PersonaSchemaError — dedicated exception class
# ---------------------------------------------------------------------------


class TestPersonaSchemaError:
    """A dedicated exception class distinguishes schema errors from I/O errors."""

    def test_is_importable(self) -> None:
        assert PersonaSchemaError is not None

    def test_is_exception_subclass(self) -> None:
        assert issubclass(PersonaSchemaError, Exception)

    def test_is_value_error_subclass(self) -> None:
        """PersonaSchemaError inherits from ValueError — it's a data-shape error."""
        assert issubclass(PersonaSchemaError, ValueError)


# ---------------------------------------------------------------------------
# Required fields — name, display_name, description, version
# ---------------------------------------------------------------------------


class TestRequiredFields:
    """persona.toml [persona] table must contain all four required fields."""

    @pytest.mark.parametrize(
        "field",
        ["name", "display_name", "description", "version"],
    )
    def test_missing_required_field_raises(
        self,
        loader: PersonaLoader,
        builtin_dir: Path,
        field: str,
    ) -> None:
        """Missing any required field raises PersonaSchemaError naming the field."""
        toml_str = _persona_toml_missing_field(field)
        _create_persona_dir(builtin_dir, "broken", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("broken")
        assert field in str(exc.value), (
            f"Error must name the missing field '{field}': got {exc.value!r}"
        )

    def test_missing_persona_table_raises(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """persona.toml with no [persona] table at all is invalid."""
        _create_persona_dir(
            builtin_dir, "nopersona", persona_toml="[other]\nkey = 'x'\n"
        )
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("nopersona")
        assert "persona" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Field types — strings only for required fields
# ---------------------------------------------------------------------------


class TestFieldTypes:
    """All four required fields are strings. Ints, bools, arrays are rejected."""

    def test_version_int_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Numeric ``version = 1`` is rejected — semver is a string."""
        toml_str = (
            '[persona]\n'
            'name = "intver"\n'
            'display_name = "IntVer"\n'
            'description = "bad"\n'
            'version = 1\n'
            "\n" + _FULL_DISPLAY_NAMES_BLOCK
        )
        _create_persona_dir(builtin_dir, "intver", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("intver")
        assert "version" in str(exc.value).lower()

    def test_name_non_string_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        toml_str = (
            '[persona]\n'
            "name = 42\n"
            'display_name = "X"\n'
            'description = "bad"\n'
            'version = "1.0.0"\n'
            "\n" + _FULL_DISPLAY_NAMES_BLOCK
        )
        _create_persona_dir(builtin_dir, "intname", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("intname")
        assert "name" in str(exc.value).lower()

    def test_description_non_string_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        toml_str = (
            '[persona]\n'
            'name = "ok"\n'
            'display_name = "X"\n'
            "description = true\n"
            'version = "1.0.0"\n'
            "\n" + _FULL_DISPLAY_NAMES_BLOCK
        )
        _create_persona_dir(builtin_dir, "boolname", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("boolname")
        assert "description" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Empty-value rejection
# ---------------------------------------------------------------------------


class TestEmptyValues:
    """Empty strings for required fields are rejected — intent must be explicit."""

    @pytest.mark.parametrize(
        "field",
        ["name", "display_name", "description", "version"],
    )
    def test_empty_string_rejected(
        self, loader: PersonaLoader, builtin_dir: Path, field: str
    ) -> None:
        values = {
            "name": "testbot",
            "display_name": "TestBot",
            "description": "desc",
            "version": "1.0.0",
        }
        values[field] = ""
        toml_str = (
            '[persona]\n'
            f'name = "{values["name"]}"\n'
            f'display_name = "{values["display_name"]}"\n'
            f'description = "{values["description"]}"\n'
            f'version = "{values["version"]}"\n'
            "\n" + _FULL_DISPLAY_NAMES_BLOCK
        )
        _create_persona_dir(builtin_dir, "empty", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("empty")
        assert field in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Display-names coverage — the adversarial per-role test (Knight B's jewel)
# ---------------------------------------------------------------------------


class TestDisplayNamesCoverage:
    """[display_names] must map every AgentRole value to a non-empty string."""

    def test_valid_full_coverage_passes(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Sanity: a TOML with complete coverage validates without raising."""
        _create_persona_dir(builtin_dir, "valid", persona_toml=_persona_toml())
        loader.validate("valid")  # must not raise

    @pytest.mark.parametrize("missing_role", list(AgentRole), ids=lambda r: r.value)
    def test_persona_missing_single_role_raises_with_role_name(
        self,
        loader: PersonaLoader,
        builtin_dir: Path,
        missing_role: AgentRole,
    ) -> None:
        """ADVERSARIAL: remove exactly ONE role from display_names.

        Counter-example that proves per-role coverage is enforced, not
        hand-waved. If the validator only checks that ``[display_names]``
        is present (not that every role is populated), this falls.

        The error message MUST name the missing role so operators can
        fix their TOML without guessing.
        """
        toml_str = _persona_toml_missing_role(missing_role)
        _create_persona_dir(builtin_dir, "onemissing", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("onemissing")
        assert missing_role.value in str(exc.value), (
            f"Error must mention missing role '{missing_role.value}': "
            f"got {exc.value!r}"
        )

    def test_empty_display_names_table_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """``[display_names]`` present but empty is invalid."""
        toml_str = (
            _persona_toml(include_display_names=False) + "\n[display_names]\n"
        )
        _create_persona_dir(builtin_dir, "emptymap", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("emptymap")
        msg = str(exc.value).lower()
        assert "display_names" in msg or "role" in msg

    def test_missing_display_names_table_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """No ``[display_names]`` table at all is invalid."""
        toml_str = _persona_toml(include_display_names=False)
        _create_persona_dir(builtin_dir, "nomap", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("nomap")
        assert "display_names" in str(exc.value)

    def test_unknown_role_in_display_names_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Extra (unknown) role keys in [display_names] are STRICTLY rejected.

        Sage D1 enforcement: the top-level extras policy is lenient, but
        role keys must match AgentRole exactly. A typo like
        ``reasearcher`` would silently miss if tolerated.
        """
        toml_str = _persona_toml().replace(
            _FULL_DISPLAY_NAMES_BLOCK,
            _FULL_DISPLAY_NAMES_BLOCK + 'bogus_role = "Clown"\n',
        )
        _create_persona_dir(builtin_dir, "bogusrole", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("bogusrole")
        assert "bogus_role" in str(exc.value)

    def test_display_name_value_non_string_rejected(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Role values in [display_names] must be strings."""
        toml_str = _persona_toml(include_display_names=False) + (
            '\n[display_names]\n'
            'researcher = 42\n'
            'tester = "Knight"\n'
            'implementer = "Warrior"\n'
            'verifier = "Assayer"\n'
            'publisher = "Bard"\n'
            'reviewer = "Wizard"\n'
            'closer = "Herald"\n'
            'synthesizer = "Sage"\n'
        )
        _create_persona_dir(builtin_dir, "intval", persona_toml=toml_str)
        with pytest.raises(PersonaSchemaError) as exc:
            loader.validate("intval")
        assert "researcher" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Extras policy — top-level unknown tables (Sage D1: warn + continue)
# ---------------------------------------------------------------------------


class TestExtrasPolicy:
    """Unknown top-level tables in persona.toml: accepted with warning (D1).

    Rationale: user-authored content; strict rejection is too brittle.
    The loader MUST log a warning naming the unknown table so it is
    visible, but validation must succeed.
    """

    def test_unknown_toplevel_table_accepted(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """An extra top-level table does not fail validation."""
        toml_str = _persona_toml(extras_block='[metadata]\nauthor = "Anta"\n')
        _create_persona_dir(builtin_dir, "extras", persona_toml=toml_str)
        loader.validate("extras")  # must not raise

    def test_unknown_toplevel_table_logs_warning(
        self,
        loader: PersonaLoader,
        builtin_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The unknown table name appears in a WARNING log record."""
        toml_str = _persona_toml(extras_block='[metadata]\nauthor = "Anta"\n')
        _create_persona_dir(builtin_dir, "extras", persona_toml=toml_str)
        with caplog.at_level(logging.WARNING):
            loader.validate("extras")
        assert any("metadata" in r.message for r in caplog.records), (
            "Expected warning naming the unknown table"
        )

    def test_multiple_unknown_toplevel_tables_accepted(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Multiple extra top-level tables all pass validation."""
        toml_str = _persona_toml(
            extras_block=(
                '[metadata]\nauthor = "Anta"\n'
                '\n[notes]\ncomment = "ok"\n'
            )
        )
        _create_persona_dir(builtin_dir, "extras2", persona_toml=toml_str)
        loader.validate("extras2")


# ---------------------------------------------------------------------------
# Version field — documentary assertions
# ---------------------------------------------------------------------------


class TestVersionField:
    """Version field must be a non-empty string. Semver is recommended."""

    def test_version_must_be_string(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Positive: semver strings validate."""
        toml_str = _persona_toml(version="2.1.0")
        _create_persona_dir(builtin_dir, "v21", persona_toml=toml_str)
        loader.validate("v21")

    def test_version_any_string_accepted(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Any non-empty version string passes — shape validation is advisory."""
        toml_str = _persona_toml(version="calver-2026.04")
        _create_persona_dir(builtin_dir, "calver", persona_toml=toml_str)
        loader.validate("calver")
