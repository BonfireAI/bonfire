"""RED contract for MCP servers scanner safety rails.

Subject: ``bonfire.onboard.scanners.mcp_servers._read_servers_from_config``
synchronously ``read_text()`` s home-dir configs with no size cap and
no symlink protection. A 50 MB Zed settings file blocks the event loop
while parsing JSON; a symlink to ``/dev/zero`` hangs forever.

This file pins down three contracts:

  1. **Size cap**: a config file larger than the configured maximum is
     skipped with a WARNING naming the path and size. The default cap
     is 1 MiB; the env var ``BONFIRE_MCP_SCAN_MAX_BYTES`` overrides.
  2. **Symlink policy**: a symlink whose resolved target lives under
     the configured ``home_dir`` or ``project_path`` is followed; a
     symlink resolving OUTSIDE those roots is skipped with a WARNING.
     This policy is what we pin (the alternative — refuse all symlinks
     unconditionally — would break real-world dotfile management).
  3. **Async-safe read**: the disk read goes through
     ``asyncio.to_thread`` (or an equivalent executor offload) so a slow
     read does not block the event loop. We assert by patching
     ``asyncio.to_thread`` and observing the call.

Tests must NOT plant symlinks to ``/dev/zero`` or any pathological
device — they must complete deterministically on every host.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# Reuse the scanner-level update type for assertion shape.
from bonfire.onboard.protocol import ScanUpdate


def _make_emit_recorder() -> tuple[AsyncMock, list[ScanUpdate]]:
    """Return an ``AsyncMock`` emit + the list its calls write into."""
    events: list[ScanUpdate] = []

    async def _emit(event: ScanUpdate) -> None:
        events.append(event)

    mock = AsyncMock(side_effect=_emit)
    return mock, events


def _plant_zed_config(home_dir: Path, payload: bytes | str) -> Path:
    """Plant a Zed settings.json under *home_dir* with arbitrary *payload*.

    Returns the resulting path. The scanner's
    ``_build_config_sources`` already includes
    ``home_dir / ".config" / "zed" / "settings.json"``.
    """
    target = home_dir / ".config" / "zed" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        target.write_bytes(payload)
    else:
        target.write_text(payload)
    return target


# ---------------------------------------------------------------------------
# 1. Size cap
# ---------------------------------------------------------------------------


class TestSizeCap:
    """A config file exceeding the byte cap is skipped + warned."""

    async def test_oversize_config_is_skipped_with_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A 2 MiB Zed settings.json is skipped; no MCP servers emitted from it.

        The default cap is 1 MiB; ``BONFIRE_MCP_SCAN_MAX_BYTES`` lowers
        the threshold so the planted 2 MiB file trips the cap
        deterministically.
        """
        from bonfire.onboard.scanners.mcp_servers import scan

        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()

        # 2 MiB of valid JSON wrapping a context_servers entry. A naive
        # ``read_text`` + ``json.loads`` would happily parse this and
        # emit a server event; the size cap must short-circuit before
        # parse.
        padding = "x" * (2 * 1024 * 1024)
        payload = json.dumps(
            {
                "context_servers": {
                    "would-be-mcp": {
                        "command": "node",
                        "args": [],
                    },
                },
                "_padding": padding,
            }
        )
        target = _plant_zed_config(home_dir, payload)
        assert target.stat().st_size > 1 * 1024 * 1024

        monkeypatch.setenv("BONFIRE_MCP_SCAN_MAX_BYTES", "1048576")
        caplog.set_level(logging.WARNING, logger="bonfire.onboard.scanners.mcp_servers")

        emit, events = _make_emit_recorder()
        count = await scan(project_path, emit, home_dir=home_dir)

        # No event from the oversize file.
        assert not any(e.value == "Zed" for e in events), (
            f"oversize Zed config produced events: {events!r}"
        )
        # Count reflects only the absence of Zed-sourced entries; other
        # configs aren't planted in this test, so we expect zero events.
        assert count == 0
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "scanner must emit at least one WARNING when an oversize "
            f"config is skipped; got: {[r.getMessage() for r in caplog.records]!r}"
        )
        joined = " | ".join(r.getMessage() for r in warning_records)
        assert "Zed" in joined or str(target) in joined or "settings.json" in joined, (
            f"WARNING must name the offending file; got: {joined!r}"
        )


