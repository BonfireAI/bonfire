"""BON-342 W5.3 RED — handlers/__init__.py canonical synthesis.

Sage-synthesized from Knight A (Conservative Porter) + Knight B
(Generic-Vocabulary Modernizer).

Decisions locked here:

- **D1 ADOPT `analyst`**: architect -> AgentRole.ANALYST; ROLE_DISPLAY['analyst']
  = DisplayNames("Analysis Agent", "Architect").
- **D2 ADOPT HANDLER_ROLE_MAP**: package exposes
  ``HANDLER_ROLE_MAP: dict[str, AgentRole]`` binding gamified stem -> generic
  AgentRole member. Canonical source of truth for display-layer translation.
- **D6 KEEP strategist negative assertions**: Strategist is OUT OF SCOPE for
  W5.3 and MUST NOT appear in __init__.py, __all__, or docstring.

The package expresses generic binding two ways:
1. Programmatic: ``HANDLER_ROLE_MAP``.
2. Human-readable: a docstring table that mirrors the map.

v0.1 ships exactly four handlers:

- ``BardHandler``       (gamified) -> ``publisher`` (generic)
- ``WizardHandler``     (gamified) -> ``reviewer``  (generic)
- ``HeraldHandler``     (gamified) -> ``closer``    (generic)
- ``ArchitectHandler``  (gamified) -> ``analyst``   (generic, D1)
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from bonfire.agent.roles import AgentRole
from bonfire.naming import ROLE_DISPLAY

# ---------------------------------------------------------------------------
# Package import shim
# ---------------------------------------------------------------------------

_PACKAGE_IMPORT_ERROR: str | None = None
try:
    import bonfire.handlers as handlers_pkg
except ImportError as e:  # pragma: no cover
    _PACKAGE_IMPORT_ERROR = str(e)
    handlers_pkg = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _require_handlers_package() -> None:
    if _PACKAGE_IMPORT_ERROR is not None:
        pytest.fail(
            f"bonfire.handlers package not importable: {_PACKAGE_IMPORT_ERROR}"
        )


# ---------------------------------------------------------------------------
# D1: ROLE_DISPLAY generic->gamified mapping lock
# ---------------------------------------------------------------------------


class TestRoleDisplayMapping:
    """All four generic roles have a display-map entry."""

    def test_publisher_maps_to_bard(self) -> None:
        assert "publisher" in ROLE_DISPLAY
        assert ROLE_DISPLAY["publisher"].gamified == "Bard"

    def test_reviewer_maps_to_wizard(self) -> None:
        assert "reviewer" in ROLE_DISPLAY
        assert ROLE_DISPLAY["reviewer"].gamified == "Wizard"

    def test_closer_maps_to_herald(self) -> None:
        assert "closer" in ROLE_DISPLAY
        assert ROLE_DISPLAY["closer"].gamified == "Herald"

    def test_analyst_maps_to_architect(self) -> None:
        """D1: Sage-locked — analyst -> Architect (Layer 3)."""
        assert "analyst" in ROLE_DISPLAY, (
            "Sage D1: ROLE_DISPLAY must have an 'analyst' entry for the "
            "architect handler (gamified='Architect', professional='Analysis Agent')."
        )
        assert ROLE_DISPLAY["analyst"].gamified == "Architect"
        assert ROLE_DISPLAY["analyst"].professional == "Analysis Agent"


# ---------------------------------------------------------------------------
# D2: HANDLER_ROLE_MAP programmatic contract
# ---------------------------------------------------------------------------


class TestHandlerRoleMap:
    """Single source of truth binding gamified file stem -> AgentRole."""

    def test_handler_role_map_exists(self) -> None:
        """bonfire.handlers.HANDLER_ROLE_MAP must be importable."""
        assert hasattr(handlers_pkg, "HANDLER_ROLE_MAP"), (
            "bonfire.handlers must export HANDLER_ROLE_MAP -- dict[str, AgentRole] "
            "binding gamified stem to generic role. This is the canonical source "
            "of truth for display-layer translation."
        )

    def test_handler_role_map_is_dict_of_str_to_agent_role(self) -> None:
        """HANDLER_ROLE_MAP[str] -> AgentRole (enum member, not bare string)."""
        m = handlers_pkg.HANDLER_ROLE_MAP
        assert isinstance(m, dict)
        for key, value in m.items():
            assert isinstance(key, str), f"key {key!r} must be str"
            assert isinstance(value, AgentRole), (
                f"HANDLER_ROLE_MAP[{key!r}] = {value!r} — must be an AgentRole, "
                f"not {type(value).__name__}. Bare strings defeat the point."
            )

    def test_handler_role_map_has_four_entries(self) -> None:
        """Exactly four keys: bard, wizard, herald, architect. No strategist (D6)."""
        m = handlers_pkg.HANDLER_ROLE_MAP
        assert set(m.keys()) == {"bard", "wizard", "herald", "architect"}, (
            f"HANDLER_ROLE_MAP must have exactly {{bard, wizard, herald, architect}}; "
            f"got {sorted(m.keys())}. Strategist is OUT OF SCOPE for W5.3."
        )

    def test_bard_maps_to_publisher(self) -> None:
        assert handlers_pkg.HANDLER_ROLE_MAP["bard"] is AgentRole.PUBLISHER

    def test_wizard_maps_to_reviewer(self) -> None:
        assert handlers_pkg.HANDLER_ROLE_MAP["wizard"] is AgentRole.REVIEWER

    def test_herald_maps_to_closer(self) -> None:
        assert handlers_pkg.HANDLER_ROLE_MAP["herald"] is AgentRole.CLOSER

    def test_architect_maps_to_analyst(self) -> None:
        """D1-locked: architect stem -> AgentRole.ANALYST."""
        assert hasattr(AgentRole, "ANALYST"), (
            "Sage D1: AgentRole.ANALYST must exist. The architect handler binds "
            "to this generic role."
        )
        assert handlers_pkg.HANDLER_ROLE_MAP["architect"] is AgentRole.ANALYST


# ---------------------------------------------------------------------------
# __all__ contract
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_all_contains_four_handler_classes(self) -> None:
        """__all__ exports exactly the four gamified handler classes."""
        expected = {"ArchitectHandler", "BardHandler", "HeraldHandler", "WizardHandler"}
        actual = set(getattr(handlers_pkg, "__all__", []))
        missing = expected - actual
        assert not missing, f"__all__ missing: {missing}"

    def test_all_does_not_export_strategist(self) -> None:
        """D6: StrategistHandler is OUT OF SCOPE for W5.3."""
        assert "StrategistHandler" not in getattr(handlers_pkg, "__all__", [])

    def test_all_exports_handler_role_map(self) -> None:
        """HANDLER_ROLE_MAP must be in __all__ so downstream readers see it."""
        assert "HANDLER_ROLE_MAP" in getattr(handlers_pkg, "__all__", [])

    def test_handler_classes_importable_from_package(self) -> None:
        """All four classes available at bonfire.handlers.<Name>."""
        for name in ("BardHandler", "WizardHandler", "HeraldHandler", "ArchitectHandler"):
            assert hasattr(handlers_pkg, name), f"{name} missing from package"


# ---------------------------------------------------------------------------
# Package docstring shape
# ---------------------------------------------------------------------------


class TestPackageDocstring:
    def test_docstring_present(self) -> None:
        assert handlers_pkg.__doc__ is not None
        assert handlers_pkg.__doc__.strip(), "Package docstring must not be empty"

    def test_docstring_lists_four_gamified_names(self) -> None:
        """Docstring mentions all four gamified handler names."""
        doc = handlers_pkg.__doc__ or ""
        for name in ("Bard", "Wizard", "Herald", "Architect"):
            assert name in doc, (
                f"bonfire.handlers docstring must mention the gamified name {name!r}"
            )

    def test_docstring_lists_four_generic_names(self) -> None:
        """Docstring mentions the four generic role names (publisher/reviewer/closer/analyst)."""
        doc = (handlers_pkg.__doc__ or "").lower()
        for name in ("publisher", "reviewer", "closer", "analyst"):
            assert name in doc, (
                f"bonfire.handlers docstring must mention the generic role {name!r}. "
                f"The docstring is the human-readable mirror of HANDLER_ROLE_MAP."
            )

    def test_docstring_does_not_mention_strategist(self) -> None:
        """D6: Strategist is OUT OF SCOPE — no mention anywhere."""
        doc = (handlers_pkg.__doc__ or "").lower()
        assert "strategist" not in doc, (
            "Strategist is OUT OF SCOPE for W5.3; docstring must not reference it."
        )


# ---------------------------------------------------------------------------
# Mapping self-consistency with ROLE_DISPLAY and module ROLE
# ---------------------------------------------------------------------------


class TestMappingSelfConsistency:
    def test_map_roundtrips_through_role_display(self) -> None:
        """For every (stem, AgentRole) in HANDLER_ROLE_MAP, ROLE_DISPLAY has
        an entry whose gamified name equals the stem title-cased."""
        m = handlers_pkg.HANDLER_ROLE_MAP
        for stem, role in m.items():
            assert role.value in ROLE_DISPLAY, (
                f"HANDLER_ROLE_MAP[{stem!r}] = {role!r} but no ROLE_DISPLAY entry"
            )
            assert ROLE_DISPLAY[role.value].gamified.lower() == stem, (
                f"Stem {stem!r} must equal ROLE_DISPLAY[{role.value!r}].gamified "
                f"(lower-cased) = {ROLE_DISPLAY[role.value].gamified.lower()!r}"
            )

    def test_each_handler_module_role_matches_map_entry(self) -> None:
        """For every stem S in HANDLER_ROLE_MAP, module bonfire.handlers.S
        exposes ROLE equal to the map's value (enum identity)."""
        m = handlers_pkg.HANDLER_ROLE_MAP
        for stem, role in m.items():
            module_name = f"bonfire.handlers.{stem}"
            try:
                mod = importlib.import_module(module_name)
            except ImportError:  # pragma: no cover
                pytest.fail(f"Module {module_name} is not importable")
            assert hasattr(mod, "ROLE"), f"{module_name} must expose ROLE"
            assert mod.ROLE is role, (
                f"{module_name}.ROLE ({mod.ROLE!r}) != HANDLER_ROLE_MAP[{stem!r}] "
                f"({role!r}). Must be enum identity, not merely ==."
            )


# ---------------------------------------------------------------------------
# Strategist out-of-scope invariant (D6)
# ---------------------------------------------------------------------------


class TestStrategistOutOfScope:
    def test_strategist_module_not_imported_by_package_init(self) -> None:
        """handlers/__init__.py source must not import strategist."""
        init_path = Path(handlers_pkg.__file__)
        src = init_path.read_text()
        assert "strategist" not in src.lower(), (
            "Strategist is OUT OF SCOPE for W5.3. "
            "handlers/__init__.py must not reference it."
        )


# ---------------------------------------------------------------------------
# Filename discipline (gamified filenames locked)
# ---------------------------------------------------------------------------


class TestFilenameDiscipline:
    @pytest.mark.xfail(
        reason="v0.1 gap: handler modules not yet ported",
        strict=False,
    )
    def test_filenames_stay_gamified(self) -> None:
        """Gamified filenames stay: bard.py / wizard.py / herald.py / architect.py."""
        importlib.import_module("bonfire.handlers.bard")
        importlib.import_module("bonfire.handlers.wizard")
        importlib.import_module("bonfire.handlers.herald")
        importlib.import_module("bonfire.handlers.architect")
