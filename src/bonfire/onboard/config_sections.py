# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""TOML section builders for ``bonfire.toml`` generation.

Pure-functional leaf layer extracted from :mod:`bonfire.onboard.config_generator`.
Each ``_build_*`` helper turns a slice of scan results (or the conversation
profile) into a TOML section string plus a source-annotation mapping. The
shared helpers (:func:`_collect_by_panel`, :func:`_find_scan_value`,
:func:`_format_toml_list`) and the operator-local tools-sentinel builder live
here too.

These functions are leaves: they never call ``generate_config`` /
``write_config`` and never import from ``config_generator``. The parent module
re-exports every name below so existing callers and tests keep importing them
from ``bonfire.onboard.config_generator``.
"""

from __future__ import annotations

import logging
import re

from bonfire.onboard.protocol import ScanUpdate
from bonfire.persona._toml_writer import escape_basic_string

logger = logging.getLogger(__name__)

# Whitelist regex for tool labels permitted into the operator-local
# sentinel line. ``cli_toolchain.scan`` emits identifier-shaped lowercase
# names (``git``, ``python3``, ``node``). Anything outside the shape is
# dropped at the sentinel-build site so a hostile or malformed label
# cannot smuggle data through the comma-separated single-line wire
# format — defense-in-depth even though the current emission source is
# hard-coded.
_TOOLS_LABEL_WHITELIST = re.compile(r"^[a-z][a-z0-9_-]{0,32}$")


# ---------------------------------------------------------------------------
# Operator-local tools sentinel (W8.G)
# ---------------------------------------------------------------------------
#
# ``generate_config`` does not know the project_path on disk; the only
# string handed to ``write_config`` is ``config_toml``. To plumb the
# ``cli_toolchain`` scan data through without leaking it into the
# project-portable TOML, a single TOML comment line carries the tool
# names from generator to writer. The format is intentionally narrow
# (one line, fixed prefix, comma-separated names) so a regex extract
# is total and unambiguous. The sentinel is stripped from the on-disk
# bonfire.toml before write.

_TOOLS_SENTINEL_PREFIX = "# bonfire-tools-local-v1 detected="


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
    quoted = ", ".join(f'"{escape_basic_string(item)}"' for item in items)
    return f"[{quoted}]"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_header(project_name: str) -> tuple[str, dict[str, str]]:
    """Build [bonfire] header section."""
    lines = [
        "[bonfire]",
        "# Project identity",
        f'name = "{escape_basic_string(project_name)}"',
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
        lines.append(f'{key} = "{escape_basic_string(value)}"')
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
        lines.append(f'primary_language = "{escape_basic_string(lang)}"')
        annotations["project.primary_language"] = "Scan: project_structure"

    framework = _find_scan_value(scans, "framework")
    if framework:
        lines.append(f'framework = "{escape_basic_string(framework)}"')
        annotations["project.framework"] = "Scan: project_structure"

    test_fw = _find_scan_value(scans, "test_framework")
    if test_fw:
        lines.append(f'test_framework = "{escape_basic_string(test_fw)}"')
        annotations["project.test_framework"] = "Scan: project_structure"

    return "\n".join(lines), annotations


def _build_tools(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """No-op for the project-portable TOML (W8.G).

    The ``cli_toolchain`` panel is per-machine state (operator's installed
    CLI tools + versions). Stamping it into ``bonfire.toml`` would:

    * leak the operator's tool inventory + version footprint into a
      git-tracked file, AND
    * make ``bonfire scan`` non-portable — two machines produce two
      byte-different ``bonfire.toml`` files.

    The data is plumbed via :func:`_build_tools_sentinel` into a
    sentinel comment that :func:`write_config` extracts and writes to
    ``.bonfire/tools.local.toml``. This function returns ``None``
    unconditionally so ``generate_config`` skips the section entirely
    for the project-portable TOML. The signature is preserved so the
    no-leak canary in ``test_tools_section_is_local.py`` can call it
    directly and confirm no tool data ever surfaces in the main TOML.
    """
    return None


def _build_tools_sentinel(scans: list[ScanUpdate]) -> str | None:
    """Build the operator-local tools sentinel comment line.

    Returns ``None`` when ``scans`` is empty (no ``cli_toolchain``
    events → no sibling file to seed). Otherwise returns a single
    TOML comment line of the form::

        # bonfire-tools-local-v1 detected=git,python3,node

    The line is appended to ``config_toml`` so :func:`write_config`
    can extract the tool list and materialise
    ``.bonfire/tools.local.toml`` without changing the
    ``write_config`` two-argument signature the Knight contract pins.

    Tool names are restricted to the labels emitted by
    ``cli_toolchain.scan`` (lowercase identifier-shaped names like
    ``git``, ``python3``). Defense-in-depth: each label is matched
    against :data:`_TOOLS_LABEL_WHITELIST` before joining. Labels that
    fail the whitelist (embedded comma/CR/LF, leading punctuation,
    upper-case sneak-ins, anything past 33 chars) are dropped with a
    log warning so a hostile or malformed scan event cannot smuggle
    extra lines through the single-line wire format.
    """
    if not scans:
        return None
    cleaned: list[str] = []
    for s in scans:
        # ``strip`` first so trailing whitespace doesn't break the
        # whitelist match. The whitelist itself enforces no embedded
        # commas / control chars; we don't pre-clean those because a
        # label that contains them is malformed and should be dropped,
        # not silently sanitised into something the wire format accepts.
        name = s.label.strip()
        if not _TOOLS_LABEL_WHITELIST.match(name):
            logger.warning("skipping malformed tool label: %r", s.label)
            continue
        cleaned.append(name)
    if not cleaned:
        return None
    return _TOOLS_SENTINEL_PREFIX + ",".join(cleaned)


# Non-remote labels the git_state scanner emits inside the ``git_state``
# panel. Anything else with a non-error value is treated as a remote-shaped
# event (the scanner uses the remote NAME — ``origin``, ``upstream`` — as
# the label and the sanitised URL as the value).
_GIT_NON_REMOTE_LABELS: frozenset[str] = frozenset(
    {
        "repository",
        "branch",
        "branches",
        "working tree",
        "last commit",
        "remotes",  # bulk-command error event name from _run_with_emit
    }
)


def _pick_git_remote(scans: list[ScanUpdate]) -> str | None:
    """Return the URL of the preferred git remote, or None.

    The git_state scanner emits one event per remote with
    ``label=<remote_name>`` and ``value=<sanitised-url>``. Prefer
    ``origin``; otherwise return the URL of the first remote-shaped event
    in scan order. Error events (``value == "error"``) are skipped — a
    failed git-remote call must not become a TOML remote value.
    """
    remote_scans = [
        s for s in scans if s.label not in _GIT_NON_REMOTE_LABELS and s.value != "error"
    ]
    if not remote_scans:
        return None
    for s in remote_scans:
        if s.label == "origin":
            return s.value
    return remote_scans[0].value


def _build_git(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.git] from git_state scan events.

    The git_state scanner emits remote events with the remote NAME as the
    label (``origin``, ``upstream``) and the sanitised URL as the value;
    the writer here promotes the preferred remote (origin > first) to a
    single ``remote = "..."`` line.
    """
    if not scans:
        return None

    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.git]",
        "# Derived from scan: git_state panel",
    ]

    remote = _pick_git_remote(scans)
    if remote:
        lines.append(f'remote = "{escape_basic_string(remote)}"')
        annotations["git.remote"] = "Scan: git_state"

    branch = _find_scan_value(scans, "branch")
    if branch:
        lines.append(f'branch = "{escape_basic_string(branch)}"')
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


