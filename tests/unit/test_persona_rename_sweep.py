"""RED sweep tests — lock in the rename discipline across src/ (Knight A's lens).

Enforces the negative-space contract for BON-345:

  1. ``PhrasePool`` MUST NOT appear anywhere in ``src/bonfire/``
     (class has been renamed to ``PhraseBank``).
  2. ``from bonfire.persona.pool`` / ``import bonfire.persona.pool``
     MUST NOT appear anywhere in ``src/``.
  3. ``pool.py`` MUST NOT exist in ``src/bonfire/persona/`` — the
     replacement module is ``phrase_bank.py``.
  4. ``"passelewe"`` string literal MUST NOT appear in ``src/bonfire/``
     Python sources. Allowed only inside the persona's own TOML under
     ``builtins/passelewe/``.
  5. ``Config.persona`` default MUST be ``"default"`` (Sage D4 — the
     rename extends to ``src/bonfire/models/config.py:46``).
  6. Every built-in persona TOML in ``src/bonfire/persona/builtins/``
     must include a ``[display_names]`` map covering ALL 8 AgentRole
     values, with no extra keys.
  7. ``hookspec.py`` / ``PersonaHookSpec`` / the stale hookspec comment
     MUST NOT appear — hookspec is deferred for v0.1.

These tests read files on disk rather than shelling out; no subprocess.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"
_PERSONA_DIR = _SRC_DIR / "persona"
_BUILTINS_DIR = _PERSONA_DIR / "builtins"
_CONFIG_PATH = _SRC_DIR / "models" / "config.py"

# The 8 canonical AgentRole values — mirrors bonfire.agent.roles.AgentRole.
_CANONICAL_ROLES = frozenset(
    {
        "researcher",
        "tester",
        "implementer",
        "verifier",
        "publisher",
        "reviewer",
        "closer",
        "synthesizer",
    }
)


def _iter_python_files(root: Path) -> list[Path]:
    """Return all .py files under *root*, excluding __pycache__."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _builtin_personas() -> list[Path]:
    """Return all built-in persona directories containing persona.toml."""
    if not _BUILTINS_DIR.is_dir():
        return []
    return [
        child
        for child in _BUILTINS_DIR.iterdir()
        if child.is_dir() and (child / "persona.toml").is_file()
    ]


# ---------------------------------------------------------------------------
# AgentRole cross-check — guard against upstream rename of the 8 roles
# ---------------------------------------------------------------------------


def test_canonical_roles_match_agent_role_enum() -> None:
    """Our frozenset of 8 roles must match ``bonfire.agent.roles.AgentRole``.

    If AgentRole evolves, this fires first so we know the TOML
    assertions below are checking the right vocabulary.
    """
    from bonfire.agent.roles import AgentRole

    enum_values = {r.value for r in AgentRole}
    assert enum_values == _CANONICAL_ROLES, (
        f"AgentRole values {sorted(enum_values)} != canonical "
        f"{sorted(_CANONICAL_ROLES)} — update the sweep test."
    )


# ---------------------------------------------------------------------------
# Stale PhrasePool class name
# ---------------------------------------------------------------------------


class TestPhrasePoolReferencesGone:
    """No surviving references to the old ``PhrasePool`` class name."""

    def test_no_phrase_pool_in_src(self) -> None:
        """The identifier ``PhrasePool`` must not appear in src/bonfire/."""
        offenders: list[tuple[Path, int, str]] = []
        for path in _iter_python_files(_SRC_DIR):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                if "PhrasePool" in line:
                    offenders.append((path, i, line.rstrip()))
        assert not offenders, (
            "Found stale 'PhrasePool' references in src/bonfire/:\n"
            + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
        )

    def test_no_phrase_pool_in_persona_init_exports(self) -> None:
        """``bonfire.persona`` must not re-export ``PhrasePool``."""
        init_path = _PERSONA_DIR / "__init__.py"
        assert init_path.exists(), "src/bonfire/persona/__init__.py must exist"
        text = init_path.read_text(encoding="utf-8")
        assert "PhrasePool" not in text, (
            "bonfire.persona.__init__ re-exports 'PhrasePool' — "
            "must be renamed to PhraseBank."
        )


# ---------------------------------------------------------------------------
# Stale pool.py module
# ---------------------------------------------------------------------------