# ---------------------------------------------------------------------------
# 2. Symlink policy
# ---------------------------------------------------------------------------


class TestSymlinkPolicy:
    """Symlinks resolving outside ``home_dir`` / ``project_path`` are refused.

    Policy choice locked here: a config-location symlink is followed
    iff its resolved target lives under one of the two configured
    roots. This catches the ``/dev/zero`` / arbitrary-host-path class
    of risk without breaking dotfile managers that symlink within
    ``home_dir``.
    """

    async def test_symlink_within_home_is_followed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A symlink whose target lives under ``home_dir`` is read normally."""
        from bonfire.onboard.scanners.mcp_servers import scan

        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()

        # Real file lives under ``home_dir`` (allowed).
        real_target = home_dir / "dotfiles" / "zed-settings.json"
        real_target.parent.mkdir(parents=True)
        real_target.write_text(
            json.dumps(
                {
                    "context_servers": {
                        "filesystem": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                        },
                    },
                }
            )
        )

        # The scanner-expected config path is a SYMLINK to that real file.
        config_path = home_dir / ".config" / "zed" / "settings.json"
        config_path.parent.mkdir(parents=True)
        config_path.symlink_to(real_target)

        emit, events = _make_emit_recorder()
        count = await scan(project_path, emit, home_dir=home_dir)

        zed_events = [e for e in events if e.value == "Zed"]
        assert zed_events, (
            f"symlink within home_dir must be followed and produce events; got: {events!r}"
        )
        assert count >= 1

    async def test_symlink_outside_home_is_refused(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A symlink whose target is outside the configured roots is skipped + warned."""
        from bonfire.onboard.scanners.mcp_servers import scan

        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()

        # The real file lives OUTSIDE both configured roots.
        outside = tmp_path / "outside" / "zed-settings.json"
        outside.parent.mkdir(parents=True)
        outside.write_text(
            json.dumps(
                {
                    "context_servers": {
                        "filesystem": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                        },
                    },
                }
            )
        )

        config_path = home_dir / ".config" / "zed" / "settings.json"
        config_path.parent.mkdir(parents=True)
        config_path.symlink_to(outside)

        caplog.set_level(logging.WARNING, logger="bonfire.onboard.scanners.mcp_servers")
        emit, events = _make_emit_recorder()
        await scan(project_path, emit, home_dir=home_dir)

        zed_events = [e for e in events if e.value == "Zed"]
        assert not zed_events, f"symlink outside home_dir must NOT produce events; got: {events!r}"
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "scanner must emit at least one WARNING when refusing an outside-root symlink"
        )


# ---------------------------------------------------------------------------
# 3. Async-safe disk read
# ---------------------------------------------------------------------------


class TestAsyncSafeRead:
    """The disk read is offloaded from the event loop via ``asyncio.to_thread``."""

    async def test_to_thread_called_for_config_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``asyncio.to_thread`` (or equivalent) is invoked when reading a real config.

        Patches ``asyncio.to_thread`` in the scanner module's
        namespace and counts the calls. The Warrior can satisfy this
        either by ``asyncio.to_thread(...)`` directly or by importing
        + using it from a different binding — patching the module-level
        attribute on ``asyncio`` covers both cases.
        """
        from bonfire.onboard.scanners import mcp_servers as scanner_mod

        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()

        _plant_zed_config(
            home_dir,
            json.dumps(
                {
                    "context_servers": {
                        "filesystem": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                        },
                    },
                }
            ),
        )

        original_to_thread = asyncio.to_thread
        call_counter = {"n": 0}

        async def _counting_to_thread(func, *args, **kwargs):
            call_counter["n"] += 1
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _counting_to_thread)

        emit, _events = _make_emit_recorder()
        await scanner_mod.scan(project_path, emit, home_dir=home_dir)

        assert call_counter["n"] >= 1, (
            "scanner must offload disk reads via asyncio.to_thread; "
            f"observed {call_counter['n']} calls"
        )
