"""RED contract tests — Scout-2/338 §5 blind-spot corpus (BON-338).

Sage-canonical. Knight-A basis — all 12 documented blind spots preserved as
xfails. Sage ambiguity #4 keeps Cyrillic xfail (C6.6 regex intentionally does
NOT cover Cyrillic; v0.2 integrates a confusables library).

Each blind spot is INTENTIONALLY not caught in v0.1. The xfail markers let
today's run green while documenting the gap so a future Warrior can flip
them once v0.2 tree-sitter-bash / AST detection lands.

Scout-2/338 §5 blind spots:
1. Env-var indirection
2. Command substitution head
3. Base64-encoded eval
4. Function/alias redefinition
5. Multi-line heredoc
6. Unicode lookalikes (Cyrillic — per ambiguity #4)
7. Wildcard path evasion
8. Quote fragmentation
9. IFS brace-expansion
10. Indirect destruction
11. MCP side-channel (scope exclusion)
12. Write-then-execute (scope exclusion)
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
# Blind spot #1 — Env-var indirection
# ---------------------------------------------------------------------------


class TestBlindSpotEnvVarIndirection:
    @pytest.mark.xfail(
        reason="Blind spot #1 (Scout-2/338 §5.1): env-var indirection. "
        "Cannot evaluate variable expansion at rest; v0.2 tree-sitter-bash.",
    )
    @pytest.mark.asyncio
    async def test_env_indirection_3var(self):
        cmd = "X=rm; Y=-rf; Z=/; $X $Y $Z"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #1.")
    @pytest.mark.asyncio
    async def test_env_indirection_concat(self):
        cmd = 'X="rm -rf"; $X /'
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #2 — Command substitution at head
# ---------------------------------------------------------------------------


class TestBlindSpotSubstitutionHead:
    @pytest.mark.xfail(
        reason="Blind spot #2 (Scout-2/338 §5.2): $(echo rm) -rf / — v0.2.",
    )
    @pytest.mark.asyncio
    async def test_substitution_head_echo_rm(self):
        cmd = "$(echo rm) -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #2.")
    @pytest.mark.asyncio
    async def test_substitution_head_printf_hex(self):
        cmd = "`printf 'r\\x6d'` -rf /"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #3 — Base64-encoded eval
# ---------------------------------------------------------------------------


class TestBlindSpotBase64Eval:
    @pytest.mark.xfail(
        reason="Blind spot #3 (Scout-2/338 §5.3): base64 eval. v0.2 entropy detection near `| sh`.",
    )
    @pytest.mark.asyncio
    async def test_base64_pipe_sh(self):
        cmd = "echo cm0gLXJmIC8K | base64 -d | sh"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #3.")
    @pytest.mark.asyncio
    async def test_base64_eval_via_substitution(self):
        cmd = 'eval "$(echo cm0gLXJmIC8K | base64 -d)"'
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #4 — Function / alias redefinition
# ---------------------------------------------------------------------------


class TestBlindSpotFunctionAliasRedefinition:
    @pytest.mark.xfail(
        reason="Blind spot #4 (Scout-2/338 §5.4): C6.7 WARN-only in v0.1.",
    )
    @pytest.mark.asyncio
    async def test_function_cd_redefined_denied(self):
        cmd = 'cd() { rm -rf "$@"; }; cd /'
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #4.")
    @pytest.mark.asyncio
    async def test_alias_ls_redefined_denied(self):
        cmd = "alias ls='rm -rf /'; ls"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #5 — Multi-line heredoc
# ---------------------------------------------------------------------------


class TestBlindSpotHeredoc:
    @pytest.mark.xfail(
        reason="Blind spot #5 (Scout-2/338 §5.5): heredoc body extraction is v0.2.",
    )
    @pytest.mark.asyncio
    async def test_heredoc_bash(self):
        cmd = "bash <<EOF\nrm -rf /\nEOF"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #5.")
    @pytest.mark.asyncio
    async def test_heredoc_sh(self):
        cmd = "sh <<'EOT'\ndd if=/dev/zero of=/dev/sda\nEOT"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #6 — Unicode lookalikes (AMBIGUITY #4)
# ---------------------------------------------------------------------------


class TestBlindSpotUnicodeLookalike:
    """Ambiguity #4: C6.6 regex covers NBSP + zero-widths + fullwidth range.
    NFKC normalize catches fullwidth. Cyrillic lookalikes are DOCUMENTED blind
    spot — scope does NOT widen in v0.1. v0.2 uses a confusables library."""

    @pytest.mark.asyncio
    async def test_fullwidth_rm_caught(self):
        """NFKC: fullwidth ｒｍ → ASCII 'rm'. Must deny."""
        cmd = "ｒｍ -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(
        reason="Blind spot #6 / Ambiguity #4 (Scout-2/338 §5.6): Cyrillic 'r' "
        "(U+0440) is NOT NFKC-equivalent to Latin 'r' (U+0072). C6.6 regex "
        "does NOT widen to Cyrillic in v0.1. v0.2 via confusables library.",
    )
    @pytest.mark.asyncio
    async def test_cyrillic_rm_caught(self):
        cmd = "\u0440m -rf /"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #7 — Wildcard path evasion
# ---------------------------------------------------------------------------


class TestBlindSpotWildcardEvasion:
    @pytest.mark.xfail(
        reason="Blind spot #7 (Scout-2/338 §5.7): C6.5 WARN-only; v0.2 glob expansion.",
    )
    @pytest.mark.asyncio
    async def test_wildcard_cat_passwd(self):
        cmd = "/???/??t /???/p??s??"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #7.")
    @pytest.mark.asyncio
    async def test_wildcard_rm_path(self):
        cmd = "/???/?m -rf /"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #8 — Quote fragmentation
# ---------------------------------------------------------------------------


class TestBlindSpotQuoteFragmentation:
    @pytest.mark.xfail(
        reason="Blind spot #8 (Scout-2/338 §5.8): quote fragmentation. v0.2 shlex-rejoin.",
    )
    @pytest.mark.asyncio
    async def test_quote_fragment_rm(self):
        cmd = 'r"m" -rf /'
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #8.")
    @pytest.mark.asyncio
    async def test_quote_fragment_rm_double(self):
        cmd = "'r''m' -rf /"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #9 — IFS manipulation (partial: $IFS DOES normalize; brace-expansion xfail)
# ---------------------------------------------------------------------------


class TestBlindSpotIFSManipulation:
    @pytest.mark.asyncio
    async def test_ifs_dollar_expansion_normalized(self):
        """Sage D6 _normalize step expands $IFS → space. This DOES catch."""
        cmd = "cat${IFS}~/.ssh/id_rsa"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_ifs_dollar9(self):
        cmd = "cat$IFS$9~/.ssh/id_rsa"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(
        reason="Blind spot #9 (Scout-2/338 §5.9): brace-expansion "
        "{cat,/etc/passwd}. C6.4 is WARN-only in v0.1.",
    )
    @pytest.mark.asyncio
    async def test_brace_expansion(self):
        cmd = "{cat,~/.ssh/id_rsa}"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #10 — Indirect destruction
# ---------------------------------------------------------------------------


class TestBlindSpotIndirectDestruction:
    @pytest.mark.xfail(
        reason="Blind spot #10 (Scout-2/338 §5.10): indirect destruction. "
        "tar --remove-files / rsync --delete are v0.2 explicit rules.",
    )
    @pytest.mark.asyncio
    async def test_tar_remove_files(self):
        cmd = "tar --remove-files -cf out.tar /home/user"
        assert _is_deny(await _run(cmd))

    @pytest.mark.xfail(reason="Blind spot #10.")
    @pytest.mark.asyncio
    async def test_rsync_delete(self):
        cmd = "rsync -a --delete /src/ /dst/"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_git_filter_repo_caught(self):
        """Scout-2/338 C2.9 DOES cover filter-repo — should deny."""
        cmd = "git filter-repo --invert-paths"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Blind spot #11 — MCP side-channel (scope exclusion)
# ---------------------------------------------------------------------------


class TestBlindSpotMCPSideChannel:
    def test_mcp_side_channel_is_documented_out_of_scope(self):
        """Scout-2/338 §5.11 explicit scope exclusion (tombstone)."""
        assert True


# ---------------------------------------------------------------------------
# Blind spot #12 — Write-then-execute (scope exclusion)
# ---------------------------------------------------------------------------


class TestBlindSpotWriteThenExecute:
    def test_write_then_execute_is_documented_out_of_scope(self):
        """Scout-2/338 §5.12 explicit scope exclusion (tombstone)."""
        assert True

    @pytest.mark.xfail(
        reason="Blind spot #12: write-then-execute. v0.2+ file-write content scan.",
    )
    @pytest.mark.asyncio
    async def test_write_shell_script_with_rm_rf(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/home/user/run.sh",
                    "content": "#!/bin/bash\nrm -rf /\n",
                },
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)
