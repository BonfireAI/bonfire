# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Config generator — bonfire.toml from scan results + conversation profile.

Builds a well-formatted TOML string from collected scan events and the
conversation profile dict. Each config value is annotated with its source
(scan panel or conversation question).
"""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire._safe_write import safe_write_text
from bonfire.onboard.protocol import ConfigGenerated, ScanUpdate
from bonfire.persona._toml_writer import escape_basic_string

if TYPE_CHECKING:
    pass

__all__ = ["generate_config", "write_config"]


# ---------------------------------------------------------------------------
# init->scan composability predicate
# ---------------------------------------------------------------------------
#
# ``bonfire init`` writes exactly ``b"[bonfire]\n"`` to ``bonfire.toml``
# (see ``bonfire.cli.commands.init``). The prior overwrite-guard
# refuses to overwrite ANY existing ``bonfire.toml`` — including that
# stub — which breaks the README quickstart ``bonfire init . && bonfire
# scan``. This shared predicate lets the writer and the scan-CLI
# fail-fast both treat that exact stub (and only that stub) as
# "absent". Any user customization — one added key, a comment,
# anything past the section header — falls back into the overwrite
# guard and is preserved.
#
# Symlinks and non-regular files always return False here; the broader
# O_NOFOLLOW write-defense story is handled separately and this
# predicate must not widen the attack surface. The 64-byte size cap
# is defense-in-depth: a stub is 10 bytes, so an oversize file is
# never slurped to check stub-ness.

INIT_STUB_BYTES = b"[bonfire]\n"
_MAX_STUB_BYTES = 64

# Narrow widening (W8.F): also recognize the exact byte shape that
# ``bonfire persona set <name>`` emits when run immediately after
# ``bonfire init`` — ``[bonfire]\npersona = "<basic-string>"`` — as
# still-a-stub, so the documented ``init && persona set && scan`` flow
# composes. The pattern is anchored via ``fullmatch`` against the
# trailing-whitespace-stripped bytes; the TOML basic-string body
# permits any byte except an unescaped ``"`` or ``\`` plus ``\X``
# escapes. The widening is persona-key-SPECIFIC by design: a hand-added
# ``name = "..."`` key (or any other single key) must still fall into
# the overwrite refusal per the W7.M / PR #103 defense. See
# ``tests/unit/test_init_persona_scan_composability.py`` for the upper
# bound (4 GREEN canaries pinning narrowness).
_PERSONA_STUB_RE = re.compile(
    rb'\[bonfire\]\npersona = "(?:[^"\\]|\\.)*"',
)


def _is_init_stub(path: Path) -> bool:
    """Return True iff ``path`` is the exact byte-for-byte stub from ``init``.

    Tolerates only trailing ASCII whitespace (spaces, tabs, CR, LF) so a
    Windows checkout or an editor that appends a final newline still
    reads as a stub. Anything else — a leading comment, an added key,
    a second section — is treated as a user customization and the
    overwrite guard takes over.

    Symlinks, non-regular files, and files larger than 64 bytes are
    refused without raising. The size gate fires BEFORE any
    ``read_bytes`` call so adversarial inputs are never slurped.
    """
    # Symlinks: never a stub. The symlink-write defense is handled
    # separately; this predicate must not widen the overwrite path
    # through a symlink. ``is_symlink`` reads metadata without
    # following, and returns True for dangling symlinks too — so this
    # also covers the "broken target" case.
    if path.is_symlink():
        return False

    try:
        st = path.stat()
    except OSError:
        return False

    if not stat.S_ISREG(st.st_mode):
        return False

    # Size gate FIRST — must short-circuit BEFORE read_bytes so an
    # adversarial 1 MiB file starting with ``[bonfire]\n`` is never
    # whole-file slurped to check stub-ness.
    if st.st_size > _MAX_STUB_BYTES:
        return False

    try:
        raw = path.read_bytes()
    except OSError:
        return False

    stripped = raw.rstrip(b" \t\r\n")
    if stripped == INIT_STUB_BYTES.rstrip(b" \t\r\n"):
        return True
    # Narrow widening (W8.F): accept the exact ``persona set`` output
    # shape ``[bonfire]\npersona = "<basic-string>"`` (anchored via
    # ``fullmatch``) as still-a-stub so ``init && persona set && scan``
    # composes. Anything else — a second key, a second section, a
    # different key name — falls back into the overwrite guard.
    return _PERSONA_STUB_RE.fullmatch(stripped) is not None


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
    """Write bonfire.toml to ``project_path``. Return the written path.

    Refuses to overwrite an existing ``bonfire.toml`` — a user who runs
    ``bonfire scan`` against a directory with a hand-tuned config must not
    silently lose that work. Mirrors the existing guard in
    ``bonfire.cli.commands.init`` (where the file is only written when it
    does not already exist).

    The one exception is the exact byte-for-byte stub that ``bonfire init``
    writes (``b"[bonfire]\\n"``). That stub carries no user content, so
    overwriting it composes the README quickstart (``bonfire init .``
    then ``bonfire scan``) without forcing the user to delete the stub by
    hand. The ``_is_init_stub`` predicate is the shared source of truth —
    the CLI fail-fast in ``scan.py`` consults it too, so the two paths
    cannot drift. The stub-overwrite path unlinks the stub before the
    ``os.open(O_EXCL)`` call below, since ``O_EXCL`` would otherwise
    refuse to create over the existing file.

    Symlinks (dangling, live, or looping) are refused BEFORE the
    ``exists()`` check, because ``Path.exists()`` follows symlinks and
    would otherwise let a dangling symlink slip through to the writer —
    which would then open the symlink TARGET in write+truncate mode and
    yield an arbitrary-write primitive. The actual write uses
    ``os.open(..., O_CREAT | O_EXCL | O_NOFOLLOW)`` as defense-in-depth so
    a TOCTOU race between the ``is_symlink()`` check and the write cannot
    bypass the refusal.

    Raises
    ------
    FileExistsError
        If ``project_path / "bonfire.toml"`` already exists AND it is
        not the exact init stub, OR if it is a symlink. The message
        names the path and tells the user how to recover. The symlink
        branch's message contains the literal substring ``"symlink"``
        so log-grep can distinguish symlink refusal from regular
        collision. No ``--force`` flag in v0.1.
    """
    target = project_path / "bonfire.toml"
    # The symlink + overwrite refusal is delegated to ``safe_write_text``,
    # which centralises the W7.M two-layer defense (is_symlink() pre-check
    # + O_NOFOLLOW + O_EXCL) across all of v0.1's operator-controlled
    # write sites. See :mod:`bonfire._safe_write` for the full contract.
    #
    # The only piece kept here is the init-stub overwrite carve-out
    # (so the README quickstart ``init && scan`` composes): when the
    # existing file is the byte-for-byte init stub we unlink it before
    # invoking ``safe_write_text``, which then takes the fresh-create
    # path (``allow_existing=False`` / O_EXCL). The collision-message
    # contract — ``FileExistsError`` mentioning the path ``bonfire.toml``
    # for regular-file collisions, and the literal substring ``symlink``
    # for symlinked collisions — is preserved by the helper because the
    # path passed in always contains the ``bonfire.toml`` segment.
    if target.is_symlink():
        # Stay on the dedicated symlink branch so the message text and
        # log-grep contract from W7.M (``bonfire.toml at {target} is a
        # symlink. Refusing to follow or overwrite...``) is preserved
        # verbatim — downstream operators may grep on this exact prefix.
        msg = (
            f"bonfire.toml at {target} is a symlink. Refusing to follow or "
            "overwrite a symlinked config. Remove the symlink and re-run."
        )
        raise FileExistsError(msg)
    if target.exists():
        if _is_init_stub(target):
            # The byte-for-byte stub from ``bonfire init`` is overwritable.
            # ``O_EXCL`` inside ``safe_write_text`` refuses any existing
            # file, so the stub must be unlinked here first.
            target.unlink()
        else:
            msg = (
                f"bonfire.toml already exists at {target}. Refusing to "
                "overwrite. Remove or move the existing file and re-run."
            )
            raise FileExistsError(msg)
    # ``safe_write_text`` defaults to ``allow_existing=False`` (O_EXCL)
    # + always-O_NOFOLLOW + half-written-file cleanup, matching the
    # W7.M inline implementation. The helper raises FileExistsError on
    # TOCTOU symlink/regular-file races between the pre-checks above
    # and the open(2); its message includes the literal "symlink" for
    # the symlink-race branch.
    safe_write_text(target, config_toml)
    return target