def _sanitize_toml_comment(text: str) -> str:
    """Strip characters that would break a single-line TOML comment.

    TOML 1.0 rejects every byte in U+0000-U+001F and U+007F inside a
    comment, with tab (U+0009) the sole exception. A hostile scanner
    detail (e.g. a top-level key from ``~/.claude/settings.json``
    containing a NUL or DEL byte) would otherwise flow through here into
    the comment line and crash ``tomllib.loads`` at config round-trip.

    Newlines / carriage returns are folded to a single space first so a
    hostile detail can't smuggle a fake table header by inserting a
    line break. Every remaining U+0000-U+001F byte (except tab, which
    TOML allows) and U+007F is dropped. The result is safe to append
    after a leading ``# `` on its own line.
    """
    # Step 1: fold line breaks to spaces so the comment stays single-line
    # (and a hostile detail can't smuggle a synthetic table header).
    folded = text.replace("\r", " ").replace("\n", " ")
    # Step 2: drop the rest of the TOML-rejected control range. Tab
    # (U+0009) is the only whitespace control char TOML allows inside a
    # comment; preserve it. \r and \n were already handled above.
    return "".join(ch for ch in folded if ch == "\t" or (ord(ch) >= 0x20 and ord(ch) != 0x7F))


def _build_claude_memory(
    scans: list[ScanUpdate],
) -> tuple[str, dict[str, str]] | None:
    """Build [bonfire.claude_memory] from claude_memory scan events.

    The scanner emits redaction sentinels (``model="set"``,
    ``permissions="3 keys"``, ``extensions="3 enabled"``) — strings that
    describe *presence/structure*, never literal values (see
    ``scanners/claude_memory.py`` privacy posture). Stamping those as TOML
    string values produces unreadable noise that LOOKS like real config.

    The writer here surfaces sentinel labels as TOML **comments** inside
    the section, so the section keeps its diagnostic value (the operator
    sees that Claude Code was detected) without claiming real values.
    Real numeric data (memory-type counts) is preserved as actual TOML
    values.
    """
    if not scans:
        return None

    annotations: dict[str, str] = {}
    lines = [
        "",
        "[bonfire.claude_memory]",
        "# Derived from scan: claude_memory panel",
    ]

    # Sentinel labels: emit as comments rather than quoted values.
    # ``model``, ``permissions``, ``extensions`` are all redaction sentinels
    # per the scanner's privacy posture — never stamp them as values.
    sentinel_labels = ("model", "permissions", "extensions")
    for label in sentinel_labels:
        value = _find_scan_value(scans, label)
        if value:
            # Find the originating scan to read the optional ``detail``
            # so the comment surfaces structural metadata when present.
            detail = ""
            for s in scans:
                if s.label == label:
                    detail = s.detail
                    break
            note = f"{label}: {value}" if not detail else f"{label}: {value} ({detail})"
            lines.append(f"# {_sanitize_toml_comment(note)}")
            annotations[f"claude_memory.{label}"] = "Scan: claude_memory"

    # Memory counts by type — REAL numeric data, keep as TOML values.
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