class TestPoolModuleGone:
    """The ``pool.py`` module has been renamed to ``phrase_bank.py``."""

    def test_pool_py_does_not_exist_in_persona(self) -> None:
        """``src/bonfire/persona/pool.py`` must not exist."""
        stale = _PERSONA_DIR / "pool.py"
        assert not stale.exists(), (
            f"Stale module {stale} still exists — rename to phrase_bank.py."
        )

    def test_no_imports_from_persona_pool_in_src(self) -> None:
        """No ``from bonfire.persona.pool import ...`` anywhere in src/bonfire/."""
        offenders: list[tuple[Path, int, str]] = []
        needle_imports = [
            "from bonfire.persona.pool",
            "import bonfire.persona.pool",
        ]
        for path in _iter_python_files(_SRC_DIR):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                for needle in needle_imports:
                    if needle in line:
                        offenders.append((path, i, line.rstrip()))
                        break
        assert not offenders, (
            "Found stale imports from bonfire.persona.pool:\n"
            + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
        )

    def test_phrase_bank_module_is_the_replacement(self) -> None:
        """The replacement module ``phrase_bank.py`` must exist."""
        replacement = _PERSONA_DIR / "phrase_bank.py"
        assert replacement.exists(), (
            f"Expected replacement module {replacement} — "
            "rename pool.py -> phrase_bank.py must ship."
        )


# ---------------------------------------------------------------------------
# Stale "passelewe"-as-default — ban literal in Python sources
# ---------------------------------------------------------------------------


class TestPasseleweNotDefault:
    """No Python source in ``src/bonfire/`` may hardcode ``"passelewe"``.

    Allowed: the directory name ``builtins/passelewe/``, TOML
    ``name = "passelewe"`` inside that persona's own persona.toml.
    Banned: any Python source under ``src/bonfire/`` that pins
    ``passelewe`` as an implicit default.
    """

    def test_no_passelewe_literal_in_persona_py_sources(self) -> None:
        """No ``"passelewe"`` / ``'passelewe'`` literal in ``src/bonfire/persona/*.py``."""
        offenders: list[tuple[Path, int, str]] = []
        for path in _iter_python_files(_PERSONA_DIR):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                if '"passelewe"' in line or "'passelewe'" in line:
                    offenders.append((path, i, line.rstrip()))
        assert not offenders, (
            "Found 'passelewe' string literal in persona package sources — "
            "the default persona name is 'default':\n"
            + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
        )

    def test_no_passelewe_default_in_src_bonfire(self) -> None:
        """Anywhere in ``src/bonfire/`` — no ``"passelewe"`` Python literal.

        Catches subtle cases: argparse defaults, ``DEFAULT_PERSONA =
        "passelewe"``, Pydantic model ``persona: str = "passelewe"``, etc.
        """
        offenders: list[tuple[Path, int, str]] = []
        banned_patterns = ['"passelewe"', "'passelewe'"]
        for path in _iter_python_files(_SRC_DIR):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                for pat in banned_patterns:
                    if pat in line:
                        offenders.append((path, i, line.rstrip()))
                        break
        assert not offenders, (
            "Found 'passelewe' literal in src/bonfire/:\n"
            + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
        )


# ---------------------------------------------------------------------------
# Config.persona default — Sage D4 enforcement
# ---------------------------------------------------------------------------


class TestConfigPersonaDefault:
    """``Config.persona`` default must be ``"default"``, not ``"passelewe"``."""

    def test_config_py_exists(self) -> None:
        assert _CONFIG_PATH.is_file(), f"Expected config module at {_CONFIG_PATH}"

    def test_config_persona_default_is_default(self) -> None:
        """``src/bonfire/models/config.py`` sets ``persona: str = "default"``.

        Sage D4 — the rename extends to the model default. The model
        file must contain the literal ``persona: str = "default"`` line.
        """
        text = _CONFIG_PATH.read_text(encoding="utf-8")
        assert 'persona: str = "default"' in text, (
            "Config.persona default must be 'default' (Sage D4). "
            "Expected literal line 'persona: str = \"default\"' in "
            f"{_CONFIG_PATH}."
        )

    def test_config_persona_default_is_not_passelewe(self) -> None:
        """``Config.persona`` default literal must NOT be ``"passelewe"``."""
        text = _CONFIG_PATH.read_text(encoding="utf-8")
        assert 'persona: str = "passelewe"' not in text, (
            "Config.persona must not pin 'passelewe' as the default — "
            "rename to 'default' (Sage D4)."
        )


# ---------------------------------------------------------------------------
# Built-in TOML shape — all 8 roles required, no extras
# ---------------------------------------------------------------------------


