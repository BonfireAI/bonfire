"""RED tests for the built-in ``default``, ``minimal``, and ``passelewe`` personas.

Pins the rename split:

  * ``default`` — the implicit persona returned by ``PersonaLoader.load()``
    with no argument. Professional/neutral tone. Uses
    ``ROLE_DISPLAY[role].professional`` values in [display_names].
  * ``minimal`` — safety net + discoverable built-in (Sage D5).
    Structural output only. Exactly one phrase per event type. No
    personality markers.
  * ``passelewe`` — optional example persona. Chamberlain voice.
    Must ship an explanatory one-liner (description field or leading
    comment). Not the default — ``load()`` with no argument must never
    return a persona named ``passelewe``.

All three must satisfy PersonaProtocol and ship a complete
``[display_names]`` map covering every AgentRole value.

Passelewe distinctness (Sage D6)
--------------------------------
The distinctness test compares raw phrase banks by reading each
persona's phrases.toml directly. No RNG sampling. The symmetric
difference of the two phrase sets must be non-empty, proving passelewe
is not an alias of default.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from bonfire.agent.roles import AgentRole
from bonfire.persona import PersonaLoader, PersonaProtocol

# ---------------------------------------------------------------------------
# Real-dir fixtures — point the loader at the shipped built-ins
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILTIN_DIR = _REPO_ROOT / "src" / "bonfire" / "persona" / "builtins"
_FAKE_USER_DIR = _REPO_ROOT / "tests" / "unit" / "_nonexistent_user_personas"

_CANONICAL_ROLES = {r.value for r in AgentRole}


@pytest.fixture()
def loader() -> PersonaLoader:
    """PersonaLoader pointed at the shipped built-ins."""
    return PersonaLoader(builtin_dir=_BUILTIN_DIR, user_dir=_FAKE_USER_DIR)


# ---------------------------------------------------------------------------
# "default" — the implicit loader default
# ---------------------------------------------------------------------------


class TestDefaultPersona:
    """The ``default`` built-in replaces ``passelewe`` as the loader default."""

    def test_default_ships_as_builtin(self, loader: PersonaLoader) -> None:
        """``default`` appears in available()."""
        assert "default" in loader.available()

    def test_default_loads(self, loader: PersonaLoader) -> None:
        persona = loader.load("default")
        assert persona is not None
        assert persona.name == "default"

    def test_default_satisfies_protocol(self, loader: PersonaLoader) -> None:
        persona = loader.load("default")
        assert isinstance(persona, PersonaProtocol)

    def test_load_with_no_argument_returns_default(self, loader: PersonaLoader) -> None:
        """``load()`` with no argument returns the persona named ``default``."""
        persona = loader.load()
        assert persona.name == "default"

    def test_default_is_not_passelewe(self, loader: PersonaLoader) -> None:
        """``default`` and ``passelewe`` are distinct personas — no aliasing."""
        persona = loader.load()
        assert persona.name != "passelewe"

    def test_default_toml_has_full_display_names(self) -> None:
        """default/persona.toml [display_names] covers all 8 AgentRole values."""
        toml_path = _BUILTIN_DIR / "default" / "persona.toml"
        assert toml_path.is_file(), f"{toml_path} must exist"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        display_names = data.get("display_names", {})
        missing = _CANONICAL_ROLES - set(display_names.keys())
        assert not missing, (
            f"default/persona.toml [display_names] missing roles: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# "minimal" — safety net + discoverable (Sage D5)
# ---------------------------------------------------------------------------


class TestMinimalPersona:
    """The ``minimal`` persona ships as a discoverable built-in AND is the fallback."""

    def test_minimal_ships_as_builtin(self, loader: PersonaLoader) -> None:
        """``minimal`` appears in available() — it's discoverable, not hidden."""
        assert "minimal" in loader.available()

    def test_minimal_loads(self, loader: PersonaLoader) -> None:
        persona = loader.load("minimal")
        assert persona is not None
        assert persona.name == "minimal"

    def test_minimal_satisfies_protocol(self, loader: PersonaLoader) -> None:
        persona = loader.load("minimal")
        assert isinstance(persona, PersonaProtocol)

    def test_minimal_toml_has_full_display_names(self) -> None:
        """minimal/persona.toml [display_names] covers all 8 AgentRole values."""
        toml_path = _BUILTIN_DIR / "minimal" / "persona.toml"
        assert toml_path.is_file(), f"{toml_path} must exist"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        display_names = data.get("display_names", {})
        missing = _CANONICAL_ROLES - set(display_names.keys())
        assert not missing, (
            f"minimal/persona.toml [display_names] missing roles: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# "passelewe" — optional example, never the default
# ---------------------------------------------------------------------------


class TestPasseleweAsOptionalExample:
    """``passelewe`` is an optional example persona, not the default."""

    def test_passelewe_ships_as_builtin(self, loader: PersonaLoader) -> None:
        """``passelewe`` is discoverable via available()."""
        assert "passelewe" in loader.available()

    def test_passelewe_loads(self, loader: PersonaLoader) -> None:
        persona = loader.load("passelewe")
        assert persona is not None
        assert persona.name == "passelewe"

    def test_passelewe_satisfies_protocol(self, loader: PersonaLoader) -> None:
        persona = loader.load("passelewe")
        assert isinstance(persona, PersonaProtocol)

    def test_passelewe_distinct_from_default(self, loader: PersonaLoader) -> None:
        """``default`` and ``passelewe`` are distinct objects with distinct names."""
        default_persona = loader.load("default")
        passelewe_persona = loader.load("passelewe")
        assert default_persona.name == "default"
        assert passelewe_persona.name == "passelewe"
        assert default_persona.name != passelewe_persona.name

    def test_passelewe_phrase_bank_differs_from_default(self) -> None:
        """Passelewe's phrase bank differs from default's — distinct voices (Sage D6).

        Deterministic set-comparison. Reads each persona's phrases.toml
        directly and asserts the symmetric difference is non-empty —
        passelewe must carry phrases default does not, or vice versa.
        Proves passelewe is not an alias of default, without depending
        on the anti-repeat algorithm or RNG.
        """

        def _collect_phrases(persona_name: str) -> set[str]:
            """Read persona phrases.toml and collect every phrase string."""
            phrases_path = _BUILTIN_DIR / persona_name / "phrases.toml"
            assert phrases_path.is_file(), f"{phrases_path} must exist"
            with phrases_path.open("rb") as f:
                raw = tomllib.load(f)
            collected: set[str] = set()
            # phrases.toml has nested shape: [stage.started] -> phrases = [...]
            # We flatten any list[str] value found anywhere in the tree.
            def _walk(node: object) -> None:
                if isinstance(node, dict):
                    for v in node.values():
                        _walk(v)
                elif isinstance(node, list):
                    for item in node:
                        if isinstance(item, str):
                            collected.add(item)
            _walk(raw)
            return collected

        default_phrases = _collect_phrases("default")
        passelewe_phrases = _collect_phrases("passelewe")

        assert default_phrases, "default persona must ship non-empty phrases"
        assert passelewe_phrases, "passelewe persona must ship non-empty phrases"

        symmetric_diff = default_phrases ^ passelewe_phrases
        assert symmetric_diff, (
            "default and passelewe phrase banks are identical — "
            "passelewe must be a distinct voice, not an alias. "
            f"default has {len(default_phrases)} phrases, "
            f"passelewe has {len(passelewe_phrases)}."
        )

    def test_passelewe_has_explanatory_one_liner(self) -> None:
        """passelewe/persona.toml ships an explanatory note.

        Accepts either:
          * A non-empty ``description`` field under [persona].
          * A top-of-file TOML comment on line 1 or 2 (leading ``#``).
        """
        toml_path = _BUILTIN_DIR / "passelewe" / "persona.toml"
        assert toml_path.is_file(), f"{toml_path} must exist"

        raw_text = toml_path.read_text(encoding="utf-8")
        with toml_path.open("rb") as f:
            data = tomllib.load(f)

        persona_meta = data.get("persona", {})
        description = persona_meta.get("description", "").strip()

        first_lines = raw_text.splitlines()[:3]
        has_leading_comment = any(
            line.lstrip().startswith("#") and len(line.strip()) > 2
            for line in first_lines
        )

        assert description or has_leading_comment, (
            "passelewe/persona.toml must ship an explanatory one-liner — "
            "either a [persona].description field or a leading # comment. "
            "passelewe is an optional example persona; its reason for "
            "existing must be on the record."
        )

    def test_passelewe_toml_has_full_display_names(self) -> None:
        """passelewe/persona.toml [display_names] covers all 8 AgentRole values."""
        toml_path = _BUILTIN_DIR / "passelewe" / "persona.toml"
        assert toml_path.is_file(), f"{toml_path} must exist"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        display_names = data.get("display_names", {})
        missing = _CANONICAL_ROLES - set(display_names.keys())
        assert not missing, (
            f"passelewe/persona.toml [display_names] missing roles: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Discovery — all three built-ins surface in available()
# ---------------------------------------------------------------------------


class TestBuiltinsDiscovery:
    """``loader.available()`` lists every shipped built-in, sorted."""

    def test_available_lists_all_builtins(self, loader: PersonaLoader) -> None:
        available = loader.available()
        assert "default" in available
        assert "minimal" in available
        assert "passelewe" in available

    def test_available_is_sorted(self, loader: PersonaLoader) -> None:
        """``available()`` is sorted — deterministic CLI output."""
        available = loader.available()
        assert available == sorted(available)
