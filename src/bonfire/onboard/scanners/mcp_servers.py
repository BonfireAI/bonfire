# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""MCP Server Scanner — Reel 5.

Discovers MCP server declarations from config files across all known
AI clients: Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Zed.

Privacy: NEVER reads ~/.claude.json. NEVER reports env values.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bonfire.onboard.protocol import ScanCallback, ScanUpdate

__all__ = ["scan"]

_PANEL = "mcp_servers"
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known server registry — substring match against command + args joined
# ---------------------------------------------------------------------------

KNOWN_SERVERS: dict[str, str] = {
    "@modelcontextprotocol/server-filesystem": "Filesystem",
    "@modelcontextprotocol/server-github": "GitHub",
    "github-mcp-server": "GitHub (Official)",
    "mcp-server-sqlite": "SQLite",
    "@anthropic/mcp-server-memory": "Memory",
    "linear": "Linear",
    "@modelcontextprotocol/server-brave-search": "Brave Search",
    "@modelcontextprotocol/server-puppeteer": "Puppeteer",
}


# ---------------------------------------------------------------------------
# Client config definitions
# ---------------------------------------------------------------------------


class _ClientConfig:
    """Describes where a client stores MCP server config and how to parse it."""

    __slots__ = ("client_name", "path", "scope", "servers_key")

    def __init__(
        self,
        client_name: str,
        path: Path,
        scope: str,
        servers_key: str = "mcpServers",
    ) -> None:
        self.client_name = client_name
        self.path = path
        self.scope = scope
        self.servers_key = servers_key


def _build_config_sources(project_path: Path, home_dir: Path) -> list[_ClientConfig]:
    """Build the list of config file locations to scan.

    Intentionally EXCLUDES ~/.claude.json (contains OAuth tokens).
    """
    return [
        # Claude Code — project only
        _ClientConfig(
            client_name="Claude Code",
            path=project_path / ".mcp.json",
            scope="project",
        ),
        # Claude Desktop — global only (Linux path)
        _ClientConfig(
            client_name="Claude Desktop",
            path=home_dir / ".config" / "Claude" / "claude_desktop_config.json",
            scope="global",
        ),
        # Cursor — project
        _ClientConfig(
            client_name="Cursor",
            path=project_path / ".cursor" / "mcp.json",
            scope="project",
        ),
        # Cursor — global
        _ClientConfig(
            client_name="Cursor",
            path=home_dir / ".cursor" / "mcp.json",
            scope="global",
        ),
        # VS Code — project (uses "servers" key)
        _ClientConfig(
            client_name="VS Code",
            path=project_path / ".vscode" / "mcp.json",
            scope="project",
            servers_key="servers",
        ),
        # Windsurf — global only
        _ClientConfig(
            client_name="Windsurf",
            path=home_dir / ".codeium" / "windsurf" / "mcp_config.json",
            scope="global",
        ),
        # Zed — global only (uses "context_servers" key)
        _ClientConfig(
            client_name="Zed",
            path=home_dir / ".config" / "zed" / "settings.json",
            scope="global",
            servers_key="context_servers",
        ),
        # Cline — global only
        _ClientConfig(
            client_name="Cline",
            path=(
                home_dir
                / ".config"
                / "Code"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
                / "settings"
                / "cline_mcp_settings.json"
            ),
            scope="global",
        ),
    ]


# ---------------------------------------------------------------------------
# Server name resolution
# ---------------------------------------------------------------------------


def _resolve_server_name(key: str, server_config: dict) -> str:
    """Resolve a human-readable server name from the known registry.

    Matches by substring against: the config key itself, and the joined
    command + args string. Returns the known friendly name, or the raw
    config key if no match is found.
    """
    command = server_config.get("command", "")
    args = server_config.get("args", [])
    if not isinstance(args, list):
        args = []
    search_string = " ".join([key, command, *[str(a) for a in args]])

    for pattern, friendly_name in KNOWN_SERVERS.items():
        if pattern in search_string:
            return friendly_name

    return key


# ---------------------------------------------------------------------------
# Config file parsing
# ---------------------------------------------------------------------------


def _read_servers_from_config(config: _ClientConfig) -> list[tuple[str, dict]]:
    """Read and parse servers from a single config file.

    Returns list of (server_key, server_config_dict) tuples.
    Returns empty list on missing file, malformed JSON, or missing key.
    """
    if not config.path.is_file():
        return []

    try:
        raw = config.path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        _log.debug("Skipping %s: %s", config.path, exc)
        return []

    if not isinstance(data, dict):
        return []

    servers = data.get(config.servers_key)
    if not isinstance(servers, dict):
        return []

    return list(servers.items())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def scan(
    project_path: Path,
    emit: ScanCallback,
    *,
    home_dir: Path | None = None,
) -> int:
    """Scan MCP server configs across AI clients.

    Args:
        project_path: Root of the project to scan.
        emit: Async callback receiving ``ScanUpdate`` events.
        home_dir: Override for the user home directory (for testing).

    Returns:
        Number of servers discovered.
    """
    if home_dir is None:
        home_dir = Path.home()

    configs = _build_config_sources(project_path, home_dir)
    count = 0

    for config in configs:
        servers = _read_servers_from_config(config)
        for key, server_data in servers:
            if not isinstance(server_data, dict):
                continue
            label = _resolve_server_name(key, server_data)
            detail = config.scope
            env = server_data.get("env")
            if isinstance(env, dict) and env:
                env_keys = ", ".join(sorted(env.keys()))
                detail = f"{config.scope}; requires: {env_keys}"
            event = ScanUpdate(
                panel=_PANEL,
                label=label,
                value=config.client_name,
                detail=detail,
            )
            await emit(event)
            count += 1

    return count
