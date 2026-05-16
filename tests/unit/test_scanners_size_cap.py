# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Size-cap hardening across project-state scanners.

Six readers in the scanner stack do ``Path.read_text()`` against
``CLAUDE.md`` / ``MEMORY.md`` / ``pyproject.toml`` /
``requirements.txt`` / ``package.json`` without any size guard. A 5 GB
file or a ``/dev/zero`` symlink hangs the scanner. The fix routes
each call through :func:`bonfire._safe_read.safe_read_text`, which
stat-checks before reading and truncates with a marker on cap-exceeded.

These tests assert each affected reader:

  * Returns truncated content (not raises, not hangs) on an oversize
    file when the cap env var is dropped below the file size.
  * Continues to detect its intended pattern when the truncated content
    still contains the marker substring — defends against an
    overly-eager truncation breaking detection on the small-file path.

Real files + real env-var caps are used; no mocks of the cap value.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

from bonfire.onboard.protocol import ScanUpdate
from bonfire.onboard.scanners import claude_memory
from bonfire.scan.tech_scanner import TechScanner


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    return [c.args[0] for c in emit.call_args_list]


# ---------------------------------------------------------------------------
# claude_memory — settings.json
# ---------------------------------------------------------------------------


async def test_oversize_settings_json_truncated_warning(tmp_path, monkeypatch, caplog) -> None:
    """A multi-MB ``settings.json`` is truncated, not read whole.

    Because the truncated bytes will not be valid JSON, ``_scan_settings``
    returns 0 (silent skip) — exactly the behaviour the existing
    ``json.JSONDecodeError`` branch defines. The contract the test pins
    is the WARNING + non-hang; the JSON-decode failure is incidental.
    """
    monkeypatch.setenv("BONFIRE_CLAUDE_SETTINGS_MAX_BYTES", "256")

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    # 8 KB of valid JSON (much smaller than typical hostile case, but
    # comfortably over the 256-byte test cap).
    big_settings = {"model": "claude-x", "extensions": [{"enabled": True}] * 200}
    (claude_dir / "settings.json").write_text(json.dumps(big_settings))

    emit = AsyncMock()
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        # _scan_settings expects the .claude dir, not project root.
        count = await claude_memory._scan_settings(claude_dir, emit)

    # Truncated JSON => decode failure => 0 events emitted.
    assert count == 0
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


