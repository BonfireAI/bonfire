"""RED tests for bonfire.onboard.scanners.mcp_servers — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 23 tests per Sage §D6 Row 7. Verbatim v1 port. No innovations (conservative lens).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_events(emit: AsyncMock) -> list[ScanUpdate]:
    """Extract all ScanUpdate objects passed to the emit callback."""
    return [call.args[0] for call in emit.call_args_list]


def _find_events(
    events: list[ScanUpdate],
    *,
    label: str | None = None,
    value: str | None = None,
) -> list[ScanUpdate]:
    """Find events matching optional label and/or value filters."""
    result = events
    if label is not None:
        result = [e for e in result if e.label == label]
    if value is not None:
        result = [e for e in result if e.value == value]
    return result


# ---------------------------------------------------------------------------
# Claude Code — project-level .mcp.json
# ---------------------------------------------------------------------------


async def test_discovers_project_mcp_json(tmp_path: Path):
    """Discovers servers from project-level .mcp.json (Claude Code)."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "linear": {"command": "npx", "args": ["linear"]},
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.panel == "mcp_servers"
    assert event.label == "Linear"  # matched known registry
    assert event.value == "Claude Code"
    assert event.detail == "project"


# ---------------------------------------------------------------------------
# Claude Desktop — global config
# ---------------------------------------------------------------------------


