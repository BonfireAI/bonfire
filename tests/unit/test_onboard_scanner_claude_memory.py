"""RED tests for bonfire.onboard.scanners.claude_memory — BON-349 W6.3 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md

Floor (16 tests, per Sage §D6 Row 5): port v1 test_scanner_claude_memory.py
test surface verbatim, with the import renames
``bonfire.front_door.scanners.claude_memory`` →
``bonfire.onboard.scanners.claude_memory`` and the keyword-only
``home_dir=tmp_path`` override pattern preserved per Sage §D8.

Innovations (2 tests, INNOVATIVE-lens drift-guards over Sage floor):

  * ``TestPanelConstantContract::test_panel_constant_value_is_stable``
    — Asserts ``PANEL == "claude_memory"`` is exported as a module-level
    constant (no underscore, per Sage Appendix item 1's claim that
    claude_memory uses the un-prefixed convention). The floor only checks
    panel name on individual events. Cites Sage Appendix item 1 + v1
    src/bonfire/front_door/scanners/claude_memory.py:30
    (``PANEL = "claude_memory"``).

  * ``TestMemoryTypePrefixesContract::test_memory_type_prefixes_tuple_is_stable``
    — Asserts ``_MEMORY_TYPE_PREFIXES`` is the locked 5-tuple
    ``("feedback", "project", "reference", "session", "user")`` per Sage §D8
    "claude_memory.py — LOCKED". The floor exercises individual prefixes
    (feedback, project, reference, user, session) but does not assert the
    full tuple ordering or completeness — a silent rename to
    ``("feedback", "project", "reference", "user")`` (4-tuple) would slip
    past the floor as long as no test happens to use the dropped prefix.
    Cites Sage §D8 "claude_memory.py — LOCKED" + v1
    src/bonfire/front_door/scanners/claude_memory.py:33
    (``_MEMORY_TYPE_PREFIXES = ("feedback", "project", "reference", "session", "user")``).

Imports are RED — ``bonfire.onboard.scanners.claude_memory`` does not exist
until Warriors port v1 source per Sage §D9.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_claude_dir(home, *, settings: dict | None = None):
    """Create a minimal ~/.claude/ directory structure."""
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    if settings is not None:
        (claude_dir / "settings.json").write_text(json.dumps(settings))
    return claude_dir


def _build_memory_dir(home, project_path, *, files: dict[str, str] | None = None):
    """Create the encoded memory directory with optional files.

    ``files`` maps filename -> file content.
    """
    encoded = str(project_path).lstrip("/").replace("/", "-")
    mem_dir = home / ".claude" / "projects" / f"-{encoded}" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    if files:
        for name, content in files.items():
            (mem_dir / name).write_text(content)
    return mem_dir


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    return [c.args[0] for c in emit.call_args_list]


# ---------------------------------------------------------------------------
# Claude Code installed
# ---------------------------------------------------------------------------


async def test_detects_claude_installed(tmp_path):
    """Scanner emits 'Claude Code' / 'installed' when ~/.claude exists."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={"model": "opus"})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    count = await scan(project, emit, home_dir=home)

    assert count >= 1
    events = _events(emit)
    assert all(e.panel == "claude_memory" for e in events)
    assert any(e.label == "Claude Code" and e.value == "installed" for e in events)


