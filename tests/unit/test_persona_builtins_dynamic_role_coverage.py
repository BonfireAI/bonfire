"""Forever-guard: every shipped built-in persona covers every AgentRole.

This test is the tripwire added by BON-520 (Sage §D5) to prevent the class of
cross-wave failure that motivated the reconciliation:

  * BON-342 widened ``AgentRole`` by one member (``analyst``) in one wave.
  * BON-345 shipped three built-in persona TOMLs in a parallel wave, each
    with a ``[display_names]`` map scoped to the 8-role enum at authoring
    time.
  * Both waves passed their scoped pytest and merged independently.
  * The combined tip was RED: every built-in's display-names map had 8 of
    the 9 canonical roles.

The fix is contract-level: any future widening of ``AgentRole`` must be
accompanied by a matching widening of every shipped built-in — the two
cannot drift without at least one tripwire firing.

Why this test AND ``test_persona_builtin.py`` / ``test_persona_defaults.py``
-----------------------------------------------------------------------
Those existing suites already assert each built-in covers every role, but
they go through the loader (``PersonaLoader.validate()``) or check a
hardcoded per-persona list. This test:

  1. Reads the ``AgentRole`` enum at collection time — dynamic source of
     truth. If a new role is added, this test automatically extends its
     coverage assertions to that role.
  2. Reads persona TOMLs directly via ``tomllib`` — bypasses the loader
     entirely, so a regression in the loader's validator cannot mask a
     built-in's defect.
  3. Parametrises over every ``(persona_dir, agent_role)`` pair so a
     failure message names exactly which persona lacks which role.

Two independent paths to the same invariant = doubled-up tripwire.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from bonfire.agent.roles import AgentRole

# ---------------------------------------------------------------------------
# Discover the shipped built-in directory on disk
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILTINS_DIR = _REPO_ROOT / "src" / "bonfire" / "persona" / "builtins"


def _shipped_builtin_dirs() -> list[Path]:
    """Return every built-in persona directory that ships a ``persona.toml``."""
    if not _BUILTINS_DIR.is_dir():
        return []
    return sorted(
        child
        for child in _BUILTINS_DIR.iterdir()
        if child.is_dir() and (child / "persona.toml").is_file()
    )


def _load_display_names(persona_dir: Path) -> dict[str, object]:
    """Read the ``[display_names]`` table from the persona's TOML.

    Returns an empty dict if the table is absent so the coverage assertion
    below produces a clean failure message naming the missing role(s)
    rather than a KeyError.
    """
    toml_path = persona_dir / "persona.toml"
    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    raw = data.get("display_names", {})
    if not isinstance(raw, dict):
        return {}
    return raw


# Build the (persona, role) matrix at collection time so every missing cell
# surfaces as its own parametrize id, making batch failures readable.
_PERSONA_ROLE_MATRIX: list[tuple[Path, AgentRole]] = [
    (persona_dir, role) for persona_dir in _shipped_builtin_dirs() for role in AgentRole
]


def _matrix_id(param: object) -> str:
    if isinstance(param, Path):
        return param.name
    if isinstance(param, AgentRole):
        return param.value
    return repr(param)


# ---------------------------------------------------------------------------
# The forever-guard: one assertion per (persona, role) cell
# ---------------------------------------------------------------------------


class TestDynamicRoleCoverage:
    """Every shipped built-in must cover every AgentRole value at test time."""

    def test_at_least_one_builtin_discovered(self) -> None:
        """Guard against an empty builtins dir silently passing the matrix."""
        assert _shipped_builtin_dirs(), (
            f"No shipped built-in personas found under {_BUILTINS_DIR}; "
            "bonfire-public must ship at least 'default' and 'minimal'."
        )

    @pytest.mark.parametrize(
        ("persona_dir", "role"),
        _PERSONA_ROLE_MATRIX,
        ids=lambda p: _matrix_id(p),
    )
    def test_builtin_has_display_name_for_role(self, persona_dir: Path, role: AgentRole) -> None:
        """Built-in persona's ``[display_names]`` must include this role.

        Source of truth is the live ``AgentRole`` enum. If a role is added
        upstream without the built-in's TOML being updated in the same
        merge train, this fires with a message naming both the persona
        and the role.
        """
        display_names = _load_display_names(persona_dir)
        assert role.value in display_names, (
            f"Built-in persona {persona_dir.name!r} is missing a "
            f"[display_names] entry for AgentRole.{role.name} "
            f"({role.value!r}). Any widening of AgentRole must be "
            "accompanied by a matching widening of every shipped "
            "built-in's display-names map."
        )
        value = display_names[role.value]
        assert isinstance(value, str) and value.strip(), (
            f"Built-in persona {persona_dir.name!r}: "
            f"[display_names].{role.value} must be a non-empty string, "
            f"got {value!r}."
        )
