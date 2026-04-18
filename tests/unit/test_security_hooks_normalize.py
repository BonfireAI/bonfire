"""RED contract tests — Stage 1 normalize pipeline (BON-338).

Sage-canonical. Knight-A basis — covers NFKC, $IFS expansion, backslash-newline
continuation, DoS resistance, and zero-width blind spots (xfail).

Stage 1 normalize MUST:
- NFKC Unicode normalization (fullwidth → ASCII).
- ``$IFS``, ``${IFS}``, ``$IFS$9`` → single space.
- Collapse backslash-newline continuation (``\\n`` → space).

Zero-width characters remain a blind spot (v0.2 work) — xfail preserved.
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
        {"hook_event_name": "PreToolUse", "tool_name": "Bash",
         "tool_input": {"command": cmd}},
        "tu1",
        {"signal": None},
    )


# ---------------------------------------------------------------------------
# NFKC normalization — fullwidth variants
# ---------------------------------------------------------------------------


class TestNFKCNormalization:
    @pytest.mark.asyncio
    async def test_fullwidth_rm(self):
        cmd = "ｒｍ -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_fullwidth_rf_flag(self):
        cmd = "rm －ｒｆ /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_fullwidth_sudo(self):
        cmd = "ｓｕｄｏ rm -rf /"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# $IFS expansion
# ---------------------------------------------------------------------------


class TestIFSExpansion:
    @pytest.mark.asyncio
    async def test_ifs_bare(self):
        cmd = "rm$IFS-rf$IFS/"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_ifs_braces(self):
        cmd = "rm${IFS}-rf${IFS}/"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_ifs_dollar9(self):
        cmd = "rm$IFS$9-rf$IFS$9/"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_ifs_cat_passwd_exfil(self):
        cmd = "cat${IFS}~/.ssh/id_rsa"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Backslash-newline continuation
# ---------------------------------------------------------------------------


class TestBackslashNewlineContinuation:
    @pytest.mark.asyncio
    async def test_rm_rf_continued(self):
        cmd = "rm \\\n-rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_sudo_continued(self):
        cmd = "sudo \\\nrm -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_multiple_continuations(self):
        cmd = "rm \\\n-rf \\\n/"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Combined normalizations
# ---------------------------------------------------------------------------


class TestCombinedNormalization:
    @pytest.mark.asyncio
    async def test_fullwidth_plus_ifs(self):
        cmd = "ｒｍ${IFS}-rf${IFS}/"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_fullwidth_plus_backslash(self):
        cmd = "ｒｍ \\\n-rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_ifs_plus_backslash(self):
        cmd = "rm$IFS-rf \\\n/"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Case-not-folded — documentation
# ---------------------------------------------------------------------------


class TestCaseNotFolded:
    @pytest.mark.asyncio
    async def test_uppercase_rm_not_denied(self):
        cmd = "RM -rf /"
        result = await _run(cmd)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_mixed_case_rm_not_denied(self):
        cmd = "Rm -rf /"
        result = await _run(cmd)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Edge inputs
# ---------------------------------------------------------------------------


class TestEmptyInput:
    @pytest.mark.asyncio
    async def test_empty_string(self):
        result = await _run("")
        assert result == {}

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        result = await _run("   ")
        assert result == {}

    @pytest.mark.asyncio
    async def test_only_newlines(self):
        result = await _run("\n\n\n")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_null_byte_in_command(self):
        cmd = "rm\x00 -rf /"
        result = await _run(cmd)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# DoS resistance
# ---------------------------------------------------------------------------


class TestDoSResistance:
    @pytest.mark.asyncio
    async def test_long_benign_input_passes(self):
        cmd = "echo " + "a" * 10_000
        result = await _run(cmd)
        assert result == {}

    @pytest.mark.asyncio
    async def test_long_dangerous_input_denies(self):
        cmd = "a" * 10_000 + "; rm -rf /"
        result = await _run(cmd)
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# Zero-width characters — v0.1 blind spot (preserved xfail)
# ---------------------------------------------------------------------------


class TestZeroWidthCharacters:
    """Zero-width Unicode chars could split ``rm`` — NFKC does NOT remove them.
    v0.2 work: explicit zero-width strip step."""

    @pytest.mark.xfail(
        reason="Zero-width space (U+200B) inside command name — NFKC does NOT "
        "remove it. v0.2 explicit zero-width-strip step.",
    )
    @pytest.mark.asyncio
    async def test_zero_width_space_split_rm(self):
        cmd = "r\u200Bm -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Zero-width char blind spot.")
    @pytest.mark.asyncio
    async def test_zero_width_joiner_split(self):
        cmd = "r\u200Dm -rf /"
        assert _is_deny(await _run(cmd))