async def test_missing_claude_dir_returns_zero(tmp_path):
    """When ~/.claude/ does not exist, scanner returns 0 and emits nothing."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 0
    emit.assert_not_called()


# ---------------------------------------------------------------------------
# Panel name
# ---------------------------------------------------------------------------


async def test_panel_is_always_claude_memory(tmp_path):
    """Every emitted event has panel='claude_memory'."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={"model": "opus", "permissions": "auto"})
    project = tmp_path / "project"
    project.mkdir()
    (project / "CLAUDE.md").write_text("# My Project\n## Setup\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    for event in _events(emit):
        assert isinstance(event, ScanUpdate)
        assert event.panel == "claude_memory"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


async def test_reads_settings_model(tmp_path):
    """Reports model override from settings.json."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={"model": "claude-sonnet-4-20250514"})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    model_events = [e for e in events if e.label == "model"]
    assert len(model_events) == 1
    assert model_events[0].value == "claude-sonnet-4-20250514"


async def test_reads_settings_permissions(tmp_path):
    """Reports permissions mode from settings.json."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={"permissions": "auto-approve"})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    perm_events = [e for e in events if e.label == "permissions"]
    assert len(perm_events) == 1
    assert perm_events[0].value == "auto-approve"


async def test_missing_settings_still_works(tmp_path):
    """Scanner works when settings.json is absent."""
    home = tmp_path / "home"
    _build_claude_dir(home)  # No settings file
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    count = await scan(project, emit, home_dir=home)

    # Should still report Claude Code installed
    assert count >= 1
    events = _events(emit)
    assert any(e.label == "Claude Code" and e.value == "installed" for e in events)
    # No model or permissions events
    assert not any(e.label == "model" for e in events)
    assert not any(e.label == "permissions" for e in events)


async def test_settings_with_extensions(tmp_path):
    """Reports count of enabled extensions."""
    home = tmp_path / "home"
    _build_claude_dir(
        home,
        settings={
            "extensions": [
                {"name": "ext1", "enabled": True},
                {"name": "ext2", "enabled": True},
                {"name": "ext3", "enabled": False},
            ]
        },
    )
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    ext_events = [e for e in events if e.label == "extensions"]
    assert len(ext_events) == 1
    assert ext_events[0].value == "2 enabled"


# ---------------------------------------------------------------------------
# Memory files by type
# ---------------------------------------------------------------------------


async def test_counts_memory_files_by_type(tmp_path):
    """Counts memory files grouped by frontmatter type."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    mem_dir = _build_memory_dir(home, project)
    # Create memory files with frontmatter
    files = {
        "feedback_one.md": "- [Feedback one](feedback_one.md) -- first feedback",
        "feedback_two.md": "- [Feedback two](feedback_two.md) -- second feedback",
        "project_info.md": "- [Project info](project_info.md) -- project detail",
        "reference_git.md": "- [Git ref](reference_git.md) -- git reference",
        "user_identity.md": "- [Identity](user_identity.md) -- user info",
    }
    for name, content in files.items():
        (mem_dir / name).write_text(content)

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    # Should have events for feedback, project, reference, user types
    type_events = {e.label: e.value for e in events if "memories" in e.label}
    assert "feedback memories" in type_events
    assert type_events["feedback memories"] == "2"
    assert "project memories" in type_events
    assert type_events["project memories"] == "1"
    assert "reference memories" in type_events
    assert type_events["reference memories"] == "1"
    assert "user memories" in type_events
    assert type_events["user memories"] == "1"


async def test_counts_session_prefixed_memory_files(tmp_path):
    """Session-prefixed files are counted as a memory type."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    mem_dir = _build_memory_dir(home, project)
    (mem_dir / "session_001.md").write_text("session content")
    (mem_dir / "session_002.md").write_text("session content")

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    type_events = {e.label: e.value for e in events if "memories" in e.label}
    assert "session memories" in type_events
    assert type_events["session memories"] == "2"


async def test_emits_total_memory_file_count(tmp_path):
    """Scanner emits a total count of all memory files with per-type breakdown in detail."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    mem_dir = _build_memory_dir(home, project)
    files = {
        "feedback_one.md": "content",
        "feedback_two.md": "content",
        "feedback_three.md": "content",
        "project_info.md": "content",
        "project_plan.md": "content",
        "project_arch.md": "content",
        "project_deps.md": "content",
        "project_test.md": "content",
        "user_identity.md": "content",
        "user_prefs.md": "content",
        "user_style.md": "content",
        "user_name.md": "content",
    }
    for name, content in files.items():
        (mem_dir / name).write_text(content)

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    total_events = [e for e in events if e.label == "Memory files"]
    assert len(total_events) == 1
    assert total_events[0].value == "12"
    # Detail should break down by type
    assert "feedback: 3" in total_events[0].detail
    assert "project: 5" in total_events[0].detail
    assert "user: 4" in total_events[0].detail


async def test_missing_memory_dir_no_memory_events(tmp_path):
    """When memory directory doesn't exist, no memory events are emitted."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    assert not any("memories" in e.label for e in events)
    assert not any(e.label == "memory topics" for e in events)


# ---------------------------------------------------------------------------
# MEMORY.md index
# ---------------------------------------------------------------------------


async def test_parses_memory_md_index(tmp_path):
    """Counts entries in MEMORY.md (lines starting with '- [')."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    mem_dir = _build_memory_dir(home, project)
    memory_md = (
        "- [Topic one](topic_one.md) -- first topic\n"
        "- [Topic two](topic_two.md) -- second topic\n"
        "- [Topic three](topic_three.md) -- third topic\n"
        "\n"
        "Some other text\n"
    )
    (mem_dir / "MEMORY.md").write_text(memory_md)

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    topic_events = [e for e in events if e.label == "memory topics"]
    assert len(topic_events) == 1
    assert topic_events[0].value == "3 topics indexed"


# ---------------------------------------------------------------------------
# CLAUDE.md
# ---------------------------------------------------------------------------


async def test_detects_claude_md(tmp_path):
    """Detects CLAUDE.md in project root and counts sections."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()
    (project / "CLAUDE.md").write_text(
        "# Project Title\nSome content\n## Architecture\nMore content\n## Testing\n### Subsection\n"
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    claude_md_events = [e for e in events if e.label == "CLAUDE.md"]
    assert len(claude_md_events) == 1
    assert claude_md_events[0].value == "found"
    assert claude_md_events[0].detail == "4 sections"


async def test_missing_claude_md_no_event(tmp_path):
    """When CLAUDE.md is absent, no CLAUDE.md event is emitted."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    assert not any(e.label == "CLAUDE.md" for e in events)


# ---------------------------------------------------------------------------
# Privacy: never reads .claude.json
# ---------------------------------------------------------------------------


async def test_never_reads_claude_json(tmp_path, monkeypatch):
    """The scanner must NEVER open ~/.claude.json (contains OAuth tokens)."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    # Create the forbidden file
    (home / ".claude.json").write_text('{"oauth_token": "secret"}')

    project = tmp_path / "project"
    project.mkdir()

    # Track all file opens
    import builtins

    original_open = builtins.open
    opened_paths: list[str] = []

    def tracking_open(path, *args, **kwargs):
        opened_paths.append(str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    # Ensure .claude.json was never opened
    assert not any(".claude.json" in p for p in opened_paths)


# ---------------------------------------------------------------------------
# Return count matches emitted
# ---------------------------------------------------------------------------


async def test_return_count_matches_emitted(tmp_path):
    """Return value equals number of emit calls."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={"model": "opus", "permissions": "auto"})
    project = tmp_path / "project"
    project.mkdir()
    (project / "CLAUDE.md").write_text("# Title\n## Section\n")

    mem_dir = _build_memory_dir(home, project)
    (mem_dir / "MEMORY.md").write_text("- [Topic](t.md) -- topic\n")
    (mem_dir / "feedback_one.md").write_text("content")

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    count = await scan(project, emit, home_dir=home)

    assert count == emit.call_count
    assert count > 0


# ---------------------------------------------------------------------------
# INNOVATIONS (Knight B drift-guards — Sage Appendix item 1 + §D8)
# ---------------------------------------------------------------------------


class TestPanelConstantContract:
    """Innovation: PANEL constant export contract.

    Cites Sage Appendix item 1 (PANEL vs _PANEL naming) + v1
    src/bonfire/front_door/scanners/claude_memory.py:30
    (``PANEL = "claude_memory"`` — un-prefixed convention).
    """

    def test_panel_constant_value_is_stable(self) -> None:
        """``PANEL`` module constant equals ``"claude_memory"``."""
        from bonfire.onboard.scanners.claude_memory import PANEL

        assert PANEL == "claude_memory", (
            "PANEL module constant must equal 'claude_memory' (v1 verbatim) "
            "— un-prefixed per Sage Appendix item 1"
        )


class TestMemoryTypePrefixesContract:
    """Innovation: _MEMORY_TYPE_PREFIXES tuple is locked verbatim.

    Cites Sage §D8 "claude_memory.py — LOCKED" + v1
    src/bonfire/front_door/scanners/claude_memory.py:33
    (``_MEMORY_TYPE_PREFIXES = ("feedback", "project", "reference", "session", "user")``).
    """

    def test_memory_type_prefixes_tuple_is_stable(self) -> None:
        """_MEMORY_TYPE_PREFIXES is the exact 5-tuple (ordering matters for dict iteration)."""
        from bonfire.onboard.scanners.claude_memory import _MEMORY_TYPE_PREFIXES

        # Ordering and membership both load-bearing — the floor's per-prefix
        # tests don't assert ordering, but Sage §D8 locks the tuple verbatim.
        assert _MEMORY_TYPE_PREFIXES == (
            "feedback",
            "project",
            "reference",
            "session",
            "user",
        ), (
            "_MEMORY_TYPE_PREFIXES must equal the v1 verbatim 5-tuple per "
            "Sage §D8 lock — ordering is load-bearing"
        )
