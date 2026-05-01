# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Config generator — bonfire.toml from scan results + conversation profile.

Builds a well-formatted TOML string from collected scan events and the
conversation profile dict. Each config value is annotated with its source
(scan panel or conversation question).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.onboard.protocol import ConfigGenerated, ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["generate_config", "write_config"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_by_panel(
    scan_results: list[ScanUpdate],
) -> dict[str, list[ScanUpdate]]:
    """Group scan results by panel name."""
    panels: dict[str, list[ScanUpdate]] = {}
    for scan in scan_results:
        panels.setdefault(scan.panel, []).append(scan)
    return panels


def _find_scan_value(
    scans: list[ScanUpdate],
    label: str,
) -> str | None:
    """Find first scan with matching label, return its value."""
    for scan in scans:
        if scan.label == label:
            return scan.value
    return None


def _format_toml_list(items: list[str]) -> str:
    """Format a Python list as a TOML inline array of quoted strings."""
    quoted = ", ".join(f'"{item}"' for item in items)
    return f"[{quoted}]"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_header(project_name: str) -> tuple[str, dict[str, str]]:
    """Build [bonfire] header section."""
    lines = [
        "[bonfire]",
        "# Project identity",
        f'name = "{project_name}"',
    ]
    return "\n".join(lines), {}


def _build_persona(
    profile: dict[str, str],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.persona] section from conversation profile."""
    if not profile:
        return None
    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.persona]",
        "# Derived from conversation",
    ]
    for key, value in profile.items():
        lines.append(f'{key} = "{value}"')
        annotations[f"persona.{key}"] = "Conversation"
    return "\n".join(lines), annotations


def _build_project(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.project] from project_structure scan events."""
    if not scans:
        return None

    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.project]",
        "# Derived from scan: project_structure panel",
    ]

    lang = _find_scan_value(scans, "language")
    if lang:
        lines.append(f'primary_language = "{lang}"')
        annotations["project.primary_language"] = "Scan: project_structure"

    framework = _find_scan_value(scans, "framework")
    if framework:
        lines.append(f'framework = "{framework}"')
        annotations["project.framework"] = "Scan: project_structure"

    test_fw = _find_scan_value(scans, "test_framework")
    if test_fw:
        lines.append(f'test_framework = "{test_fw}"')
        annotations["project.test_framework"] = "Scan: project_structure"

    return "\n".join(lines), annotations


def _build_tools(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.tools] from cli_toolchain scan events."""
    if not scans:
        return None

    tool_names = [s.label for s in scans]
    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.tools]",
        "# Derived from scan: cli_toolchain panel",
        f"detected = {_format_toml_list(tool_names)}",
    ]
    annotations["tools.detected"] = "Scan: cli_toolchain"
    return "\n".join(lines), annotations


def _build_git(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.git] from git_state scan events."""
    if not scans:
        return None

    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.git]",
        "# Derived from scan: git_state panel",
    ]

    remote = _find_scan_value(scans, "remote")
    if remote:
        lines.append(f'remote = "{remote}"')
        annotations["git.remote"] = "Scan: git_state"

    branch = _find_scan_value(scans, "branch")
    if branch:
        lines.append(f'branch = "{branch}"')
        annotations["git.branch"] = "Scan: git_state"

    return "\n".join(lines), annotations


def _build_mcp(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.mcp] from mcp_servers scan events."""
    if not scans:
        return None

    server_names = [s.label for s in scans]
    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.mcp]",
        "# Derived from scan: mcp_servers panel",
        f"servers = {_format_toml_list(server_names)}",
    ]
    annotations["mcp.servers"] = "Scan: mcp_servers"
    return "\n".join(lines), annotations


def _build_claude_memory(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.claude_memory] from claude_memory scan events."""
    if not scans:
        return None

    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.claude_memory]",
        "# Derived from scan: claude_memory panel",
    ]

    model = _find_scan_value(scans, "model")
    if model:
        lines.append(f'model = "{model}"')
        annotations["claude_memory.model"] = "Scan: claude_memory"

    permissions = _find_scan_value(scans, "permissions")
    if permissions:
        lines.append(f'permissions = "{permissions}"')
        annotations["claude_memory.permissions"] = "Scan: claude_memory"

    extensions = _find_scan_value(scans, "extensions")
    if extensions:
        lines.append(f'extensions = "{extensions}"')
        annotations["claude_memory.extensions"] = "Scan: claude_memory"

    # Memory counts by type
    memory_types = [s for s in scans if s.label.endswith(" memories")]
    for mem_scan in memory_types:
        key = mem_scan.label.replace(" memories", "_memories")
        lines.append(f"{key} = {mem_scan.value}")
        annotations[f"claude_memory.{key}"] = "Scan: claude_memory"

    return "\n".join(lines), annotations


def _build_vault(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.vault] from vault_seed scan events."""
    if not scans:
        return None

    doc_names = [s.label for s in scans]
    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.vault]",
        "# Derived from scan: vault_seed panel",
        f"seed_documents = {_format_toml_list(doc_names)}",
    ]
    annotations["vault.seed_documents"] = "Scan: vault_seed"
    return "\n".join(lines), annotations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_config(
    scan_results: list[ScanUpdate],
    profile: dict[str, str],
    project_name: str = "",
) -> ConfigGenerated:
    """Generate bonfire.toml content from scan results and conversation profile.

    Returns ConfigGenerated with:
    - config_toml: the TOML string
    - annotations: dict mapping config keys to their source
      (e.g., "persona.companion_mode" -> "Conversation")
    """
    panels = _collect_by_panel(scan_results)
    all_annotations: dict[str, str] = {}
    sections: list[str] = []

    # Header is always present
    header_text, _ = _build_header(project_name)
    sections.append(header_text)

    # Persona — from conversation profile
    persona_result = _build_persona(profile)
    if persona_result:
        text, anns = persona_result
        sections.append(text)
        all_annotations.update(anns)

    # Project — from project_structure panel
    project_result = _build_project(panels.get("project_structure", []))
    if project_result:
        text, anns = project_result
        sections.append(text)
        all_annotations.update(anns)

    # Tools — from cli_toolchain panel
    tools_result = _build_tools(panels.get("cli_toolchain", []))
    if tools_result:
        text, anns = tools_result
        sections.append(text)
        all_annotations.update(anns)

    # Git — from git_state panel
    git_result = _build_git(panels.get("git_state", []))
    if git_result:
        text, anns = git_result
        sections.append(text)
        all_annotations.update(anns)

    # Claude Memory — from claude_memory panel
    claude_memory_result = _build_claude_memory(panels.get("claude_memory", []))
    if claude_memory_result:
        text, anns = claude_memory_result
        sections.append(text)
        all_annotations.update(anns)

    # MCP — from mcp_servers panel
    mcp_result = _build_mcp(panels.get("mcp_servers", []))
    if mcp_result:
        text, anns = mcp_result
        sections.append(text)
        all_annotations.update(anns)

    # Vault — from vault_seed panel
    vault_result = _build_vault(panels.get("vault_seed", []))
    if vault_result:
        text, anns = vault_result
        sections.append(text)
        all_annotations.update(anns)

    config_toml = "\n".join(sections) + "\n"

    return ConfigGenerated(
        config_toml=config_toml,
        annotations=all_annotations,
    )


def write_config(config_toml: str, project_path: Path) -> Path:
    """Write bonfire.toml to project root. Returns the written path."""
    target = project_path / "bonfire.toml"
    target.write_text(config_toml)
    return target
