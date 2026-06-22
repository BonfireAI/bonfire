# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pre-execution security hook for the Bonfire dispatcher.

Public surface (via ``__all__``):
- ``SecurityHooksConfig`` — frozen Pydantic config model.
- ``build_preexec_hook`` — closure factory returning an async hook callable.

Private helpers are also exposed at module level (``_normalize``, ``_unwrap``,
``_extract_command``, ``_build_security_hooks_dict``) so that tests and the
SDK backend can monkeypatch + use them without reaching through internal
names.

Design doctrine:
- Fail CLOSED on any exception inside the hook body. The only exceptions
  that propagate are ``BaseException`` subclasses (``asyncio.CancelledError``
  etc) — caught as ``Exception`` skips those by construction.
- Unwrap depth is hardcoded to 5. Past that, emit ``_infra.unwrap-exhausted``
  and DENY.
- WARN path emits a SecurityDenied event with ``reason="WARN: "+rule.message``
  and returns an ``allow`` envelope (visibility without blocking).
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import unicodedata
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from bonfire.dispatch.security_patterns import (
    DEFAULT_DENY_PATTERNS,
    DEFAULT_WARN_PATTERNS,
)
from bonfire.models.events import SecurityDenied

# claude_agent_sdk's HookMatcher is required for dispatch wiring but the
# tests for this module never touch the SDK. Import with fallback so that
# the module is importable in environments without the SDK.
try:
    from claude_agent_sdk.types import HookMatcher  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — SDK always present in dev/test
    HookMatcher = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bonfire.events.bus import EventBus
    from bonfire.models.envelope import Envelope


__all__ = [
    "SecurityHooksConfig",
    "WRITE_EDIT_SENSITIVE_PATH_DENY",
    "build_preexec_hook",
]


logger = logging.getLogger(__name__)


# Keyword prefilter — if none of these substrings appear in any segment,
# the command is almost certainly safe and we skip the regex pool. Both
# DENY and WARN categories feed into this list.
_PREFILTER_KEYWORDS: tuple[str, ...] = (
    "rm",
    "dd",
    "mkfs",
    "shred",
    "chmod",
    "chown",
    "git",
    "curl",
    "wget",
    "sudo",
    "su",
    "eval",
    "base64",
    "crontab",
    "iptables",
    "ufw",
    "systemctl",
    "apt",
    "shutdown",
    "halt",
    "reboot",
    "poweroff",
    "init",
    "mv",
    ">",
    "nc",
    "scp",
    "rsync",
    "sftp",
    "ncat",
    "find",
    "fd",
    "xargs",
    "visudo",
    "usermod",
    "alias",
    "cat",
    # ``head`` and ``tail`` are reading verbs that leak secrets just as
    # readily as ``cat`` — C4.1/4.2/4.3 alternations match all three, so
    # the prefilter must let them through to the regex pool.
    "head",
    "tail",
    "bash",
    "sh ",
    "zsh",
    "dash",
    "$IFS",
    "${IFS}",
    "fetch",
    "fork",
    ":|:",
    ".env",
    # C6 obfuscation keywords that don't appear in other lists.
    "{",
    "?",
    "*",
    # Continuation escapes.
    "\\",
)


# ---------------------------------------------------------------------------
# Write/Edit sensitive-path deny family
#
# The DEFAULT_DENY_PATTERNS catalogue (C1-C7) is bash-shape: rules require
# tokens like ``\bcat\s+`` or ``>>?\s*`` as prefixes, so a Write/Edit of
# ``~/.ssh/authorized_keys`` or ``/etc/sudoers`` never matched. This family
# closes that gap with a path-prefix matcher gated to ``Write`` / ``Edit``
# tool calls only; Bash continues to flow through the existing regex pool.
#
# Each entry is a literal prefix matched after the ``file_path`` is
# canonicalized (``$HOME`` / ``/home/<user>`` collapsed to a leading ``~``
# tilde-form, leading ``./`` stripped). The list MUST stay small enough that
# auditors can read it in one screen.
# ---------------------------------------------------------------------------