async def test_small_settings_json_unbroken(tmp_path) -> None:
    """A normal ``settings.json`` still emits structural events."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps({"model": "claude-x", "permissions": {"allow": ["x"]}})
    )

    emit = AsyncMock()
    count = await claude_memory._scan_settings(claude_dir, emit)

    assert count >= 1
    labels = {e.label for e in _events(emit)}
    assert "model" in labels
    assert "permissions" in labels


# ---------------------------------------------------------------------------
# claude_memory — MEMORY.md
# ---------------------------------------------------------------------------


async def test_oversize_memory_md_truncated_still_counts_entries(
    tmp_path, monkeypatch, caplog
) -> None:
    """An oversize MEMORY.md is read truncated; index entries within the
    first cap bytes still get counted."""
    monkeypatch.setenv("BONFIRE_MEMORY_READ_MAX_BYTES", "256")

    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    # Three index lines well within the first 256 bytes, then padding.
    header = "- [topic-a](a.md) — desc\n- [topic-b](b.md) — desc\n- [topic-c](c.md) — desc\n"
    padding = "padding line\n" * 5000
    (mem_dir / "MEMORY.md").write_text(header + padding)

    emit = AsyncMock()
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        count = await claude_memory._scan_memory_index(mem_dir, emit)

    assert count == 1
    events = _events(emit)
    assert events[0].label == "memory topics"
    # The 3 index lines fit comfortably in the cap.
    assert "3" in events[0].value
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# claude_memory — CLAUDE.md
# ---------------------------------------------------------------------------


async def test_oversize_claude_md_truncated_still_counts_sections(
    tmp_path, monkeypatch, caplog
) -> None:
    """An oversize CLAUDE.md is read truncated; section headers in the
    first cap bytes still count."""
    monkeypatch.setenv("BONFIRE_CLAUDE_MD_READ_MAX_BYTES", "256")

    header = "# Top\n## Section A\n## Section B\n"
    padding = "x" * 10_000
    (tmp_path / "CLAUDE.md").write_text(header + padding)

    emit = AsyncMock()
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        count = await claude_memory._scan_claude_md(tmp_path, emit)

    assert count == 1
    events = _events(emit)
    assert events[0].label == "CLAUDE.md"
    # Three '#'-prefixed lines in the header.
    assert "3 sections" in events[0].detail
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# tech_scanner — requirements.txt / pyproject.toml / package.json
# ---------------------------------------------------------------------------


async def test_oversize_requirements_txt_truncated(tmp_path, monkeypatch, caplog) -> None:
    """Oversize requirements.txt does NOT hang; truncated content still
    enables framework detection for entries in the first cap bytes."""
    monkeypatch.setenv("BONFIRE_TECH_SCAN_MANIFEST_MAX_BYTES", "128")

    header = "pytest>=8.0\n"
    padding = "# pad\n" * 5000
    (tmp_path / "requirements.txt").write_text(header + padding)

    scanner = TechScanner(tmp_path, project_name="t")
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        entries = await scanner.scan()

    techs = {e.metadata["technology"] for e in entries}
    assert "pytest" in techs
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


async def test_oversize_pyproject_toml_truncated(tmp_path, monkeypatch, caplog) -> None:
    """Oversize pyproject.toml does NOT hang."""
    monkeypatch.setenv("BONFIRE_TECH_SCAN_MANIFEST_MAX_BYTES", "256")

    head = "[project]\nname='t'\n[project.dependencies]\npytest = '>=8.0'\n"
    padding = "# pad line\n" * 5000
    (tmp_path / "pyproject.toml").write_text(head + padding)

    scanner = TechScanner(tmp_path, project_name="t")
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        entries = await scanner.scan()

    # Manifest detection for the language always fires from the file's
    # existence; the framework detection is what depends on the truncated
    # content. Both should land cleanly under truncation.
    techs = {e.metadata["technology"] for e in entries}
    assert "Python" in techs  # language manifest detection
    assert "pytest" in techs  # truncated read still found pytest
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


async def test_oversize_package_json_truncated_graceful(tmp_path, monkeypatch, caplog) -> None:
    """Oversize package.json does NOT hang; truncation that breaks JSON
    parsing yields an empty deps dict (graceful)."""
    monkeypatch.setenv("BONFIRE_TECH_SCAN_MANIFEST_MAX_BYTES", "64")

    big = {"name": "t", "dependencies": {"react": "^18.0.0"}, "pad": "X" * 10_000}
    (tmp_path / "package.json").write_text(json.dumps(big))

    scanner = TechScanner(tmp_path, project_name="t")
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        entries = await scanner.scan()

    # Truncated => JSON decode fails => no framework entries from package.json.
    # The JavaScript language entry is still produced from the file's
    # existence alone.
    techs = {e.metadata["technology"] for e in entries}
    assert "JavaScript" in techs
    assert "React" not in techs
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Regression — small files still work
# ---------------------------------------------------------------------------


async def test_small_requirements_txt_unbroken(tmp_path) -> None:
    """Normal small requirements.txt still detects frameworks."""
    (tmp_path / "requirements.txt").write_text("pytest>=8.0\ndjango>=5.0\n")

    scanner = TechScanner(tmp_path, project_name="t")
    entries = await scanner.scan()
    techs = {e.metadata["technology"] for e in entries}

    assert "pytest" in techs
    assert "Django" in techs


async def test_small_claude_md_unbroken(tmp_path) -> None:
    """Normal small CLAUDE.md still counts section headers."""
    (tmp_path / "CLAUDE.md").write_text("# Top\n## A\n## B\n")

    emit = AsyncMock()
    count = await claude_memory._scan_claude_md(tmp_path, emit)

    assert count == 1
    events = _events(emit)
    assert "3 sections" in events[0].detail
