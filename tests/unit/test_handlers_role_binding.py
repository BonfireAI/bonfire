"""BON-342 W5.3 RED — Cross-cutting module-level ROLE binding enforcement.

Sage-synthesized from Knight B (Generic-Vocabulary Modernizer).

This file is the load-bearing NET that catches drift across all four handler
modules. Every handler module MUST expose a module-level ``ROLE`` constant
that is:

  (a) an ``AgentRole`` enum member, and
  (b) identical to the value in ``HANDLER_ROLE_MAP`` for that module's stem.

Even if one module drifts (copy-pasted from another, forgot to update ROLE,
or hand-typed a string instead of using the enum), this suite catches it.

Decisions locked:

- **D1 ADOPT `analyst`**: architect -> AgentRole.ANALYST.
- **D2 ADOPT HANDLER_ROLE_MAP**: package exports stem->AgentRole dict.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from bonfire.agent.roles import AgentRole


def _import_or_fail(module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"{module_name} not importable; Warrior must land it. ImportError: {e}")


# ---------------------------------------------------------------------------
# Expected bindings (single source of truth for THIS test file)
# ---------------------------------------------------------------------------


def _analyst_or_none() -> AgentRole | None:
    """Return AgentRole.ANALYST or None (so the class import doesn't crash
    when roles.py hasn't been widened yet; test failures are cleaner)."""
    return getattr(AgentRole, "ANALYST", None)


EXPECTED_ROLE_BINDINGS: dict[str, AgentRole | None] = {
    "bard": AgentRole.PUBLISHER,
    "wizard": AgentRole.REVIEWER,
    "steward": AgentRole.CLOSER,
    "architect": _analyst_or_none(),  # D1-locked: analyst
}


# ---------------------------------------------------------------------------
# Per-module ROLE constant enforcement
# ---------------------------------------------------------------------------


class TestModuleRoleConstants:
    """Every handler module exposes module-level ROLE bound to AgentRole."""

    @pytest.mark.parametrize("stem", ["bard", "wizard", "steward", "architect"])
    def test_module_has_role_constant(self, stem: str) -> None:
        mod = _import_or_fail(f"bonfire.handlers.{stem}")
        assert hasattr(mod, "ROLE"), (
            f"bonfire.handlers.{stem} MUST expose module-level `ROLE` constant. "
            "This is the grep target that binds the gamified file to its "
            "generic identity. Without it, the code-layer soul is invisible."
        )

    @pytest.mark.parametrize("stem", ["bard", "wizard", "steward", "architect"])
    def test_module_role_is_agent_role_instance(self, stem: str) -> None:
        """ROLE must be an AgentRole enum member — not a bare string.

        D1 locked: architect binds to AgentRole.ANALYST (profession-like,
        anchored in bonfire.analysis/). Strict enum identity enforced for
        all four handlers.
        """
        mod = _import_or_fail(f"bonfire.handlers.{stem}")
        assert isinstance(mod.ROLE, AgentRole), (
            f"bonfire.handlers.{stem}.ROLE = {mod.ROLE!r} "
            f"(type {type(mod.ROLE).__name__}) -- MUST be an AgentRole. "
            f"Bare strings defeat the point."
        )

    @pytest.mark.parametrize(
        ("stem", "expected_value"),
        [
            ("bard", "publisher"),
            ("wizard", "reviewer"),
            ("steward", "closer"),
            ("architect", "analyst"),  # D1
        ],
    )
    def test_module_role_value_equals_expected(self, stem: str, expected_value: str) -> None:
        """ROLE StrEnum value-equals the locked generic role string."""
        mod = _import_or_fail(f"bonfire.handlers.{stem}")
        assert mod.ROLE == expected_value, (
            f"bonfire.handlers.{stem}.ROLE string-value = {mod.ROLE!r}; "
            f"expected {expected_value!r}. Check ROLE assignment and the "
            f"underlying AgentRole member value."
        )


# ---------------------------------------------------------------------------
# Cross-check: module ROLE == HANDLER_ROLE_MAP[stem]
# ---------------------------------------------------------------------------


class TestModuleRoleMatchesHandlerRoleMap:
    """Locks the binding in BOTH places so drift surfaces immediately."""

    @pytest.mark.parametrize("stem", ["bard", "wizard", "steward", "architect"])
    def test_module_role_matches_handler_role_map(self, stem: str) -> None:
        handlers_pkg = _import_or_fail("bonfire.handlers")
        mod = _import_or_fail(f"bonfire.handlers.{stem}")

        assert hasattr(handlers_pkg, "HANDLER_ROLE_MAP"), (
            "bonfire.handlers.HANDLER_ROLE_MAP must exist — see "
            "test_handlers_package.py for the top-level contract."
        )
        m = handlers_pkg.HANDLER_ROLE_MAP
        assert stem in m, f"HANDLER_ROLE_MAP missing entry for {stem!r}"
        assert m[stem] is mod.ROLE, (
            f"Drift detected: bonfire.handlers.{stem}.ROLE = {mod.ROLE!r} "
            f"but HANDLER_ROLE_MAP[{stem!r}] = {m[stem]!r}. "
            f"The two MUST be identical (enum identity, not just equal)."
        )


# ---------------------------------------------------------------------------
# Negative drift guard: no module hardcodes a "role" string it should derive
# ---------------------------------------------------------------------------


class TestNoStringRoleDrift:
    """Module ROLE value comes from AgentRole, not from a typed-in string."""

    @pytest.mark.parametrize("stem", ["bard", "wizard", "steward", "architect"])
    def test_all_modules_ROLE_is_enum(self, stem: str) -> None:
        """D1 locked: ALL four modules must have ROLE as an AgentRole enum
        instance (architect binds to AgentRole.ANALYST, no exemption).
        """
        mod = _import_or_fail(f"bonfire.handlers.{stem}")
        assert isinstance(mod.ROLE, AgentRole), (
            f"bonfire.handlers.{stem}.ROLE must be an AgentRole instance, "
            f"not {type(mod.ROLE).__name__}."
        )
