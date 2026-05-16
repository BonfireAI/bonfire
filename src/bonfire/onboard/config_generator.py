# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Config generator — bonfire.toml from scan results + conversation profile.

Builds a well-formatted TOML string from collected scan events and the
conversation profile dict. Each config value is annotated with its source
(scan panel or conversation question).

Operator-local tools split (W8.G)
---------------------------------
``cli_toolchain`` scan results carry per-machine state (the operator's
installed CLI tools + versions) and must NEVER land in the
project-portable ``bonfire.toml``. Instead the data is persisted to a
sibling operator-local file ``.bonfire/tools.local.toml`` that
``bonfire init`` ``.gitignore``'s.

The plumbing between :func:`generate_config` and :func:`write_config` is
a single-line TOML comment sentinel appended to ``config_toml`` with the
format ``# bonfire-tools-local-v1 detected=<comma-list>``. The sentinel
is a valid TOML comment (parses cleanly, surfaces no keys), passes the
no-``[bonfire.tools]``-header check, and is stripped from the on-disk
``bonfire.toml`` by :func:`write_config` before the main TOML is written.
The extracted tool list is materialised to ``.bonfire/tools.local.toml``
as ``[bonfire.tools]\\ndetected = [...]``.

Readers consult :func:`load_tools_config` which ONLY reads the
operator-local file — never ``bonfire.toml`` — so a legacy
``[bonfire.tools]`` section in a pre-migration ``bonfire.toml`` is
silently orphaned (no warning, no mutation, no surprise reads).
"""

from __future__ import annotations

import logging
import re
import stat
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire._safe_write import safe_write_text
from bonfire.onboard.protocol import ConfigGenerated, ScanUpdate
from bonfire.persona._toml_writer import escape_basic_string

if TYPE_CHECKING:
    pass

__all__ = ["generate_config", "load_tools_config", "write_config"]

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
_TOOLS_SENTINEL_RE = re.compile(
    r"^# bonfire-tools-local-v1 detected=(?P<csv>[^\r\n]*)$",
    re.MULTILINE,
)

# Path of the operator-local sibling file relative to ``project_path``.
_TOOLS_LOCAL_RELPATH = Path(".bonfire") / "tools.local.toml"


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
    #
    # ``_build_tools`` returns None unconditionally (W8.G); the
    # operator-local tool inventory is routed via the sentinel comment
    # appended after all real sections below, NOT into the main TOML.
    # The annotation key, when present, is intentionally re-keyed to
    # ``tools_local.detected`` so it never advertises a ``tools.detected``
    # source that the main TOML cannot satisfy.
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

    # Append the operator-local tools sentinel comment, if any
    # cli_toolchain events were collected. ``write_config`` extracts
    # this line, materialises ``.bonfire/tools.local.toml`` from it, and
    # strips it from the on-disk bonfire.toml so the project-portable
    # file stays portable. The sentinel is a valid TOML comment, so
    # tomllib parses ``config_toml`` cleanly with or without it.
    tools_sentinel = _build_tools_sentinel(panels.get("cli_toolchain", []))
    if tools_sentinel is not None:
        config_toml = config_toml + tools_sentinel + "\n"
        # Re-key the source annotation so it advertises the operator-local
        # file rather than a [bonfire.tools] section the main TOML no
        # longer carries.
        all_annotations["tools_local.detected"] = "Scan: cli_toolchain"

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
    # W8.G — split the operator-local tools sentinel out of ``config_toml``
    # BEFORE the main-TOML write. The sentinel (a single comment line)
    # is materialised to ``.bonfire/tools.local.toml``; the main TOML
    # is written with the sentinel stripped so the project-portable
    # file never carries per-machine state. When no sentinel is
    # present (no cli_toolchain events were collected), the helper is
    # a no-op and no sibling file is created — we don't pollute the
    # user's tree with empty noise.
    main_toml, tools_local_body = _split_tools_local(config_toml)

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
    safe_write_text(target, main_toml)

    # Write the operator-local tools sibling AFTER the main TOML
    # lands. Failure here must not orphan a half-written bonfire.toml,
    # so we sequence sibling-after-main. The sibling write uses
    # ``allow_existing=True`` because re-running ``bonfire scan`` on
    # the same project (post init-stub overwrite carve-out) must
    # cleanly refresh the local tool inventory without surfacing a
    # stale-file collision.
    #
    # Deferred (v0.1.1): the unlink + safe_write_text pair is NOT
    # atomic — a crash between the unlink and the create leaves the
    # tools file absent until the next scan. Tracked separately;
    # rollback semantics need design thought before swapping to an
    # ``os.replace``-style sibling-write primitive.
    if tools_local_body is not None:
        local_dir = project_path / ".bonfire"
        local_dir.mkdir(exist_ok=True)
        local_target = local_dir / "tools.local.toml"
        # ``allow_existing=True`` permits in-place refresh on re-scan;
        # the symlink defense and O_NOFOLLOW guard from
        # ``safe_write_text`` still apply.
        if not local_target.is_symlink() and local_target.exists():
            local_target.unlink()
        # mode=0o600: operator-local file carries per-machine state
        # (tool inventory + version fingerprint). Restricting to the
        # owner reduces leakage on multi-user hosts without affecting
        # single-user workflows.
        safe_write_text(local_target, tools_local_body, mode=0o600)

    return target


def _split_tools_local(config_toml: str) -> tuple[str, str | None]:
    """Split ``config_toml`` into (main_toml, tools_local_body).

    Extracts the operator-local tools sentinel line (if present),
    returns the main TOML with the sentinel removed plus the rendered
    body of ``.bonfire/tools.local.toml`` (or ``None`` when no
    sentinel was emitted).

    The sentinel format is fixed by :data:`_TOOLS_SENTINEL_PREFIX` and
    matched by :data:`_TOOLS_SENTINEL_RE` — a single line at the end
    of ``config_toml`` carrying a comma-separated list of tool names.
    Empty / whitespace-only csv values yield no sibling file.
    """
    match = _TOOLS_SENTINEL_RE.search(config_toml)
    if match is None:
        return config_toml, None

    csv_text = match.group("csv").strip()
    # Strip the sentinel line (and any trailing newline that followed
    # it) from the main TOML so the on-disk bonfire.toml never carries
    # a hint of the per-machine data.
    main_toml = (config_toml[: match.start()] + config_toml[match.end() :]).rstrip("\n") + "\n"

    if not csv_text:
        return main_toml, None

    names = [n.strip() for n in csv_text.split(",") if n.strip()]
    if not names:
        return main_toml, None

    body_lines = [
        "# Operator-local tool inventory — do NOT commit.",
        "# Auto-generated by `bonfire scan`; per-machine state.",
        "",
        "[bonfire.tools]",
        f"detected = {_format_toml_list(names)}",
        "",
    ]
    return main_toml, "\n".join(body_lines)


def load_tools_config(project_path: Path) -> dict:
    """Read the operator-local tools table for ``project_path``.

    Returns the parsed ``[bonfire.tools]`` table from
    ``<project_path>/.bonfire/tools.local.toml`` or an empty ``dict``
    when the file is absent / unreadable / malformed.

    This reader is the ONLY supported way to consult the tool
    inventory. It NEVER falls back to ``bonfire.toml`` — a legacy
    pre-migration ``[bonfire.tools]`` section in the main TOML is
    silently orphaned (no warning, no migration, no surprise reads,
    no mutation). See ``test_tools_section_is_local.py`` for the
    full backward-compat contract.

    Parameters
    ----------
    project_path
        The project root containing (optionally) ``.bonfire/tools.local.toml``.

    Returns
    -------
    dict
        The parsed ``[bonfire.tools]`` mapping (e.g.
        ``{"detected": ["git", "python3"]}``) or ``{}`` when no
        operator-local file is present.
    """
    local_path = project_path / _TOOLS_LOCAL_RELPATH
    # Refuse to follow symlinks on READ too — same defect class as the
    # W7.M write-side guards. ``Path.is_file`` and ``Path.open`` both
    # follow symlinks, which means a planted symlink at
    # ``.bonfire/tools.local.toml -> /etc/passwd`` (or any
    # operator-readable file the attacker wants Bonfire to slurp) would
    # leak the target's contents into the reader's return value /
    # downstream consumers. ``is_symlink`` does NOT follow the link, so
    # the check is correct even against dangling targets. The reader
    # short-circuits to ``{}`` so the caller cannot distinguish "symlink
    # planted" from "file absent" — closing the metadata side-channel.
    if local_path.is_symlink():
        logger.warning("tools.local.toml at %s is a symlink; refusing to follow", local_path)
        return {}
    if not local_path.is_file():
        return {}
    try:
        with local_path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError:
        # A read failure (permission, transient I/O) should not crash
        # the caller; treat it as absent. The operator can inspect the
        # file directly to diagnose.
        return {}
    except tomllib.TOMLDecodeError as exc:
        # A malformed operator-local file should not crash the caller;
        # surface a warning so the operator can find and fix it, then
        # treat it as absent.
        logger.warning("tools.local.toml at %s is malformed; ignoring: %s", local_path, exc)
        return {}
    bonfire = data.get("bonfire", {})
    if not isinstance(bonfire, dict):
        return {}
    tools = bonfire.get("tools", {})
    if not isinstance(tools, dict):
        return {}
    return tools
