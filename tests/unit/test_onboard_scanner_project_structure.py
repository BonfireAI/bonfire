"""RED tests for bonfire.onboard.scanners.project_structure — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 8 tests per Sage §D6 Row 3. Verbatim v1 port. No innovations (conservative lens).
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