# Path prefixes that are deny-by-default for Write/Edit. Order does not
# matter — first match wins, but the matcher is O(N) over a short list so
# the order is for human readability.
WRITE_EDIT_SENSITIVE_PATH_DENY: tuple[str, ...] = (
    # SSH material
    "~/.ssh/id_",
    "~/.ssh/authorized_keys",
    "~/.ssh/known_hosts",
    # ``~/.ssh/config`` carries Host aliases and ProxyCommand directives —
    # a Write here can hijack ``ssh <host>`` to a different endpoint or
    # inject a command-execution proxy.
    "~/.ssh/config",
    # AWS
    "~/.aws/credentials",
    # GPG
    "~/.gnupg/",
    # Docker
    "~/.docker/config.json",
    # Kubernetes
    "~/.kube/config",
    # netrc
    "~/.netrc",
    # GitHub CLI — ``~/.config/gh/hosts.yml`` carries oauth tokens.
    "~/.config/gh/hosts.yml",
    # npm auth — ``~/.npmrc`` stores the ``_authToken`` for publish + scoped
    # registries.
    "~/.npmrc",
    # PyPI upload — ``~/.pypirc`` carries the token for ``twine upload``.
    "~/.pypirc",
    # Rust registry — ``~/.cargo/credentials`` (legacy plain) and
    # ``~/.cargo/credentials.toml`` (modern) both store cargo publish tokens.
    "~/.cargo/credentials",
    "~/.cargo/credentials.toml",
    # Azure CLI — entire credentials directory is sensitive (tokens,
    # service-principal secrets). Match as a prefix so any file under
    # ``~/.azure/`` is denied.
    "~/.azure/",
    # GCP / gcloud — credentials live under ``~/.config/gcloud/`` on Linux
    # and ``~/.gcloud/`` historically. Match both prefixes.
    "~/.config/gcloud/",
    "~/.gcloud/",
    # git global config — may contain ``[credential]`` helpers or embed an
    # OAuth token in URL rewrites. Treat as deny.
    "~/.gitconfig",
    # XDG location for the global git config — modern git installs read
    # ``~/.config/git/config`` in addition to ``~/.gitconfig`` and the
    # same credential-helper / URL-rewrite vectors apply.
    "~/.config/git/config",
    # Shell-rc persistence vectors. A write or append (``>>``) to any of
    # these establishes session-survival code. Match each rc file exactly
    # so neighboring docs / examples are not caught.
    "~/.bashrc",
    "~/.bash_profile",
    "~/.bash_logout",
    "~/.bash_aliases",
    "~/.profile",
    "~/.zshrc",
    "~/.zprofile",
    "~/.zshenv",
    "~/.zlogin",
    "~/.zlogout",
    "~/.config/fish/config.fish",
    # PowerShell profiles on Windows resolve under either
    # ``~/Documents/PowerShell/`` (PowerShell Core) or
    # ``~/Documents/WindowsPowerShell/`` (legacy). Match the directory
    # prefix so profile.ps1 + Microsoft.PowerShell_profile.ps1 + module
    # auto-loads are all denied.
    "~/Documents/PowerShell/",
    "~/Documents/WindowsPowerShell/",
    # Root home
    "/root/",
    # System state
    "/etc/sudoers",
    "/etc/sudoers.d/",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/gshadow",
    # System cron drop-in directory — a Write into ``/etc/cron.d/`` plants
    # a scheduled command that runs as root.
    "/etc/cron.d/",
    # systemd unit drop-in directory — a Write into
    # ``/etc/systemd/system/`` plants a service the next ``daemon-reload``
    # picks up; standard persistence vector.
    "/etc/systemd/system/",
    # ``/usr/local/bin/`` is the standard local-binary directory on the
    # default ``$PATH`` — a Write here plants an executable that
    # subsequent shell sessions invoke.
    "/usr/local/bin/",
    # ``/etc/ld.so.preload`` injects a shared object into every dynamically
    # linked process at startup — classic LD_PRELOAD persistence vector.
    "/etc/ld.so.preload",
    # /proc/<pid>/cwd and /proc/<pid>/root are kernel symlinks the
    # kernel resolves at ``open()`` time to the target process's cwd
    # / root — Writes through them bypass the home-prefix canonicalizer
    # entirely. The matcher cannot see through the symlink, so any
    # Write/Edit into /proc/<pid>/{cwd,root}/ is refused regardless of
    # the suffix. ``self`` is the alias for the calling process.
    # Matching is done via a literal prefix for the ``self`` form plus
    # a regex for the numeric-pid form — see _match_write_edit_proc_bypass.
    "/proc/self/cwd/",
    "/proc/self/root/",
)


# /proc/<pid>/cwd/ and /proc/<pid>/root/ — numeric-pid variants of the
# symlink-bypass family. The literal ``self`` aliases are handled via the
# prefix list above; the numeric-pid forms need a regex match.
_PROC_NUMERIC_BYPASS_RE = re.compile(r"^/proc/[0-9]+/(?:cwd|root)/")


# Windows UNC: ``\\server\share\<rest>`` — after backslash normalization
# arrives as ``//server/share/<rest>``. The kernel resolves UNC to a remote
# share; if ``<rest>`` matches a credential path on that share
# (``Users/<u>/.ssh/id_rsa``, etc.) the deny floor must still fire.
_WIN_UNC_RE = re.compile(r"^//([^/]+)/([^/]+)(/.*)?$")
# Windows extended-length: ``\\?\C:\<rest>`` → ``//?/C:/<rest>``; the
# ``\\?\`` prefix is a syntactic device that disables Win32 path-length
# limits and silently bypasses prefix-shape matchers that expect
# ``C:/Users/<u>/...``. Extended-length UNC: ``\\?\UNC\server\share\<rest>``
# → ``//?/UNC/server/share/<rest>``.
_WIN_EXTLEN_RE = re.compile(r"^//\?/(?:UNC/)?(.*)$")


def _strip_windows_unc_or_extlen(file_path: str) -> str | None:
    r"""Detect Windows UNC + extended-length shapes and return the underlying
    POSIX-style path for re-canonicalization.

    Returns:
        The stripped/rewritten path (still a string with forward slashes) if
        ``file_path`` matched UNC or extended-length, else ``None``.

    Behavior:
        - Extended-length UNC ``\\?\UNC\server\share\Users\u\.ssh\id_rsa``
          -> ``/Users/u/.ssh/id_rsa`` (drop ``\\?\UNC\server\share``; the
          tail is what the kernel actually opens on the remote share).
        - Extended-length ``\\?\C:\Users\u\.ssh\id_rsa`` ->
          ``C:/Users/u/.ssh/id_rsa`` (drop ``\\?\``; the underlying form is
          a normal drive path that downstream canonicalization handles).
        - UNC ``\\server\share\Users\u\.ssh\id_rsa`` ->
          ``/Users/u/.ssh/id_rsa`` (drop ``\\server\share``; treat the tail
          as a normal POSIX path so the home-prefix collapse fires).

    The double-slash detection is performed BEFORE the multi-slash collapse
    that ``_canonicalize_write_edit_path_with_underflow`` runs - by the time
    that collapse fires the UNC marker is destroyed.
    """
    if "\\" not in file_path and not file_path.startswith("//"):
        return None
    # Normalize backslashes so the regex can be authored in POSIX form.
    s = file_path.replace("\\", "/") if "\\" in file_path else file_path
    # Extended-length first (``\\?\``) — it has a more specific prefix than
    # generic UNC (``\\server``). Both UNC + extended-length-UNC are
    # rewritten so the tail re-enters canonicalization as a clean path.
    m = _WIN_EXTLEN_RE.match(s)
    if m is not None:
        tail = m.group(1)
        # ``\\?\UNC\server\share\<rest>`` lands here with tail
        # ``server/share/<rest>`` — strip the share prefix so ``<rest>``
        # alone is canonicalized. If the input was the non-UNC variant
        # (``\\?\C:\...``) the tail is ``C:/<rest>`` and is left as-is
        # for the normal drive-path canonicalization to consume.
        if s.startswith("//?/UNC/"):
            unc_parts = tail.split("/", 2)
            if len(unc_parts) < 3:
                # Malformed extended-length UNC (no share or no tail) —
                # refuse: nothing meaningful to scan.
                return ""
            return "/" + unc_parts[2]
        return tail
    m = _WIN_UNC_RE.match(s)
    if m is not None:
        tail = m.group(3) or ""
        # ``\\server\share`` with no tail → an empty stripped form.
        # Canonicalization will land on ``""``; the matcher treats that
        # as a non-match (no credential reference) and the original
        # would not reach a credential file anyway.
        return tail
    return None


