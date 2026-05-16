# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""MCP Server Scanner — Reel 5.

Discovers MCP server declarations from config files across all known
AI clients: Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Zed.

Privacy: NEVER reads ~/.claude.json. NEVER reports env values.

Safety rails:

  * Disk reads are offloaded via ``asyncio.to_thread`` so a slow config
    file does not block the event loop.
  * Config files larger than the configured byte cap are skipped with a
    WARNING. Default cap is 1 MiB; override via the
    ``BONFIRE_MCP_SCAN_MAX_BYTES`` env var.
  * Symlinks at config-file paths are followed iff their resolved
    target lives under the project root or the configured home
    directory; otherwise they are skipped with a WARNING.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from bonfire.onboard.protocol import ScanCallback, ScanUpdate

__all__ = ["scan"]

_PANEL = "mcp_servers"
_log = logging.getLogger(__name__)

# Default cap on config-file size in bytes. ``BONFIRE_MCP_SCAN_MAX_BYTES``
# overrides at runtime.
_DEFAULT_MAX_BYTES = 1 * 1024 * 1024  # 1 MiB
_MAX_BYTES_ENV = "BONFIRE_MCP_SCAN_MAX_BYTES"


def _max_bytes() -> int:
    """Resolve the configured size cap from the env var, falling back to the default."""
    raw = os.environ.get(_MAX_BYTES_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        _log.warning(
            "Ignoring invalid %s=%r; using default %d bytes",
            _MAX_BYTES_ENV,
            raw,
            _DEFAULT_MAX_BYTES,
        )
        return _DEFAULT_MAX_BYTES
    if value <= 0:
        return _DEFAULT_MAX_BYTES
    return value


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


def _is_under_root(candidate: Path, root: Path) -> bool:
    """Return ``True`` if *candidate* (resolved) is *root* (resolved) or a subpath."""
    try:
        candidate_resolved = candidate.resolve()
        root_resolved = root.resolve()
    except OSError:
        return False
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def _safe_resolve_config_path(path: Path, *, home_dir: Path, project_path: Path) -> Path | None:
    """Validate *path* against the safe roots and return the path to read.

    Returns the path itself if it is not a symlink. If it IS a symlink,
    returns the resolved target IFF that target lives under
    ``project_path`` (the write-floor). Any other target — including
    targets under ``$HOME`` outside the write-floor — is refused with
    a WARNING.

    The ``home_dir`` parameter is retained so the discovery walk in
    ``_build_config_sources`` can still locate the literal config-file
    paths under ``$HOME`` (those are direct paths, not symlinks). For
    the symlink branch the policy is the tighter write-floor rule:
    a compromised symlink in a discoverable config location must not
    silently widen the scanner's read surface across the home
    directory.
    """
    try:
        is_link = path.is_symlink()
    except OSError:
        return None

    if not is_link:
        return path

    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        _log.warning(
            "MCP config symlink %s could not be resolved (%s); skipping",
            path,
            exc,
        )
        return None

    if _is_under_root(resolved, project_path):
        return resolved

    if _is_under_root(resolved, home_dir):
        _log.warning(
            "MCP config symlink %s resolves under $HOME but outside the "
            "write-floor (%s -> %s); refused. Move the target into the "
            "project directory or read the file directly without a symlink.",
            path,
            path,
            resolved,
        )
        return None

    _log.warning(
        "MCP config symlink %s resolves outside safe roots (%s); skipping",
        path,
        resolved,
    )
    return None


def _read_text_sync(path: Path) -> str:
    """Synchronous text read offloaded onto a worker thread."""
    return path.read_text(encoding="utf-8")


async def _read_servers_from_config(
    config: _ClientConfig,
    *,
    home_dir: Path,
    project_path: Path,
) -> list[tuple[str, dict]]:
    """Read and parse servers from a single config file.

    Returns list of (server_key, server_config_dict) tuples. Returns
    an empty list on missing file, malformed JSON, oversize file,
    outside-root symlink, or missing key. Disk reads are offloaded via
    ``asyncio.to_thread`` so a slow read does not block the event
    loop.
    """
    path = config.path

    # The path may not exist OR may be a broken symlink. ``Path.is_file``
    # follows symlinks, so a dangling symlink reports False here.
    try:
        if not (path.is_symlink() or path.is_file()):
            return []
    except OSError:
        return []

    safe_path = _safe_resolve_config_path(path, home_dir=home_dir, project_path=project_path)
    if safe_path is None:
        return []

    # Size cap — check before reading.
    try:
        size = safe_path.stat().st_size
    except OSError:
        return []
    cap = _max_bytes()
    if size > cap:
        _log.warning(
            "MCP config %s exceeds size cap (%d bytes > %d bytes); skipping",
            safe_path,
            size,
            cap,
        )
        return []

    try:
        raw = await asyncio.to_thread(_read_text_sync, safe_path)
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        _log.debug("Skipping %s: %s", safe_path, exc)
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
        servers = await _read_servers_from_config(
            config, home_dir=home_dir, project_path=project_path
        )
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