class TestBuiltinPersonaTomlShape:
    """Every built-in persona's persona.toml must supply a full display-name map."""

    def test_builtins_dir_exists(self) -> None:
        assert _BUILTINS_DIR.is_dir(), (
            f"Expected builtin personas directory at {_BUILTINS_DIR}"
        )

    def test_at_least_one_builtin_exists(self) -> None:
        personas = _builtin_personas()
        assert personas, (
            "At least one built-in persona must ship in "
            "src/bonfire/persona/builtins/ (expect 'default' at minimum)."
        )

    def test_default_persona_ships(self) -> None:
        """The ``default`` persona must ship as a built-in."""
        default_dir = _BUILTINS_DIR / "default"
        toml_path = default_dir / "persona.toml"
        assert toml_path.is_file(), (
            f"Default persona's persona.toml missing at {toml_path}"
        )

    def test_minimal_persona_ships(self) -> None:
        """The ``minimal`` persona must ship as a built-in (Sage D5)."""
        minimal_dir = _BUILTINS_DIR / "minimal"
        toml_path = minimal_dir / "persona.toml"
        assert toml_path.is_file(), (
            f"Minimal persona's persona.toml missing at {toml_path}"
        )

    @pytest.mark.parametrize("persona_dir", _builtin_personas(), ids=lambda p: p.name)
    def test_each_builtin_has_display_names_section(
        self, persona_dir: Path
    ) -> None:
        """Each persona.toml has a top-level ``[display_names]`` section."""
        toml_path = persona_dir / "persona.toml"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert "display_names" in data, (
            f"{persona_dir.name}/persona.toml has no [display_names] section"
        )
        assert isinstance(data["display_names"], dict), (
            f"{persona_dir.name}/persona.toml: [display_names] must be a table"
        )

    @pytest.mark.parametrize("persona_dir", _builtin_personas(), ids=lambda p: p.name)
    def test_each_builtin_display_names_covers_all_roles(
        self, persona_dir: Path
    ) -> None:
        """[display_names] must contain an entry for every AgentRole value."""
        toml_path = persona_dir / "persona.toml"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        display_names = data.get("display_names", {})
        keys = set(display_names.keys())
        missing = _CANONICAL_ROLES - keys
        assert not missing, (
            f"{persona_dir.name}/persona.toml [display_names] is missing roles: "
            f"{sorted(missing)}"
        )

    @pytest.mark.parametrize("persona_dir", _builtin_personas(), ids=lambda p: p.name)
    def test_each_builtin_display_names_values_are_strings(
        self, persona_dir: Path
    ) -> None:
        """Every [display_names] value must be a non-empty string."""
        toml_path = persona_dir / "persona.toml"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        display_names = data.get("display_names", {})
        for role in _CANONICAL_ROLES:
            val = display_names.get(role)
            assert isinstance(val, str) and val.strip(), (
                f"{persona_dir.name}/persona.toml [display_names].{role!r} "
                f"must be a non-empty string, got {val!r}"
            )

    @pytest.mark.parametrize("persona_dir", _builtin_personas(), ids=lambda p: p.name)
    def test_each_builtin_display_names_has_no_extra_keys(
        self, persona_dir: Path
    ) -> None:
        """[display_names] must not contain keys outside the 8 AgentRole values.

        Sage D1 — strict rejection of unknown role keys. This is the
        built-in-TOML mirror of the runtime schema check.
        """
        toml_path = persona_dir / "persona.toml"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        display_names = data.get("display_names", {})
        extras = set(display_names.keys()) - _CANONICAL_ROLES
        assert not extras, (
            f"{persona_dir.name}/persona.toml [display_names] has unknown keys: "
            f"{sorted(extras)} (not in AgentRole)"
        )


# ---------------------------------------------------------------------------
# Hookspec deferred
# ---------------------------------------------------------------------------


class TestHookspecDeferredInSource:
    """Hookspec is deferred for v0.1 — no file, no class, no comment."""

    def test_hookspec_py_does_not_exist_in_persona(self) -> None:
        """``src/bonfire/persona/hookspec.py`` must not exist."""
        stale = _PERSONA_DIR / "hookspec.py"
        assert not stale.exists(), (
            f"{stale} must not exist in v0.1 — hookspec is deferred."
        )

    def test_no_persona_hookspec_identifier_in_src(self) -> None:
        """``PersonaHookSpec`` must not appear in any Python source in src/."""
        offenders: list[tuple[Path, int, str]] = []
        for path in _iter_python_files(_SRC_DIR):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                if "PersonaHookSpec" in line:
                    offenders.append((path, i, line.rstrip()))
        assert not offenders, (
            "Found 'PersonaHookSpec' references — hookspec is deferred:\n"
            + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
        )

    def test_no_hookspec_comment_in_loader(self) -> None:
        """The ``loader.py`` comment referencing ``hookspec`` has been scrubbed.

        v1's loader.py:69 carries a comment '# See bonfire.persona.hookspec...'.
        v0.1's port must remove this comment — it promises machinery that
        is not shipping.
        """
        loader_path = _PERSONA_DIR / "loader.py"
        assert loader_path.exists(), (
            "src/bonfire/persona/loader.py must exist for the sweep to check it"
        )
        text = loader_path.read_text(encoding="utf-8")
        assert "hookspec" not in text.lower(), (
            "src/bonfire/persona/loader.py still references 'hookspec' — "
            "scrub the deferred-plugin comment."
        )