# Sentinel returned by ``_strip_windows_unc_or_extlen`` for malformed
# UNC/extended-length inputs that should be refused outright.
_MALFORMED_UNC = ""


# Public exported reasons keep the SecurityDenied pattern_id slug stable
# across versions. The slug is internal to this hook (not part of the
# C1-C7 canonical catalogue) and namespaced under ``_infra.`` for the
# same reason ``_infra.control-byte`` / ``_infra.error`` are.
_WRITE_EDIT_SENSITIVE_PATH_PATTERN_ID = "_infra.write-edit-sensitive-path"
_WRITE_EDIT_SENSITIVE_PATH_REASON = (
    "Write/Edit of a credential or system-state path is denied. "
    "If intended, edit the file manually outside the agent dispatch."
)


# Regex that recognizes a ``$HOME/`` or ``/home/<user>/`` (Linux) or
# ``/Users/<user>/`` (macOS) or ``[A-Za-z]:/Users/<user>/`` (Windows, after
# backslash → forward-slash normalization) prefix so we can canonicalize
# file_path to a ``~`` form before the prefix scan. ``/root/`` itself is one
# of the deny prefixes — for ``/root/...`` inputs we keep the literal form
# (the ``/root/`` rule matches it directly).
#
# Cross-platform extension: macOS ``/Users/<u>/`` and Windows
# ``[A-Za-z]:/Users/<u>/`` are first-class home-prefix forms. Windows
# backslash separators are normalized to forward slashes BEFORE this regex
# is applied (see ``_canonicalize_write_edit_path``) so the alternation only
# needs the forward-slash form.
#
# Defense — Probe N+7 C1: the negative lookaheads ``(?!\.\.?/)`` and
# ``(?!\.\.?$)`` refuse the literal ``.`` and ``..`` segments as the
# ``[^/]+`` username slot. Without them, an input like
# ``/home/../etc/sudoers`` had its ``..`` greedily consumed as a valid
# username, the substitution collapsed to ``~/etc/sudoers``, no
# underflow signal fired, and the canonical form matched no deny
# prefix — voiding the ENTIRE WRITE/EDIT deny floor via any
# ``/home/../``, ``/Users/../``, or ``[A-Za-z]:/Users/../`` shape. The
# lookaheads refuse to match on those shapes; dot-segment resolution
# then collapses ``../`` correctly and the matcher's second
# home-prefix pass (see ``_canonicalize_write_edit_path_with_underflow``)
# re-collapses any newly-revealed ``/home/<realuser>/...`` form so the
# credential deny scan still fires.
_HOME_PREFIX_RE = re.compile(
    r"^(?:"
    r"\$HOME"
    r"|/home/(?!\.\.?/)(?!\.\.?$)[^/]+"
    r"|/Users/(?!\.\.?/)(?!\.\.?$)[^/]+"
    r"|[A-Za-z]:/Users/(?!\.\.?/)(?!\.\.?$)[^/]+"
    r")(/|$)"
)


_MULTI_SLASH_RE = re.compile(r"/{2,}")


def _resolve_dot_segments(path: str) -> tuple[str, bool]:
    """Resolve ``.`` and ``..`` segments in ``path``.

    Walks ``path`` segment-wise, dropping ``.`` and popping the predecessor
    on ``..``. The anchor (``~/``, ``/``, or none for relative paths) is
    preserved and acts as a floor — a ``..`` that would pop past the anchor
    is dropped (clamped) and the underflow is reported via the second
    return value. Adversarial inputs like
    ``/home/alice/Documents/../.ssh/id_rsa`` collapse to ``~/.ssh/id_rsa``
    after the home substitution (no underflow), while
    ``/etc/sudoers/../passwd`` collapses to ``/etc/passwd`` (no
    underflow) — both reach the deny-prefix scan in their canonical form.

    Returns ``(canonical_path, underflowed)`` where ``underflowed`` is
    True if any ``..`` segment would have popped past the anchor floor.
    Cross-user escapes like ``/home/alice/../bob/.ssh/id_rsa`` substitute
    to ``~/../bob/.ssh/id_rsa`` and trip the underflow flag — the caller
    must treat underflow as deny because the kernel resolves the original
    path to a different user's home, defeating the alice-anchored deny
    scan.

    Empty segments (from accidental trailing slashes) are also dropped.
    """
    if path.startswith("~/"):
        anchor = "~/"
        tail = path[2:]
    elif path == "~":
        return "~", False
    elif path.startswith("/"):
        anchor = "/"
        tail = path[1:]
    else:
        anchor = ""
        tail = path
    if "/" not in tail and tail not in (".", ".."):
        # Fast path: a single segment that is not itself a dot-segment.
        return anchor + tail, False
    resolved: list[str] = []
    underflowed = False
    for seg in tail.split("/"):
        if seg == "" or seg == ".":
            continue
        if seg == "..":
            if resolved:
                resolved.pop()
            else:
                # ``..`` underflows past the anchor — clamp by dropping
                # but flag the escape so the caller can refuse.
                underflowed = True
            continue
        resolved.append(seg)
    return anchor + "/".join(resolved), underflowed


