"""RED tests for bonfire.persona.loader — discovery + total-fallback contract.

Scope of this file
------------------
1. ``PersonaLoader.load(name)`` returns a PersonaProtocol for known personas.
2. ``PersonaLoader.load()`` with no argument returns the ``"default"`` persona
   (Sage D3 — ergonomic contract).
3. Two-tier discovery — user_dir > builtin_dir.
4. Malformed TOML logs a warning and falls back to minimal; never raises.
5. Minimal safety net (Sage D5):
     a. ``builtins/minimal/`` ships and is discoverable via ``available()``.
     b. When ``default`` is missing OR malformed AND ``minimal/`` is missing
        OR malformed, ``load()`` returns a hardcoded
        ``BasePersona(name="minimal", phrases={})``.
6. ``available()`` returns a deduplicated, sorted list.

Schema strictness (required fields, per-role coverage, extras policy)
lives in ``test_persona_toml_schema.py``. Built-in-specific shape
checks (falcor/default/minimal) live in ``test_persona_defaults.py``
and ``test_persona_builtin.py``.

Tests use ``tmp_path`` fixtures — no real ``~/.bonfire/`` is touched.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003 — runtime constructor type

import pytest

from bonfire.persona import (
    BasePersona,
    PersonaLoader,
    PersonaProtocol,
)

# ---------------------------------------------------------------------------
# Helpers — build TOML strings and create persona directories
# ---------------------------------------------------------------------------

_VALID_PERSONA_TOML = """\
[persona]
name = "testbot"
display_name = "TestBot"
description = "A test persona"
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
[stage.started]
phrases = [
    "The {stage_name} begins",
    "{stage_name} is starting up",
]

