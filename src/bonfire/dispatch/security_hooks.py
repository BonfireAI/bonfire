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


def _normalize(command: str) -> str:
    """Stage 1: NFKC + expand $IFS + collapse backslash-newline.

    Deliberately NOT doing an shlex round-trip here — shlex chokes on
    partial quotes which is a common agent output; we prefer "best effort
    normalize without raising." Structural unwrap (Stage 2) performs its
    own shlex-based tokenization on the segments where it matters.
    """
    s = unicodedata.normalize("NFKC", command)
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
    """
    sid = session_id or ""
    aname = agent_name or ""
    user_patterns_source = tuple(config.extra_deny_patterns)
    emit = bool(config.emit_denial_events)

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

            # Compile user patterns FIRST — a broken pattern must DENY
            # even for benign commands that would otherwise skip via the
            # keyword prefilter. Failure here lands in the outer except,
            # which is the Sage-mandated _infra.error DENY path.
            user_patterns = _compile_user_patterns(list(user_patterns_source))

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