def _canonicalize_write_edit_path(file_path: str) -> str:
    """Collapse home-equivalent prefixes to ``~`` so the prefix matcher
    is straightforward.

    Order:
        1. Strip leading ``./`` (one round; bash doesn't repeat it).
        2. Normalize Windows backslash separators to forward slashes — both
           raw (``C:\\Users\\alice``) and escaped (``C:\\\\Users\\\\alice``)
           collapse to ``C:/Users/alice``.
        3. Collapse any run of two or more forward slashes to a single
           slash — unconditional so pure-POSIX ``//`` / ``///`` shapes
           don't bypass the prefix scan.
        4. Replace ``$HOME/`` or ``/home/<user>/`` or ``/Users/<user>/`` or
           ``[A-Za-z]:/Users/<user>/`` with ``~/``.
        5. Resolve ``.`` / ``..`` segments in the path tail, clamped at the
           anchor (``~/`` or ``/``) so ``..`` cannot escape past the home
           or filesystem root.

    Backslash normalization MUST happen BEFORE both the regex substitution
    AND the rsplit-on-``/`` tail-segment match (``rsplit("/", 1)``) so a
    Windows path bearing only backslashes does not arrive at the tail match
    as a single segment.

    Slash-collapse MUST run unconditionally (not gated behind a backslash
    check): pure-POSIX inputs like ``/home/alice//.ssh/id_rsa`` would
    otherwise leave a ``//`` artifact that bypasses ``_HOME_PREFIX_RE``'s
    ``[^/]+`` greedy match and silently slip past the deny floor.

    Dot-segment resolution MUST run AFTER the home substitution so the
    ``~/`` anchor (rather than the literal ``/home/<user>/``) is the
    clamp boundary — this keeps adversarial ``../`` traversal inside the
    home prefix scope of the deny matcher. ``..`` segments that would
    escape past the anchor are flagged as underflow; the matcher
    (``_match_write_edit_sensitive_path``) treats underflow as a
    cross-user / cross-root escape attempt and denies. See
    ``_resolve_dot_segments`` for details.

    /root/ is NOT canonicalized — it has its own dedicated deny prefix.

    Returns the canonical path string. Underflow information is lost on
    this return path; callers that need to refuse on underflow must use
    ``_canonicalize_write_edit_path_with_underflow`` instead.
    """
    canonical, _ = _canonicalize_write_edit_path_with_underflow(file_path)
    return canonical


def _canonicalize_write_edit_path_with_underflow(file_path: str) -> tuple[str, bool]:
    """Internal variant that also reports anchor underflow.

    Returns ``(canonical, underflowed)``. ``underflowed`` is True when
    the dot-segment walk would have escaped past the home (or filesystem
    root) anchor — a cross-user / cross-root traversal attempt. The
    matcher uses this to refuse adversarial inputs whose kernel resolution
    would land in a DIFFERENT user's home (e.g.
    ``/home/alice/../bob/.ssh/id_rsa``).
    """
    s = file_path
    if s.startswith("./"):
        s = s[2:]
    # Windows separator normalization — only fires when backslashes are
    # present (no-op on pure-POSIX inputs).
    if "\\" in s:
        s = s.replace("\\", "/")
    # Unconditional slash-collapse: handles BOTH backslash-derived runs
    # (``C:\\\\Users\\\\alice`` → ``C:////Users////alice`` after step 1)
    # AND pure-POSIX adversarial runs (``/home/alice//.ssh/id_rsa``),
    # each of which would otherwise leave ``//`` artifacts that bypass
    # ``_HOME_PREFIX_RE`` and silently slip past the deny floor.
    s = _MULTI_SLASH_RE.sub("/", s)
    s = _HOME_PREFIX_RE.sub(lambda m: "~" + m.group(1), s, count=1)
    s, underflowed = _resolve_dot_segments(s)
    # Second home-prefix pass (Probe N+7 C1): when the first pass refused
    # to collapse a dot-segment username (``/home/../``,
    # ``C:/Users/../Users/<u>/...``, etc.), dot-segment resolution then
    # cleans the ``../`` and may reveal a legitimate
    # ``/home/<realuser>/...`` or ``[A-Za-z]:/Users/<realuser>/...`` form
    # that still belongs under the ``~/`` home anchor. Re-running the
    # collapse here ensures those cleaned-up paths reach the credential
    # deny scan in canonical ``~/...`` form. The pass is a no-op for
    # inputs the first pass already collapsed (``$HOME/`` →  ``~/``,
    # ``/home/alice/`` → ``~/``) because the substituted ``~/`` no
    # longer matches ``_HOME_PREFIX_RE``'s alternation. Underflow state
    # from the first dot-segment walk is preserved — a cross-user
    # ``..`` escape stays flagged regardless of whether the second pass
    # re-anchors the result.
    s = _HOME_PREFIX_RE.sub(lambda m: "~" + m.group(1), s, count=1)
    return s, underflowed


def _is_case_insensitive_fs() -> bool:
    """Return True when the local filesystem is case-insensitive.

    macOS HFS+ / APFS (default) and Windows NTFS resolve ``~/.SSH/id_rsa``
    and ``~/.ssh/id_rsa`` to the same inode. The deny matcher must
    case-fold both sides on those platforms; pure-POSIX Linux stays
    case-sensitive (the correct semantics).
    """
    return sys.platform == "darwin" or sys.platform == "win32"


