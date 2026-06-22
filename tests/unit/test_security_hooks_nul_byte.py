"""RED contract tests — NUL-byte strip in security_hooks ``_normalize``.

Closes Mirror Probe N+1 finding **S1.5** — the NUL-byte bypass.

The defect:

``_normalize`` (NFKC + ``$IFS`` + backslash-newline rewrite) does NOT strip
``\\x00`` or other ASCII control bytes. The C1.1 deny pattern's separator
class is ``\\s+`` which does NOT match ``\\x00``. So a command like
``rm\\x00-rf /`` passes every C1-C7 deny rule and is silently allowed,
defeating the entire dangerous-rm guard.

The contract this file pins:

1. ``_normalize`` removes ``\\x00`` outright (and ideally every U+0000–U+001F
   ASCII control byte *except* ``\\t``, ``\\n``, ``\\r``).
2. End-to-end via the pre-exec hook: a tool-use call with a NUL-byte-bearing
   ``rm`` command is DENIED, not silently allowed.
3. Control bytes embedded in the MIDDLE of a token (``r\\x00m -rf /``) must
   ALSO be denied — the strip happens before the deny match.

This file follows the style of ``test_security_hooks_normalize.py``: a flat
async ``_run`` helper, a ``_is_deny`` shape check, and class-grouped cases.
"""

from __future__ import annotations

from typing import Any

import pytest


def _is_deny(result: dict[str, Any]) -> bool:
    try:
        return (
            result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
            and result["hookSpecificOutput"]["permissionDecision"] == "deny"
        )
    except (KeyError, TypeError):
        return False


async def _run(cmd: str) -> dict[str, Any]:
    from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

    hook = build_preexec_hook(SecurityHooksConfig())
    return await hook(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}},
        "tu1",
        {"signal": None},
    )


# ---------------------------------------------------------------------------
# _normalize unit contract — strip happens
# ---------------------------------------------------------------------------


class TestNormalizeStripsControlBytes:
    """``_normalize`` MUST drop ASCII control bytes (\\x00–\\x1f) except
    \\t / \\n / \\r. Direct-unit assertion, no hook plumbing."""

    def test_normalize_strips_nul_between_tokens(self) -> None:
        from bonfire.dispatch.security_hooks import _normalize

        out = _normalize("rm\x00-rf /")
        assert "\x00" not in out
        # The token boundary that NUL stood in for must collapse into a form
        # the deny regex can see — either no separator (``rm-rf``) or a
        # whitespace (``rm -rf``). Both satisfy C1.1's ``\\s*`` / boundary
        # surface; assert one of the two.
        assert out.startswith(("rm-rf", "rm -rf"))

    def test_normalize_strips_nul_inside_token(self) -> None:
        from bonfire.dispatch.security_hooks import _normalize

        out = _normalize("r\x00m -rf /")
        assert "\x00" not in out
        # After strip, the two halves of ``rm`` rejoin into a token the deny
        # regex recognizes.
        assert out.startswith("rm")

    def test_normalize_strips_other_control_bytes(self) -> None:
        from bonfire.dispatch.security_hooks import _normalize

        # SOH (\x01), US (\x1f), VT (\x0b), FF (\x0c). \t \n \r preserved.
        out = _normalize("rm\x01\x0b\x0c\x1f-rf /tmp/junk")
        for b in ("\x01", "\x0b", "\x0c", "\x1f"):
            assert b not in out, f"control byte {b!r} survived normalize"


# ---------------------------------------------------------------------------
# Hook end-to-end — DENY decision on NUL-bearing rm
# ---------------------------------------------------------------------------


class TestNulByteBypassDenied:
    """End-to-end via the pre-exec hook: a NUL-byte-bearing ``rm`` MUST be
    denied. This is the actual S1.5 closure assertion."""

    @pytest.mark.asyncio
    async def test_nul_between_command_and_flag_denied(self) -> None:
        # The canonical bypass payload: NUL standing in for the space.
        cmd = "rm\x00-rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_nul_inside_rm_token_denied(self) -> None:
        # NUL in the middle of ``rm`` itself — strip must rejoin then deny.
        cmd = "r\x00m -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_soh_byte_bypass_denied(self) -> None:
        # \x01 — SOH. The C1.1 pattern's ``[a-zA-Z]*`` flag-letter class does
        # not absorb \x01 either; same bypass shape as \x00.
        cmd = "rm\x01-rf /tmp/"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_us_byte_bypass_denied(self) -> None:
        # \x1f — Unit Separator. Final control byte before printable space.
        cmd = "rm\x1f-rf ~/"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Preserved whitespace — strip is targeted, not blanket
# ---------------------------------------------------------------------------


class TestNormalizePreservesWhitespace:
    """``\\t``, ``\\n``, ``\\r`` must SURVIVE normalize — they are legitimate
    shell whitespace. Only the bypass-shaped control bytes (\\x00-\\x08,
    \\x0b-\\x0c, \\x0e-\\x1f) are stripped."""

    def test_normalize_preserves_tab(self) -> None:
        from bonfire.dispatch.security_hooks import _normalize

        out = _normalize("echo\tfoo")
        assert "\t" in out

    def test_normalize_preserves_newline(self) -> None:
        from bonfire.dispatch.security_hooks import _normalize

        out = _normalize("echo foo\necho bar")
        assert "\n" in out