async def test_discovers_claude_desktop_global(tmp_path: Path):
    """Discovers servers from Claude Desktop global config."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    config_dir = home / ".config" / "Claude"
    config_dir.mkdir(parents=True)
    (config_dir / "claude_desktop_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "@modelcontextprotocol/server-filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.panel == "mcp_servers"
    assert event.label == "Filesystem"  # known registry match
    assert event.value == "Claude Desktop"
    assert event.detail == "global"


# ---------------------------------------------------------------------------
# Cursor — project + global
# ---------------------------------------------------------------------------


async def test_discovers_cursor_project_config(tmp_path: Path):
    """Discovers servers from Cursor project-level config."""
    project = tmp_path / "project"
    project.mkdir()
    cursor_dir = project / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "@modelcontextprotocol/server-github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "GitHub"
    assert event.value == "Cursor"
    assert event.detail == "project"


async def test_discovers_cursor_global_config(tmp_path: Path):
    """Discovers servers from Cursor global config (~/.cursor/mcp.json)."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    cursor_global = home / ".cursor"
    cursor_global.mkdir()
    (cursor_global / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mcp-server-sqlite": {
                        "command": "uvx",
                        "args": ["mcp-server-sqlite"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "SQLite"
    assert event.value == "Cursor"
    assert event.detail == "global"


# ---------------------------------------------------------------------------
# VS Code — uses "servers" key, not "mcpServers"
# ---------------------------------------------------------------------------


async def test_vscode_uses_servers_key(tmp_path: Path):
    """VS Code config uses 'servers' key, not 'mcpServers'."""
    project = tmp_path / "project"
    project.mkdir()
    vscode_dir = project / ".vscode"
    vscode_dir.mkdir()
    (vscode_dir / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "@anthropic/mcp-server-memory": {
                        "command": "npx",
                        "args": ["-y", "@anthropic/mcp-server-memory"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "Memory"
    assert event.value == "VS Code"
    assert event.detail == "project"


# ---------------------------------------------------------------------------
# Windsurf — global only
# ---------------------------------------------------------------------------


async def test_discovers_windsurf_global(tmp_path: Path):
    """Discovers servers from Windsurf global config."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    windsurf_dir = home / ".codeium" / "windsurf"
    windsurf_dir.mkdir(parents=True)
    (windsurf_dir / "mcp_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "@modelcontextprotocol/server-brave-search": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "Brave Search"
    assert event.value == "Windsurf"
    assert event.detail == "global"


# ---------------------------------------------------------------------------
# Zed — uses "context_servers" key
# ---------------------------------------------------------------------------


async def test_zed_uses_context_servers_key(tmp_path: Path):
    """Zed config uses 'context_servers' key inside settings.json."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    zed_dir = home / ".config" / "zed"
    zed_dir.mkdir(parents=True)
    (zed_dir / "settings.json").write_text(
        json.dumps(
            {
                "context_servers": {
                    "@modelcontextprotocol/server-puppeteer": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
                    },
                },
                "other_stuff": "ignored",
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "Puppeteer"
    assert event.value == "Zed"
    assert event.detail == "global"


# ---------------------------------------------------------------------------
# Known server registry matching
# ---------------------------------------------------------------------------


async def test_known_server_registry_match_by_substring(tmp_path: Path):
    """Known server names are matched by substring in command+args."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "my-github-tool": {
                        "command": "npx",
                        "args": ["-y", "github-mcp-server"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    # Matched "github-mcp-server" substring in args
    assert event.label == "GitHub (Official)"


async def test_unknown_server_reports_key_name(tmp_path: Path):
    """Servers not in the known registry report their config key as label."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "my-custom-server": {
                        "command": "/usr/local/bin/my-custom-server",
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "my-custom-server"


# ---------------------------------------------------------------------------
# Env key reporting
# ---------------------------------------------------------------------------


async def test_server_with_env_reports_key_names(tmp_path: Path):
    """Server with env dict reports key names in detail field."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "my-server": {
                        "command": "npx",
                        "args": ["my-server"],
                        "env": {
                            "GITHUB_TOKEN": "ghp_secret123",
                            "API_KEY": "sk-secret456",
                        },
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    assert "requires:" in event.detail
    assert "API_KEY" in event.detail
    assert "GITHUB_TOKEN" in event.detail


async def test_server_env_values_never_included(tmp_path: Path):
    """Env VALUES must never appear in the detail field — only key names."""
    project = tmp_path / "project"
    project.mkdir()
    secret_value = "ghp_supersecrettoken12345"
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "my-server": {
                        "command": "npx",
                        "args": ["my-server"],
                        "env": {
                            "GITHUB_TOKEN": secret_value,
                        },
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    await scan(project, emit, home_dir=tmp_path / "home")

    event = _collect_events(emit)[0]
    assert secret_value not in event.detail
    assert "GITHUB_TOKEN" in event.detail


async def test_server_without_env_has_scope_only_detail(tmp_path: Path):
    """Server without env dict has only scope in detail."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "my-server": {
                        "command": "npx",
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    await scan(project, emit, home_dir=tmp_path / "home")

    event = _collect_events(emit)[0]
    assert event.detail == "project"


# ---------------------------------------------------------------------------
# Missing / malformed config
# ---------------------------------------------------------------------------


async def test_missing_config_files_skip_silently(tmp_path: Path):
    """When no config files exist, scanner returns 0 and emits nothing."""
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 0
    emit.assert_not_called()


async def test_malformed_json_skipped_silently(tmp_path: Path):
    """Malformed JSON config files are skipped without crashing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text("{this is not valid json!!!")

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 0
    emit.assert_not_called()


# ---------------------------------------------------------------------------
# Privacy: NEVER access ~/.claude.json
# ---------------------------------------------------------------------------


async def test_never_accesses_claude_json(tmp_path: Path):
    """The scanner MUST never read ~/.claude.json (contains OAuth tokens)."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    # Place a .claude.json in home with MCP servers — it must NOT be read
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "secret-server": {
                        "command": "npx",
                        "args": ["secret-server"],
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 0
    emit.assert_not_called()


# ---------------------------------------------------------------------------
# Panel name constant
# ---------------------------------------------------------------------------


async def test_panel_name_always_mcp_servers(tmp_path: Path):
    """Every emitted event must have panel='mcp_servers'."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    # Create configs for multiple clients
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"server-a": {"command": "a"}}}))
    cursor_dir = project / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"server-b": {"command": "b"}}}))

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    await scan(project, emit, home_dir=home)

    events = _collect_events(emit)
    assert len(events) >= 2
    for event in events:
        assert event.panel == "mcp_servers"


# ---------------------------------------------------------------------------
# Count matches emitted events
# ---------------------------------------------------------------------------


async def test_count_matches_emitted_events(tmp_path: Path):
    """Return value must equal the number of emitted ScanUpdate events."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "server-1": {"command": "cmd1"},
                    "server-2": {"command": "cmd2"},
                }
            }
        )
    )

    config_dir = home / ".config" / "Claude"
    config_dir.mkdir(parents=True)
    (config_dir / "claude_desktop_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "server-3": {"command": "cmd3"},
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    events = _collect_events(emit)
    assert count == len(events)
    assert count == 3


# ---------------------------------------------------------------------------
# Scope identification
# ---------------------------------------------------------------------------


async def test_scope_correctly_identified(tmp_path: Path):
    """Project-level configs → 'project', global configs → 'global'."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    # Project-level: Claude Code
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"proj-server": {"command": "x"}}})
    )

    # Global: Claude Desktop
    config_dir = home / ".config" / "Claude"
    config_dir.mkdir(parents=True)
    (config_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"global-server": {"command": "y"}}})
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    await scan(project, emit, home_dir=home)

    events = _collect_events(emit)
    proj_events = _find_events(events, label="proj-server")
    global_events = _find_events(events, label="global-server")

    assert len(proj_events) == 1
    assert proj_events[0].detail == "project"
    assert len(global_events) == 1
    assert global_events[0].detail == "global"


# ---------------------------------------------------------------------------
# Multiple servers in one config
# ---------------------------------------------------------------------------


async def test_multiple_servers_in_one_config(tmp_path: Path):
    """All servers within a single config file are emitted."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "linear": {"command": "npx", "args": ["linear"]},
                    "@modelcontextprotocol/server-filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    },
                    "custom-tool": {"command": "/usr/bin/custom"},
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 3
    events = _collect_events(emit)
    labels = {e.label for e in events}
    assert "Linear" in labels
    assert "Filesystem" in labels
    assert "custom-tool" in labels


# ---------------------------------------------------------------------------
# Config with empty mcpServers
# ---------------------------------------------------------------------------


async def test_empty_mcp_servers_object(tmp_path: Path):
    """Config with empty mcpServers dict emits nothing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {}}))

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 0
    emit.assert_not_called()


# ---------------------------------------------------------------------------
# Config missing the expected key entirely
# ---------------------------------------------------------------------------


async def test_config_missing_expected_key(tmp_path: Path):
    """Config without the expected servers key emits nothing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps({"someOtherKey": {"foo": "bar"}}))

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 0
    emit.assert_not_called()


# ---------------------------------------------------------------------------
# Known registry: match by key name (not just command+args)
# ---------------------------------------------------------------------------


async def test_known_registry_match_by_key(tmp_path: Path):
    """Known servers can be matched by the config key itself."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "@modelcontextprotocol/server-github": {
                        "command": "some-binary",
                    },
                }
            }
        )
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=tmp_path / "home")

    assert count == 1
    event = _collect_events(emit)[0]
    assert event.label == "GitHub"


# ---------------------------------------------------------------------------
# Cross-client deduplication NOT required (same server, different clients)
# ---------------------------------------------------------------------------


async def test_same_server_different_clients_both_emitted(tmp_path: Path):
    """Same server in two clients produces two events (no dedup)."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    # Claude Code project config
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"linear": {"command": "npx", "args": ["linear"]}}})
    )

    # Cursor project config
    cursor_dir = project / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"linear": {"command": "npx", "args": ["linear"]}}})
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.mcp_servers import scan

    count = await scan(project, emit, home_dir=home)

    assert count == 2
    events = _collect_events(emit)
    clients = {e.value for e in events}
    assert "Claude Code" in clients
    assert "Cursor" in clients