def _match_write_edit_sensitive_path(file_path: str) -> bool:
    r"""Return True if ``file_path`` resolves under any deny prefix.

    Also covers the ``.env`` family and the ``..`` cross-user / cross-root
    escape family. The matcher runs the following passes:

    1. Numeric-pid /proc symlink-bypass match on the post-backslash-normalize
       form (``/proc/<pid>/cwd/`` or ``/proc/<pid>/root/``). The literal
       ``/proc/self/...`` aliases are in the prefix list below.
    2. Windows UNC + extended-length detection: ``\\server\share\<rest>``
       and ``\\?\<rest>`` bypass the home-prefix collapse because the
       slash-collapse step destroys the leading ``//`` marker. Detect
       these shapes early and re-run the matcher on the stripped tail.
    3. Canonicalize the path. If dot-segment resolution underflowed past the
       anchor (cross-user / cross-root traversal attempt), refuse — the
       kernel resolves the original path to a DIFFERENT user's home or to
       a path outside any deny prefix entirely.
    4. Canonical prefix match against ``WRITE_EDIT_SENSITIVE_PATH_DENY``.
       On case-insensitive filesystems (macOS, Windows) the comparison is
       case-folded; POSIX Linux stays case-sensitive.
    5. Tail-name match against ``.env`` / ``.env.*`` (case-sensitive,
       segment-anchored — ``/path/to/.env`` matches, ``/path/env.txt``
       does not, ``/path/.env_example.txt`` does not). The tail match
       is ALSO case-folded on case-insensitive filesystems.
    """
    if not file_path:
        return False
    # Numeric-pid /proc symlink bypass — the prefix list catches the
    # literal ``self`` aliases; the numeric forms need a regex. Run on a
    # backslash-normalized form so a Windows-shape input bearing
    # ``\\proc\\12345\\cwd\\...`` still matches. Pure-POSIX inputs are
    # unaffected.
    proc_probe = file_path.replace("\\", "/") if "\\" in file_path else file_path
    proc_probe = _MULTI_SLASH_RE.sub("/", proc_probe)
    if _PROC_NUMERIC_BYPASS_RE.match(proc_probe):
        return True
    # Windows UNC + extended-length: detect BEFORE main canonicalization so
    # the slash-collapse does not destroy the ``//`` UNC marker. If the
    # strip helper returns a tail, re-evaluate that tail through the full
    # matcher (one level of recursion — the stripped tail is normal POSIX
    # or drive-letter form and cannot recurse again).
    stripped = _strip_windows_unc_or_extlen(file_path)
    if stripped is not None:
        if stripped == _MALFORMED_UNC:
            # Malformed extended-length UNC (no share or no tail) → refuse.
            return True
        # Recurse on the stripped form. The stripped form starts with ``/``
        # or with a drive letter (``C:/...``) — neither path re-triggers
        # the UNC strip, so recursion is bounded at depth 1.
        return _match_write_edit_sensitive_path(stripped)
    canonical, underflowed = _canonicalize_write_edit_path_with_underflow(file_path)
    if underflowed:
        # Cross-user / cross-root escape attempt — kernel resolves the
        # original path to a target the alice-anchored deny scan can't see.
        # Refuse outright. Fail-CLOSED is the v0.1 contract.
        return True
    case_fold = _is_case_insensitive_fs()
    canonical_cmp = canonical.casefold() if case_fold else canonical
    for prefix in WRITE_EDIT_SENSITIVE_PATH_DENY:
        prefix_cmp = prefix.casefold() if case_fold else prefix
        if canonical_cmp.startswith(prefix_cmp):
            return True
    # Last segment match for .env / .env.* (segment-anchored).
    # Get the final path segment.
    segment = canonical.rsplit("/", 1)[-1]
    segment_cmp = segment.casefold() if case_fold else segment
    if segment_cmp == ".env":
        return True
    if segment_cmp.startswith(".env."):
        # ``.env.example`` is whitelisted because it's documentation, not
        # secrets; everything else under ``.env.<suffix>`` is treated as a
        # real dotenv file.
        if segment_cmp == ".env.example":
            return False
        return True
    return False


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