[stage.completed]
phrases = [
    "{stage_name} finished",
    "Done with {stage_name}",
]
"""

_MALFORMED_TOML = """\
[persona
name = "broken
"""


def _make_persona_toml(name: str, display_name: str = "X") -> str:
    """Schema-valid persona.toml with full AgentRole coverage for *name*."""
    return (
        f"[persona]\n"
        f'name = "{name}"\n'
        f'display_name = "{display_name}"\n'
        f'description = "desc"\n'
        f'version = "1.0.0"\n'
        f"\n"
        f"[display_names]\n"
        f'researcher = "Research Agent"\n'
        f'tester = "Test Agent"\n'
        f'implementer = "Build Agent"\n'
        f'verifier = "Verify Agent"\n'
        f'publisher = "Publish Agent"\n'
        f'reviewer = "Review Agent"\n'
        f'closer = "Release Agent"\n'
        f'synthesizer = "Synthesis Agent"\n'
    )


def _create_persona_dir(
    base: Path,
    name: str,
    *,
    persona_toml: str = _VALID_PERSONA_TOML,
    phrases_toml: str = _VALID_PHRASES_TOML,
) -> Path:
    """Create a persona directory with persona.toml and phrases.toml."""
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
# load() — happy path
# ---------------------------------------------------------------------------


class TestPersonaLoaderLoad:
    """PersonaLoader.load() discovers and returns PersonaProtocol instances."""

    def test_load_returns_persona_protocol(self, loader: PersonaLoader, builtin_dir: Path) -> None:
        """``load(name)`` returns a PersonaProtocol instance when the persona exists."""
        _create_persona_dir(builtin_dir, "testbot")
        persona = loader.load("testbot")
        assert isinstance(persona, PersonaProtocol)

    def test_load_returns_base_persona_instance(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """The concrete return type is ``BasePersona`` — the default impl."""
        _create_persona_dir(builtin_dir, "testbot")
        persona = loader.load("testbot")
        assert isinstance(persona, BasePersona)

    def test_load_nonexistent_falls_back_to_minimal(self, loader: PersonaLoader) -> None:
        """Unknown name falls back to the minimal persona (name == 'minimal')."""
        persona = loader.load("nonexistent_persona")
        assert isinstance(persona, PersonaProtocol)
        assert persona.name == "minimal"

    def test_load_nonexistent_logs_warning(
        self, loader: PersonaLoader, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``load()`` emits a warning when falling back to the safety net."""
        with caplog.at_level(logging.WARNING):
            loader.load("nonexistent_persona")
        assert any("nonexistent_persona" in r.message for r in caplog.records)

    def test_malformed_toml_falls_back_to_minimal(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Malformed persona.toml does not crash; falls back to minimal."""
        _create_persona_dir(builtin_dir, "broken", persona_toml=_MALFORMED_TOML)
        persona = loader.load("broken")
        assert isinstance(persona, PersonaProtocol)
        assert persona.name == "minimal"

    def test_malformed_toml_does_not_raise(self, loader: PersonaLoader, builtin_dir: Path) -> None:
        """Malformed TOML must not propagate exceptions."""
        _create_persona_dir(builtin_dir, "broken", persona_toml=_MALFORMED_TOML)
        loader.load("broken")  # must not raise


# ---------------------------------------------------------------------------
# load() — no-arg ergonomic contract (Sage D3)
# ---------------------------------------------------------------------------


class TestPersonaLoaderLoadNoArg:
    """``PersonaLoader.load()`` (no argument) returns the ``"default"`` persona."""

    def test_load_no_argument_returns_default(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """``load()`` with no argument resolves to the persona named ``default``."""
        _create_persona_dir(
            builtin_dir,
            "default",
            persona_toml=_make_persona_toml("default", "Default"),
        )
        persona = loader.load()
        assert persona.name == "default"

    def test_load_default_name_returns_default_persona(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """``load("default")`` returns the default persona, not the safety net."""
        _create_persona_dir(
            builtin_dir,
            "default",
            persona_toml=_make_persona_toml("default", "Default"),
        )
        persona = loader.load("default")
        assert persona.name == "default"

    def test_falcor_is_not_the_default_name(self, loader: PersonaLoader, builtin_dir: Path) -> None:
        """``load()`` with no argument MUST NOT return a persona named 'falcor'."""
        _create_persona_dir(
            builtin_dir,
            "default",
            persona_toml=_make_persona_toml("default", "Default"),
        )
        _create_persona_dir(
            builtin_dir,
            "falcor",
            persona_toml=_make_persona_toml("falcor", "Falcor"),
        )
        persona = loader.load()
        assert persona.name != "falcor"
        assert persona.name == "default"


# ---------------------------------------------------------------------------
# Two-tier discovery — user_dir > builtin_dir
# ---------------------------------------------------------------------------


class TestDiscoveryPrecedence:
    """User-installed personas shadow built-ins with the same name."""

    def test_user_dir_takes_priority_over_builtin(
        self, loader: PersonaLoader, builtin_dir: Path, user_dir: Path
    ) -> None:
        """User-installed persona overrides built-in with the same name."""
        _create_persona_dir(
            builtin_dir,
            "custom",
            persona_toml=_make_persona_toml("custom", "Built-in Custom"),
        )
        _create_persona_dir(
            user_dir,
            "custom",
            persona_toml=_make_persona_toml("custom", "User Custom"),
        )
        persona = loader.load("custom")
        assert persona.name == "custom"

    def test_user_only_persona_loads(self, loader: PersonaLoader, user_dir: Path) -> None:
        """A persona installed only in user_dir is discoverable."""
        _create_persona_dir(user_dir, "myuser")
        persona = loader.load("myuser")
        assert persona.name == "myuser"

    def test_builtin_only_persona_loads(self, loader: PersonaLoader, builtin_dir: Path) -> None:
        """A persona shipped only in builtin_dir is discoverable."""
        _create_persona_dir(builtin_dir, "shipped")
        persona = loader.load("shipped")
        assert persona.name == "shipped"


# ---------------------------------------------------------------------------
# Minimal safety-net — load()-is-total contract (Sage D5)
# ---------------------------------------------------------------------------


class TestMinimalSafetyNet:
    """If every candidate fails, ``load()`` returns a hardcoded minimal persona.

    No name, no filesystem state, and no malformed TOML may cause ``load()``
    to raise. This is the load()-is-total contract.
    """

    def test_default_missing_falls_back_to_minimal_in_builtin(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """``default`` missing → loader returns the ``minimal`` built-in if present."""
        _create_persona_dir(
            builtin_dir,
            "minimal",
            persona_toml=_make_persona_toml("minimal", "Minimal"),
        )
        persona = loader.load("default")
        assert isinstance(persona, PersonaProtocol)
        assert persona.name == "minimal"

    def test_default_missing_and_minimal_missing_returns_hardcoded(
        self, loader: PersonaLoader
    ) -> None:
        """Neither persona on disk — hardcoded minimal BasePersona is returned."""
        persona = loader.load("default")
        assert isinstance(persona, BasePersona)
        assert persona.name == "minimal"

    def test_default_malformed_and_minimal_missing_returns_hardcoded(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Malformed ``default`` + no ``minimal`` → hardcoded minimal."""
        _create_persona_dir(builtin_dir, "default", persona_toml=_MALFORMED_TOML)
        persona = loader.load("default")
        assert isinstance(persona, BasePersona)
        assert persona.name == "minimal"

    def test_default_malformed_and_minimal_malformed_returns_hardcoded(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """Malformed ``default`` AND malformed ``minimal`` → hardcoded minimal."""
        _create_persona_dir(builtin_dir, "default", persona_toml=_MALFORMED_TOML)
        _create_persona_dir(builtin_dir, "minimal", persona_toml=_MALFORMED_TOML)
        persona = loader.load("default")
        assert isinstance(persona, BasePersona)
        assert persona.name == "minimal"

    def test_minimal_hardcoded_has_empty_phrases(self, loader: PersonaLoader) -> None:
        """Hardcoded fallback is ``BasePersona(name='minimal', phrases={})``."""
        from bonfire.models.events import StageCompleted

        persona = loader.load("does_not_exist")
        assert persona.name == "minimal"
        event = StageCompleted(
            session_id="s1",
            sequence=0,
            stage_name="scout",
            agent_name="agent1",
            duration_seconds=1.0,
            cost_usd=0.0,
        )
        # Any event formatted against empty phrases returns None.
        assert persona.format_event(event) is None

    def test_minimal_safety_net_logs_warning(
        self, loader: PersonaLoader, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Falling back to the hardcoded minimal emits a warning."""
        with caplog.at_level(logging.WARNING):
            loader.load("default")
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "Expected at least one warning when falling back to minimal"

    def test_minimal_safety_net_never_raises(self, loader: PersonaLoader) -> None:
        """Total function: any name, any filesystem state, never raises."""
        for name in ("default", "minimal", "", "../../etc/passwd", "unicode-名前"):
            persona = loader.load(name)
            assert isinstance(persona, PersonaProtocol)

    def test_safety_net_satisfies_protocol(self, loader: PersonaLoader) -> None:
        """The safety-net fallback persona also satisfies PersonaProtocol."""
        persona = loader.load("does_not_exist")
        assert isinstance(persona, PersonaProtocol)


# ---------------------------------------------------------------------------
# available()
# ---------------------------------------------------------------------------


class TestPersonaLoaderAvailable:
    """``available()`` returns a deduplicated, sorted list."""

    def test_available_returns_list(self, loader: PersonaLoader) -> None:
        assert isinstance(loader.available(), list)

    def test_available_empty_dirs(self, loader: PersonaLoader) -> None:
        assert loader.available() == []

    def test_available_includes_builtin(self, loader: PersonaLoader, builtin_dir: Path) -> None:
        _create_persona_dir(builtin_dir, "alpha")
        _create_persona_dir(builtin_dir, "beta")
        names = loader.available()
        assert "alpha" in names
        assert "beta" in names

    def test_available_includes_user(self, loader: PersonaLoader, user_dir: Path) -> None:
        _create_persona_dir(user_dir, "mypersona")
        assert "mypersona" in loader.available()

    def test_available_deduplicates(
        self, loader: PersonaLoader, builtin_dir: Path, user_dir: Path
    ) -> None:
        """Same name in both dirs appears only once in ``available()``."""
        _create_persona_dir(builtin_dir, "shared")
        _create_persona_dir(user_dir, "shared")
        names = loader.available()
        assert names.count("shared") == 1

    def test_available_is_sorted(
        self, loader: PersonaLoader, builtin_dir: Path, user_dir: Path
    ) -> None:
        """``available()`` is sorted — deterministic for CLI output."""
        _create_persona_dir(user_dir, "zeta")
        _create_persona_dir(builtin_dir, "alpha")
        _create_persona_dir(builtin_dir, "mu")
        names = loader.available()
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Integration — loaded personas satisfy the protocol and format events
# ---------------------------------------------------------------------------


class TestPersonaLoaderIntegration:
    """Loaded personas satisfy PersonaProtocol and format events correctly."""

    def test_loaded_persona_satisfies_protocol(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        _create_persona_dir(builtin_dir, "testbot")
        persona = loader.load("testbot")
        assert isinstance(persona, PersonaProtocol)

    def test_loaded_persona_formats_known_event(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """A loaded persona formats known events from its phrase bank."""
        from bonfire.models.events import StageCompleted

        _create_persona_dir(builtin_dir, "testbot")
        persona = loader.load("testbot")
        event = StageCompleted(
            session_id="s1",
            sequence=0,
            stage_name="scout",
            agent_name="agent1",
            duration_seconds=1.5,
            cost_usd=0.01,
        )
        result = persona.format_event(event)
        assert result is not None
        assert isinstance(result, str)

    def test_loaded_persona_returns_none_for_unknown_event(
        self, loader: PersonaLoader, builtin_dir: Path
    ) -> None:
        """A loaded persona returns None for events not in its phrase bank."""
        from bonfire.models.events import StageStarted

        phrases_toml = """\
[stage.completed]
phrases = ["{stage_name} done"]
"""
        _create_persona_dir(builtin_dir, "limited", phrases_toml=phrases_toml)
        persona = loader.load("limited")
        event = StageStarted(
            session_id="s1",
            sequence=0,
            stage_name="scout",
            agent_name="agent1",
        )
        assert persona.format_event(event) is None

    def test_loaded_persona_format_summary(self, loader: PersonaLoader, builtin_dir: Path) -> None:
        _create_persona_dir(builtin_dir, "testbot")
        persona = loader.load("testbot")
        result = persona.format_summary({"stages": 3, "cost": 0.42})
        assert result is not None


# ---------------------------------------------------------------------------
# Hookspec deferral — locks absence of plugin machinery
# ---------------------------------------------------------------------------


class TestHookspecDeferred:
    """Hookspec is deferred for v0.1.

    Locks the absence of hookspec machinery: no PersonaHookSpec export,
    no pluggy import anywhere under bonfire.persona.
    """

    def test_persona_module_does_not_export_hookspec(self) -> None:
        """``bonfire.persona`` MUST NOT export ``PersonaHookSpec`` in v0.1."""
        import bonfire.persona as persona_pkg

        assert not hasattr(persona_pkg, "PersonaHookSpec"), (
            "PersonaHookSpec is deferred for v0.1 — no hookspec export allowed."
        )

    def test_persona_module_does_not_import_pluggy(self) -> None:
        """No ``pluggy`` import from any module under ``bonfire.persona``."""
        import sys

        import bonfire.persona  # noqa: F401 — ensure package is loaded

        persona_modules = [name for name in sys.modules if name.startswith("bonfire.persona")]
        for mod_name in persona_modules:
            mod = sys.modules[mod_name]
            src_file = getattr(mod, "__file__", None)
            if src_file is None:
                continue
            try:
                with open(src_file, encoding="utf-8") as f:
                    source = f.read()
            except OSError:
                continue
            assert "import pluggy" not in source, (
                f"{mod_name} imports pluggy — hookspec is deferred."
            )
            assert "from pluggy" not in source, (
                f"{mod_name} imports from pluggy — hookspec is deferred."
            )
