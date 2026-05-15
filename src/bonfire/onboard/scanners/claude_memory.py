# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Claude Memory Scanner — Reel 3.

Detects Claude Code installation, reads settings, counts memory files
by type, parses MEMORY.md index, and detects CLAUDE.md — all without
leaking file content.

Scanner interface::

    async def scan(project_path: Path, emit: ScanCallback, *, home_dir: Path | None = None) -> int

PRIVACY RULES:
- NEVER read ~/.claude.json (contains OAuth tokens)
- Read MEMORY.md index entries (name + description) but NOT memory file bodies
- Report counts and topics, never content
- Settings: report structure, not values of env vars
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ScanCallback, ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["scan"]

PANEL = "claude_memory"

# Memory file type prefixes — files are named like feedback_xxx.md, project_yyy.md, etc.
_MEMORY_TYPE_PREFIXES = ("feedback", "project", "reference", "session", "user")


async def scan(
    project_path: Path,
    emit: ScanCallback,
    *,
    home_dir: Path | None = None,
) -> int:
    """Scan Claude Code config and memory. Return item count.

    Parameters
    ----------
    project_path:
        The project directory being scanned.
    emit:
        Async callback to emit each ``ScanUpdate``.
    home_dir:
        Override for ``Path.home()`` — used in tests with ``tmp_path``.
    """
    from pathlib import Path as _Path

    home = home_dir or _Path.home()
    claude_dir = home / ".claude"

    if not claude_dir.is_dir():
        return 0

    count = 0

    # 1. Claude Code installed
    await emit(ScanUpdate(panel=PANEL, label="Claude Code", value="installed"))
    count += 1

    # 2. Settings
    count += await _scan_settings(claude_dir, emit)

    # 3. Memory directory — files by type
    mem_dir = _resolve_memory_dir(home, project_path)
    if mem_dir is not None and mem_dir.is_dir():
        count += await _scan_memory_files(mem_dir, emit)
        count += await _scan_memory_index(mem_dir, emit)

    # 4. CLAUDE.md in project root
    count += await _scan_claude_md(project_path, emit)

    return count


async def _scan_settings(claude_dir: Path, emit: ScanCallback) -> int:
    """Read settings.json and report structural metadata for model, permissions, extensions.

    Per the module's privacy posture ("Settings: report structure, not values"):
    ``model`` and ``permissions`` are emitted as *presence/structure* signals
    only — the literal values never appear in any event field. This mirrors
    the existing ``extensions`` handling, which only emits a count.

    The persisted output (``bonfire.toml [bonfire.claude_memory]`` via
    ``config_generator._build_claude_memory``) and the WS broadcast both
    consume the ``value`` / ``detail`` fields; a leak in either is durable.
    Claude Code's ``permissions`` block can carry deny-list rules and ``env``
    values today, and may grow auth-bearing fields in future — emitting the
    raw value or its ``str(dict)`` repr would commit those into config.
    """
    settings_path = claude_dir / "settings.json"
    if not settings_path.is_file():
        return 0

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    count = 0

    # Model override — emit presence/structure, NOT the value. The literal
    # model identifier can itself carry token-like segments for custom
    # endpoints; presence is the only safe signal.
    if "model" in data:
        await emit(ScanUpdate(panel=PANEL, label="model", value="set"))
        count += 1

    # Permissions — emit structural metadata (top-level key names + count),
    # NOT the nested values. The deny-list bodies and any env values stay
    # out of the event entirely.
    if "permissions" in data:
        permissions = data.get("permissions")
        if isinstance(permissions, dict):
            keys = sorted(permissions.keys())
            value = f"{len(keys)} key{'s' if len(keys) != 1 else ''}"
            detail = ", ".join(keys)
        else:
            # Non-dict permissions (legacy string form, etc.): report type only.
            value = type(permissions).__name__
            detail = ""
        await emit(ScanUpdate(panel=PANEL, label="permissions", value=value, detail=detail))
        count += 1

    # Extensions count
    extensions = data.get("extensions")
    if isinstance(extensions, list):
        enabled = sum(1 for ext in extensions if isinstance(ext, dict) and ext.get("enabled"))
        await emit(ScanUpdate(panel=PANEL, label="extensions", value=f"{enabled} enabled"))
        count += 1

    return count


def _resolve_memory_dir(home: Path, project_path: Path) -> Path | None:
    """Resolve the Claude Code memory directory for a project.

    Claude Code encodes project paths as:
    ``~/.claude/projects/-<absolute-path-with-slashes-replaced-by-dashes>/memory/``

    Example: ``/home/user/Projects/bonfire`` ->
    ``~/.claude/projects/-home-user-Projects-bonfire/memory/``
    """
    encoded = str(project_path.resolve()).lstrip("/").replace("/", "-")
    mem_dir = home / ".claude" / "projects" / f"-{encoded}" / "memory"
    if mem_dir.is_dir():
        return mem_dir
    return None


async def _scan_memory_files(mem_dir: Path, emit: ScanCallback) -> int:
    """Count memory files by type prefix and emit one event per type."""
    type_counts: dict[str, int] = {}

    for f in mem_dir.iterdir():
        if not f.is_file() or f.suffix != ".md":
            continue
        # Skip MEMORY.md index — handled separately
        if f.name == "MEMORY.md":
            continue
        for prefix in _MEMORY_TYPE_PREFIXES:
            if f.name.startswith(f"{prefix}_"):
                type_counts[prefix] = type_counts.get(prefix, 0) + 1
                break

    count = 0
    for mem_type in sorted(type_counts):
        await emit(
            ScanUpdate(
                panel=PANEL,
                label=f"{mem_type} memories",
                value=str(type_counts[mem_type]),
            )
        )
        count += 1

    # Emit total count with per-type breakdown
    if type_counts:
        total = sum(type_counts.values())
        breakdown = ", ".join(f"{t}: {type_counts[t]}" for t in sorted(type_counts))
        await emit(
            ScanUpdate(
                panel=PANEL,
                label="Memory files",
                value=str(total),
                detail=breakdown,
            )
        )
        count += 1

    return count


async def _scan_memory_index(mem_dir: Path, emit: ScanCallback) -> int:
    """Parse MEMORY.md and count index entries (lines starting with '- [')."""
    memory_md = mem_dir / "MEMORY.md"
    if not memory_md.is_file():
        return 0

    try:
        text = memory_md.read_text(encoding="utf-8")
    except OSError:
        return 0

    entry_count = sum(1 for line in text.splitlines() if line.startswith("- ["))

    if entry_count > 0:
        await emit(
            ScanUpdate(
                panel=PANEL,
                label="memory topics",
                value=f"{entry_count} topics indexed",
            )
        )
        return 1

    return 0


async def _scan_claude_md(project_path: Path, emit: ScanCallback) -> int:
    """Detect CLAUDE.md and count section headers."""
    claude_md = project_path / "CLAUDE.md"
    if not claude_md.is_file():
        return 0

    try:
        text = claude_md.read_text(encoding="utf-8")
    except OSError:
        return 0

    sections = sum(1 for line in text.splitlines() if line.startswith("#"))

    await emit(
        ScanUpdate(
            panel=PANEL,
            label="CLAUDE.md",
            value="found",
            detail=f"{sections} sections",
        )
    )
    return 1