class SecurityHooksConfig(BaseModel):
    """User-facing policy for the pre-exec security hook.

    The DEFAULT_DENY_PATTERNS floor cannot be softened — users may only
    EXTEND the deny list via ``extra_deny_patterns``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    enabled: bool = True
    extra_deny_patterns: list[str] = Field(default_factory=list)
    emit_denial_events: bool = True


# ---------------------------------------------------------------------------
# Stage 1 — normalize
# ---------------------------------------------------------------------------


# $IFS, ${IFS}, $IFS$9 → space.
_IFS_RE = re.compile(r"\$\{IFS\}|\$IFS\$[0-9]|\$IFS")

# Backslash-newline continuation → space.
_BACKSLASH_NEWLINE_RE = re.compile(r"\\\n")

# ASCII control bytes EXCEPT tab (\x09), newline (\x0a), and carriage return
# (\x0d). Closes the NUL-byte bypass: a payload
# like ``rm\x00-rf /`` sneaks past the C1.1 ``\s+``-separator deny rule
# because ``\s`` does not match ``\x00``. Strip these BEFORE downstream
# matching so the deny regex sees the rejoined token.
_CONTROL_BYTE_CLASS = r"[\x00-\x08\x0b\x0c\x0e-\x1f]"
_CONTROL_BYTE_RE = re.compile(_CONTROL_BYTE_CLASS)
# Control-byte runs sandwiched between two ASCII letters: drop entirely so
# attacker-injected ``r\x00m`` rejoins into ``rm`` and the deny regex sees
# the canonical token. Other control-byte runs collapse to a single space
# so ``rm\x00-rf`` becomes ``rm -rf`` and C1.1's ``\s+`` separator matches.
_CONTROL_BYTE_BETWEEN_LETTERS_RE = re.compile(
    r"(?<=[A-Za-z])" + _CONTROL_BYTE_CLASS + r"+(?=[A-Za-z])"
)
_CONTROL_BYTE_RUN_RE = re.compile(_CONTROL_BYTE_CLASS + r"+")


def _normalize(command: str) -> str:
    """Stage 1: strip bypass control bytes + NFKC + expand $IFS + collapse
    backslash-newline.

    Deliberately NOT doing an shlex round-trip here — shlex chokes on
    partial quotes which is a common agent output; we prefer "best effort
    normalize without raising." Structural unwrap (Stage 2) performs its
    own shlex-based tokenization on the segments where it matters.

    Control-byte handling preserves \\t, \\n, \\r (legitimate shell
    whitespace). Other U+0000–U+001F bytes are removed via two passes:
    first, runs sandwiched between two ASCII letters are dropped so split
    tokens (``r\\x00m``) rejoin into recognizable commands (``rm``); then
    any remaining runs collapse to a single space so injected
    pseudo-separators (``rm\\x00-rf``) yield the canonical ``rm -rf`` shape
    that deny regexes expect.
    """
    s = _CONTROL_BYTE_BETWEEN_LETTERS_RE.sub("", command)
    s = _CONTROL_BYTE_RUN_RE.sub(" ", s)
    s = unicodedata.normalize("NFKC", s)
    s = _BACKSLASH_NEWLINE_RE.sub(" ", s)
    s = _IFS_RE.sub(" ", s)
    return s


# ---------------------------------------------------------------------------
# Stage 2 — structural unwrap
# ---------------------------------------------------------------------------


# Regex-based "peel" patterns. Each rule matches a wrapper prefix + captures
# the inner command body. The functions are tried in registration order and
# the first hit wins per round.


_SUDO_RE = re.compile(r"^sudo(?:\s+-[a-zA-Z]+)*\s+(.+)$", re.DOTALL)
_TIMEOUT_RE = re.compile(r"^timeout(?:\s+--\S+)*(?:\s+\S+)?\s+(.+)$", re.DOTALL)
_NOHUP_RE = re.compile(r"^nohup\s+(.+?)(?:\s*&)?$", re.DOTALL)
_WATCH_RE = re.compile(r"^watch(?:\s+-[a-zA-Z]+)*\s+(.+)$", re.DOTALL)
_ENV_RE = re.compile(r"^env(?:\s+-[a-zA-Z]+)*(?:\s+[A-Za-z_][A-Za-z0-9_]*=\S*)+\s+(.+)$", re.DOTALL)
_XARGS_RE = re.compile(r"^xargs(?:\s+-[a-zA-Z]+\S*)*\s+(.+)$", re.DOTALL)
# find ... -exec <X> ... (+|\;) → <X>
_FIND_EXEC_RE = re.compile(
    r"^(?:find|fd)\s+.*?-exec\s+(.+?)(?:\s+(?:\\;|\+))?\s*$",
    re.DOTALL,
)

_BASH_C_FLAGS = r"(?:\s+-[a-zA-Z]+)*"
_BASH_SH_C_RE = re.compile(
    r"^(?:bash|sh)" + _BASH_C_FLAGS + r"\s+-c" + _BASH_C_FLAGS + r"\s+(['\"])(.+)\1\s*$",
    re.DOTALL,
)


_UNWRAPPER_PREFIXES: tuple[str, ...] = (
    "sudo ",
    "bash ",
    "sh ",
    "timeout ",
    "nohup ",
    "watch ",
    "env ",
    "xargs ",
    "find ",
    "fd ",
)


def _has_unwrapper_prefix(segment: str) -> bool:
    s = segment.lstrip()
    return any(s.startswith(p) for p in _UNWRAPPER_PREFIXES)


def _split_chain(segment: str) -> list[str]:
    """Split on chain operators: ; && || |. Respects quoting best-effort.

    This is NOT a full bash parser — it's a segment splitter. ``|`` inside a
    pipe-to-shell regex (C3.1) still needs to be seen as a single token, so
    we keep each segment intact for the regex pass but ALSO yield the
    left side on its own so segments in isolation are checked.
    """
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    in_single = False
    in_double = False
    n = len(segment)
    while i < n:
        ch = segment[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            # Order matters: check && / || before single & /|.
            if segment.startswith("&&", i):
                parts.append("".join(buf).strip())
                buf = []
                i += 2
                continue
            if segment.startswith("||", i):
                parts.append("".join(buf).strip())
                buf = []
                i += 2
                continue
            if ch == ";":
                parts.append("".join(buf).strip())
                buf = []
                i += 1
                continue
            if ch == "|":
                # Keep the ORIGINAL segment (with the pipe) as ALSO a segment so
                # that curl|sh regex still fires on the full left-plus-pipe.
                # Simplest approach: split here, but ALSO yield the whole
                # segment as a segment. Caller passes the full original as an
                # additional segment already, so here we just split.
                parts.append("".join(buf).strip())
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _extract_substitutions(segment: str) -> list[str]:
    """Return the inner bodies of $(...) and `...` in ``segment``.

    Handles arbitrary nesting by walking character-by-character and
    tracking paren depth.
    """
    out: list[str] = []
    n = len(segment)
    i = 0
    while i < n:
        ch = segment[i]
        # $( … )
        if ch == "$" and i + 1 < n and segment[i + 1] == "(":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                c = segment[j]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        inner = segment[i + 2 : j]
                        out.append(inner)
                        # Recurse into inner for nested subs.
                        out.extend(_extract_substitutions(inner))
                        break
                j += 1
            i = j + 1
            continue
        # `…`
        if ch == "`":
            j = i + 1
            while j < n and segment[j] != "`":
                j += 1
            if j < n:
                inner = segment[i + 1 : j]
                out.append(inner)
                out.extend(_extract_substitutions(inner))
            i = j + 1
            continue
        i += 1
    return out


def _peel_one(segment: str) -> str | None:
    """Try to peel a single unwrapper off ``segment``.

    Returns the inner body, or ``None`` if nothing was peeled.
    """
    s = segment.strip()

    m = _BASH_SH_C_RE.match(s)
    if m is not None:
        return m.group(2)

    if s.startswith("sudo "):
        m = _SUDO_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    if s.startswith("timeout "):
        m = _TIMEOUT_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    if s.startswith("nohup "):
        m = _NOHUP_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    if s.startswith("watch "):
        m = _WATCH_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    if s.startswith("env "):
        m = _ENV_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    if s.startswith("xargs "):
        m = _XARGS_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    if s.startswith("find ") or s.startswith("fd "):
        m = _FIND_EXEC_RE.match(s)
        if m is not None:
            return m.group(1).strip()

    return None


_UNWRAP_EXHAUSTED_SENTINEL = "\x00__BONFIRE_UNWRAP_EXHAUSTED__\x00"


def _unwrap(command: str, *, max_depth: int = 5) -> list[str]:
    """Stage 2: recursively peel wrappers up to ``max_depth`` rounds.

    Returns a list of segments to be matched. The original command is
    always the first entry (so regex rules that care about the full chain
    still see it). Subsequent entries are the peeled bodies, each also
    chain-split.

    If after ``max_depth`` rounds a segment still starts with an
    unwrapper prefix, the sentinel ``_UNWRAP_EXHAUSTED_SENTINEL`` is
    appended to the output. The hook body turns that into a synthetic
    DENY via the ``_infra.unwrap-exhausted`` slug.
    """
    segments: list[str] = [command]

    # Seed with the chain-split of the top-level command too — each split
    # segment gets independently inspected / unwrapped.
    seeds = _split_chain(command)
    if seeds != [command]:
        segments.extend(seeds)

    # Also seed with command-substitution bodies.
    for sub in _extract_substitutions(command):
        segments.append(sub)
        segments.extend(_split_chain(sub))

    work: list[str] = list(segments)
    for depth in range(max_depth):
        next_round: list[str] = []
        for seg in work:
            peeled = _peel_one(seg)
            if peeled is None:
                continue
            next_round.append(peeled)
            # Chain-split + substitution-extract the peeled body too.
            chained = _split_chain(peeled)
            if chained != [peeled]:
                next_round.extend(chained)
            for sub in _extract_substitutions(peeled):
                next_round.append(sub)
                next_round.extend(_split_chain(sub))
        if not next_round:
            break
        segments.extend(next_round)
        work = next_round
    else:
        # Loop exhausted without ``break`` — meaning we still produced new
        # peels at depth == max_depth. If any still has an unwrapper
        # prefix, that's exhaustion.
        for seg in work:
            if _has_unwrapper_prefix(seg):
                segments.append(_UNWRAP_EXHAUSTED_SENTINEL)
                break

    # Dedup while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for seg in segments:
        if seg and seg not in seen:
            seen.add(seg)
            unique.append(seg)
    return unique


# ---------------------------------------------------------------------------
# Stage 3 — prefilter + extract
# ---------------------------------------------------------------------------


def _extract_command(tool_name: str, tool_input: Any) -> str:
    """Extract the string payload to scan for a given tool.

    Bash → ``command``. Write/Edit → ``file_path`` (and optionally
    ``content``, but v0.1 does NOT scan content per Scout-2/338 §5.12).
    """
    if not isinstance(tool_input, dict):
        return ""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
    elif tool_name in ("Write", "Edit"):
        cmd = tool_input.get("file_path", "")
    else:
        return ""
    if isinstance(cmd, bytes):
        try:
            return cmd.decode("utf-8", errors="replace")
        except Exception:
            return ""
    if not isinstance(cmd, str):
        return ""
    return cmd


def _keyword_hit(segments: list[str]) -> bool:
    for seg in segments:
        for kw in _PREFILTER_KEYWORDS:
            if kw in seg:
                return True
    return False


# ---------------------------------------------------------------------------
# Stage 4 — match
# ---------------------------------------------------------------------------


def _compile_user_patterns(patterns: list[str]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compile user-supplied extra_deny_patterns.

    Raises (re-raised in the hook body) on any invalid regex, which the
    outer try/except turns into a DENY + ``_infra.error`` event.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for i, raw in enumerate(patterns):
        compiled.append((f"user.extra.{i}", re.compile(raw)))
    return tuple(compiled)


def _match_deny(
    segment: str,
    *,
    user_patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> tuple[str, str] | None:
    """Return (rule_id, message) for the first matching DENY rule, else None."""
    for rule in DEFAULT_DENY_PATTERNS:
        if rule.pattern.search(segment):
            return rule.rule_id, rule.message
    for rid, pat in user_patterns:
        if pat.search(segment):
            return rid, f"User-defined deny pattern matched: {pat.pattern!r}"
    return None


def _match_warn(segment: str) -> tuple[str, str] | None:
    for rule in DEFAULT_WARN_PATTERNS:
        if rule.pattern.search(segment):
            return rule.rule_id, rule.message
    return None


# ---------------------------------------------------------------------------
# Decision envelopes
# ---------------------------------------------------------------------------


def _deny_envelope(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _allow_envelope(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }


async def _safe_emit(
    bus: EventBus | None,
    event: SecurityDenied,
) -> None:
    """Emit ``event`` on ``bus`` swallowing any exception.

    Bus failures MUST NOT rescue a DENY-worthy command. Exceptions here are
    logged and suppressed; the hook body continues to return its decision.
    """
    if bus is None:
        return
    try:
        await bus.emit(event)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("security_hooks: bus.emit failed; continuing with decision")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_preexec_hook(
    config: SecurityHooksConfig,
    *,
    bus: EventBus | None = None,
    session_id: str | None = None,
    agent_name: str | None = None,
) -> Callable[[dict, str, dict], Awaitable[dict[str, Any]]]:
    """Return a fresh async hook closure bound to ``config`` + bus + ids.

    Each call produces a distinct callable so that concurrent dispatches
    (different agents, different sessions) don't share state.

    User-supplied ``extra_deny_patterns`` are compiled ONCE here at
    factory time: on a long agent dispatch the compile result is stable
    (config is frozen, patterns are captured) so per-call ``re.compile``
    would be wasted work. A broken user pattern is captured as an
    exception and re-raised inside the hook body, where the outer
    try/except turns it into the Sage-mandated DENY + ``_infra.error``
    event — preserving the existing fail-safe contract.
    """
    sid = session_id or ""
    aname = agent_name or ""
    user_patterns_source = tuple(config.extra_deny_patterns)
    emit = bool(config.emit_denial_events)

    # Compile user patterns once at factory time. Defer any compile
    # error to the hook body so it lands in the existing outer-except
    # DENY path (fail-safe semantics preserved).
    _user_patterns_compiled: tuple[tuple[str, re.Pattern[str]], ...] | None
    _user_patterns_error: Exception | None
    try:
        _user_patterns_compiled = _compile_user_patterns(list(user_patterns_source))
        _user_patterns_error = None
    except Exception as exc:  # noqa: BLE001 — surface as DENY in hook body
        _user_patterns_compiled = None
        _user_patterns_error = exc

    async def _hook(
        input_data: dict,
        tool_use_id: str,
        context: dict,
    ) -> dict[str, Any]:
        try:
            if not isinstance(input_data, dict):
                return {}
            if input_data.get("hook_event_name") != "PreToolUse":
                return {}

            tool_name = input_data.get("tool_name", "")
            if tool_name not in ("Bash", "Write", "Edit"):
                return {}

            tool_input = input_data.get("tool_input", {}) or {}
            command = _extract_command(tool_name, tool_input)
            if not command:
                return {}

            # User patterns were compiled at factory time. If any
            # pattern was invalid, raise here so the outer except turns
            # it into the Sage-mandated _infra.error DENY path — this
            # preserves the fail-CLOSED contract even for benign commands
            # that would otherwise skip via the keyword prefilter.
            if _user_patterns_error is not None:
                raise _user_patterns_error
            user_patterns = _user_patterns_compiled
            assert user_patterns is not None  # narrow for type-checker

            # Write/Edit sensitive-path family: gate path-shape inputs that
            # the bash-shape C1-C7 catalogue would never match. Runs BEFORE
            # the prefilter so a benign-looking file_path (no shell keywords)
            # cannot skate past the scan.
            if tool_name in ("Write", "Edit") and _match_write_edit_sensitive_path(command):
                if emit:
                    await _safe_emit(
                        bus,
                        SecurityDenied(
                            session_id=sid,
                            sequence=0,
                            tool_name=tool_name,
                            reason=_WRITE_EDIT_SENSITIVE_PATH_REASON,
                            pattern_id=_WRITE_EDIT_SENSITIVE_PATH_PATTERN_ID,
                            agent_name=aname,
                        ),
                    )
                return _deny_envelope(_WRITE_EDIT_SENSITIVE_PATH_REASON)

            # Pre-strip detection: a Bash command bearing ASCII control bytes
            # (anywhere outside \t / \n / \r) is bypass-shaped. The Stage-1
            # _normalize strip rebuilds the token for downstream matching, but
            # well-crafted payloads can still smuggle through dangerous-path
            # exclusions on the rebuilt form (e.g. ``rm\x01-rf /tmp/`` would
            # otherwise inherit C1.1's ``/tmp/`` exclusion). Treat control-byte
            # presence as its own deny signal for Bash; Write/Edit accept
            # arbitrary file content, so this gate applies only to Bash.
            if tool_name == "Bash" and _CONTROL_BYTE_RE.search(command):
                reason = "ASCII control byte in Bash command — bypass-shaped payload denied."
                if emit:
                    await _safe_emit(
                        bus,
                        SecurityDenied(
                            session_id=sid,
                            sequence=0,
                            tool_name=tool_name,
                            reason=reason,
                            pattern_id="_infra.control-byte",
                            agent_name=aname,
                        ),
                    )
                return _deny_envelope(reason)

            normalized = _normalize(command)

            segments = _unwrap(normalized, max_depth=5)

            # Exhaustion sentinel from _unwrap → DENY.
            if _UNWRAP_EXHAUSTED_SENTINEL in segments:
                reason = (
                    "security-hook-error: unwrap depth exceeded; "
                    "command nesting beyond safe scan depth"
                )
                if emit:
                    await _safe_emit(
                        bus,
                        SecurityDenied(
                            session_id=sid,
                            sequence=0,
                            tool_name=tool_name,
                            reason=reason,
                            pattern_id="_infra.unwrap-exhausted",
                            agent_name=aname,
                        ),
                    )
                return _deny_envelope(reason)

            # Prefilter skips the expensive regex pool unless the command
            # carries a "dangerous-looking" token OR the user supplied
            # extras (we can't keyword-prefilter for arbitrary user
            # patterns).
            if not user_patterns and not _keyword_hit(segments):
                return {}

            # Match DENY first, then WARN.
            for seg in segments:
                deny_hit = _match_deny(seg, user_patterns=user_patterns)
                if deny_hit is not None:
                    rule_id, message = deny_hit
                    if emit:
                        await _safe_emit(
                            bus,
                            SecurityDenied(
                                session_id=sid,
                                sequence=0,
                                tool_name=tool_name,
                                reason=message,
                                pattern_id=rule_id,
                                agent_name=aname,
                            ),
                        )
                    return _deny_envelope(message)

            # No DENY hits — scan for WARN.
            warn_hits: list[tuple[str, str]] = []
            for seg in segments:
                warn_hit = _match_warn(seg)
                if warn_hit is not None:
                    warn_hits.append(warn_hit)

            if warn_hits:
                rule_id, message = warn_hits[0]
                warn_reason = f"WARN: {message}"
                if emit:
                    await _safe_emit(
                        bus,
                        SecurityDenied(
                            session_id=sid,
                            sequence=0,
                            tool_name=tool_name,
                            reason=warn_reason,
                            pattern_id=rule_id,
                            agent_name=aname,
                        ),
                    )
                return _allow_envelope(warn_reason)

            return {}

        except asyncio.CancelledError:
            # CancelledError is a BaseException in Py3.8+ but to be safe on
            # older runtimes we explicitly re-raise.
            raise
        except Exception as exc:
            reason = f"security-hook-error: {exc!r}"
            logger.exception(
                "security_hooks: internal error during PreToolUse evaluation",
            )
            if emit:
                try:
                    await _safe_emit(
                        bus,
                        SecurityDenied(
                            session_id=sid,
                            sequence=0,
                            tool_name=str(input_data.get("tool_name", ""))
                            if isinstance(input_data, dict)
                            else "",
                            reason=reason,
                            pattern_id="_infra.error",
                            agent_name=aname,
                        ),
                    )
                except Exception:
                    logger.exception("security_hooks: failed to emit _infra.error event")
            return _deny_envelope(reason)

    return _hook


# ---------------------------------------------------------------------------
# Wiring helper — builds the ``hooks`` kwarg for ClaudeAgentOptions
# ---------------------------------------------------------------------------


def _build_security_hooks_dict(
    config: SecurityHooksConfig,
    *,
    bus: EventBus | None,
    envelope: Envelope,
) -> dict[str, list[Any]] | None:
    """Build the dict passed as ``ClaudeAgentOptions.hooks=...``.

    Returns ``None`` when the config is disabled — the caller passes the
    None through to the SDK, which treats it as "no hook registered."
    """
    if not config.enabled:
        return None
    if HookMatcher is None:  # pragma: no cover
        raise RuntimeError(
            "claude_agent_sdk.types.HookMatcher is not importable — cannot wire security hooks"
        )
    hook = build_preexec_hook(
        config,
        bus=bus,
        session_id=envelope.envelope_id,
        agent_name=envelope.agent_name,
    )
    return {"PreToolUse": [HookMatcher(matcher="Bash|Write|Edit", hooks=[hook])]}
