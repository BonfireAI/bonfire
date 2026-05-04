"""RED tests for bonfire.onboard.scanners.project_structure — BON-349 (CONTRACT-LOCKED).

Sage decision logs:
  - docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md (Warrior contract)
  - docs/audit/sage-decisions/bon-349-contract-lock-*.md (Knight A/B reconciliation)

Floor (8 tests, per Sage §D6 Row 3): port v1 test_scanner_project_structure.py
test surface verbatim, with the import renames
``bonfire.front_door.scanners.project_structure`` →
``bonfire.onboard.scanners.project_structure`` (Sage §D3 row 8).

Innovations (2 adopted, drift-guards over Sage floor):

  * ``TestPanelConstantContract::test_panel_constant_value_is_stable``
    — Asserts ``PANEL == "project_structure"`` is exported as a module-level
    constant (the panel name flows into orchestrator's panel-name list and
    every emitted ScanUpdate). The floor only checks panel-name on
    individual events. Cites Sage Appendix item 1 (PANEL vs _PANEL naming
    inconsistency) + v1 src/bonfire/front_door/scanners/project_structure.py:25
    (``PANEL = "project_structure"``).

  * ``TestTechScannerImportRename::test_techscanner_imported_from_v01_module_path``
    — Asserts the v0.1 cross-module rename succeeded:
    ``bonfire.scan.tech_scanner.TechScanner`` is importable AND the
    project_structure scanner module pulls from that path (NOT v1's
    ``bonfire.scanners.fingerprinter.TechFingerprinter``). This is the only
    non-trivial cross-module import delta in the entire BON-349 port and
    deserves an explicit guard. Cites Sage §D3 row 9 + v1
    src/bonfire/front_door/scanners/project_structure.py:18
    (``from bonfire.scanners.fingerprinter import TechFingerprinter``)
    that becomes v0.1
    src/bonfire/onboard/scanners/project_structure.py:18
    (``from bonfire.scan.tech_scanner import TechScanner``).

Imports are RED — ``bonfire.onboard.scanners.project_structure`` does not exist
until Warriors port v1 source per Sage §D9.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from bonfire.onboard.protocol import ScanUpdate


async def test_scan_emits_language_events(tmp_path):
    """Scanner emits ScanUpdate for detected languages."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "main.py").touch()

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    count = await scan(tmp_path, emit)

    assert count > 0
    assert emit.call_count == count
    # At least one language event
    techs = [call.args[0].value for call in emit.call_args_list]
    assert "Python" in techs


async def test_scan_emits_framework_events(tmp_path):
    """Scanner emits ScanUpdate for detected frameworks."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="test"\n\n[project.dependencies]\n"pytest>=8.0"\n'
    )
    (tmp_path / "main.py").touch()

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    await scan(tmp_path, emit)

    techs = [call.args[0].value for call in emit.call_args_list]
    assert "pytest" in techs


async def test_panel_is_always_project_structure(tmp_path):
    """Every emitted ScanUpdate has panel='project_structure'."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "main.py").touch()

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    await scan(tmp_path, emit)

    for call in emit.call_args_list:
        event = call.args[0]
        assert isinstance(event, ScanUpdate)
        assert event.panel == "project_structure"


async def test_empty_project_returns_zero(tmp_path):
    """Project with no config files returns 0 and emits nothing."""
    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    count = await scan(tmp_path, emit)

    assert count == 0
    emit.assert_not_called()


async def test_returned_count_matches_emitted(tmp_path):
    """Return value equals number of emit calls."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "package.json").write_text(json.dumps({"name": "test"}))
    (tmp_path / "main.py").touch()
    (tmp_path / "app.js").touch()

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    count = await scan(tmp_path, emit)

    assert count == emit.call_count
    assert count >= 2  # At least Python + JavaScript


async def test_detail_includes_file_count_when_present(tmp_path):
    """When file_count exists in metadata, detail shows it."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "main.py").touch()
    (tmp_path / "utils.py").touch()

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    await scan(tmp_path, emit)

    # Find the Python language event
    python_events = [
        call.args[0]
        for call in emit.call_args_list
        if call.args[0].value == "Python" and call.args[0].label == "language"
    ]
    assert len(python_events) == 1
    assert "files" in python_events[0].detail


async def test_detail_falls_back_to_source_file(tmp_path):
    """When file_count is absent, detail shows source_file."""
    # Frameworks from requirements.txt don't get file_count
    (tmp_path / "requirements.txt").write_text("django>=5.0\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    await scan(tmp_path, emit)

    django_events = [call.args[0] for call in emit.call_args_list if call.args[0].value == "Django"]
    assert len(django_events) == 1
    assert django_events[0].detail == "requirements.txt"


async def test_label_is_category(tmp_path):
    """Label field comes from metadata category."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "main.py").touch()

    emit = AsyncMock()
    from bonfire.onboard.scanners.project_structure import scan

    await scan(tmp_path, emit)

    labels = {call.args[0].label for call in emit.call_args_list}
    assert "language" in labels


# ---------------------------------------------------------------------------
# INNOVATIONS (Knight B drift-guards — Sage Appendix item 1 + §D3 row 9)
# ---------------------------------------------------------------------------


class TestPanelConstantContract:
    """Innovation: PANEL constant export contract.

    Cites Sage Appendix item 1 (PANEL vs _PANEL naming inconsistency) + v1
    src/bonfire/front_door/scanners/project_structure.py:25
    (``PANEL = "project_structure"``).
    """

    def test_panel_constant_value_is_stable(self) -> None:
        """``PANEL`` module constant equals ``"project_structure"``."""
        from bonfire.onboard.scanners.project_structure import PANEL

        assert PANEL == "project_structure", (
            "PANEL module constant must equal 'project_structure' (v1 verbatim) "
            "— this string flows into every emitted ScanUpdate.panel"
        )


class TestTechScannerImportRename:
    """Innovation: cross-module rename to v0.1 surface.

    Cites Sage §D3 row 9 + v1 src/bonfire/front_door/scanners/project_structure.py:18
    (``from bonfire.scanners.fingerprinter import TechFingerprinter``) →
    v0.1 expected (``from bonfire.scan.tech_scanner import TechScanner``).
    """

    def test_techscanner_imported_from_v01_module_path(self) -> None:
        """v0.1 surface: TechScanner is importable from bonfire.scan.tech_scanner."""
        # The new (v0.1) class must be present.
        from bonfire.scan.tech_scanner import TechScanner

        assert TechScanner is not None
        # It must be a class (not a deprecated alias function or None).
        assert isinstance(TechScanner, type)
        # Old (v1) symbol path must NOT be exported by the onboard scanner module
        # (we don't want a leftover compat shim importing TechFingerprinter).
        import bonfire.onboard.scanners.project_structure as ps_mod

        assert not hasattr(ps_mod, "TechFingerprinter"), (
            "project_structure must NOT re-export TechFingerprinter; the v1→v0.1 "
            "rename per Sage §D3 row 9 deletes that name"
        )
