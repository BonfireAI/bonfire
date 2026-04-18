"""RED contract tests — structural unwrap pipeline stage 2 (BON-338).

Sage-canonical. Knight-A basis + Sage ambiguity #2 lockdown.

Sage D6 — Scout-2/338 §6.1 Stage 2 — max depth 5 recursive unwrap.

Unwrappers recognized:
- ``sudo X`` → ``X``
- ``bash -c '<X>'`` / ``sh -c "<X>"`` → ``X``
- ``timeout 30 X``, ``nohup X``, ``env FOO=bar X`` → ``X``
- ``xargs -I{} X`` → ``X``
- ``watch X`` → ``X``
- ``find ... -exec X`` → ``X``
- ``X | Y``, ``X && Y``, ``X ; Y`` → each segment matched
- ``$(X)``, backtick ``X`` → X substituted

Ambiguity #2 (Sage-locked): past ``unwrap_max_depth=5``, hook FAILS CLOSED.
Emits SecurityDenied with ``pattern_id="_infra.unwrap-exhausted"`` and
``permissionDecision="deny"``. The xfail markers Knight-A wrote for depth-6+
are FLIPPED to mandatory assertions here.
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


def _deny_reason(result: dict[str, Any]) -> str:
    return str(result["hookSpecificOutput"]["permissionDecisionReason"])


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
# Depth 1 — single unwrapper
# ---------------------------------------------------------------------------


class TestDepth1SingleUnwrap:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cmd",
        [
            "sudo rm -rf /",
            "bash -c 'rm -rf /'",
            'bash -c "rm -rf /"',
            "sh -c 'rm -rf /'",
            "timeout 30 rm -rf /",
            "timeout --preserve-status 10 rm -rf /",
            "nohup rm -rf /",
            "nohup rm -rf / &",
            "env HOME=/tmp rm -rf /",
            "env -i HOME=/ rm -rf /",
            "watch rm -rf /",
        ],
    )
    async def test_single_unwrap_still_denies(self, cmd: str):
        result = await _run(cmd)
        assert _is_deny(result), (
            f"Single-unwrap of {cmd!r} must still hit C1 deny."
        )


# ---------------------------------------------------------------------------
# Depth 2 — two unwrappers combined
# ---------------------------------------------------------------------------


class TestDepth2Combined:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cmd",
        [
            "sudo bash -c 'rm -rf /'",
            "sudo timeout 30 rm -rf /",
            "sudo nohup rm -rf /",
            "bash -c 'sudo rm -rf /'",
            "timeout 30 bash -c 'rm -rf /'",
            "timeout 30 sudo rm -rf /",
            "env FOO=bar sudo rm -rf /",
            "env FOO=bar bash -c 'rm -rf /'",
            "nohup sudo rm -rf /",
        ],
    )
    async def test_depth2_combo_denies(self, cmd: str):
        result = await _run(cmd)
        assert _is_deny(result), f"Depth-2 combo {cmd!r} must deny after unwrap."


# ---------------------------------------------------------------------------
# Depth 3-5 — at the recursion limit
# ---------------------------------------------------------------------------


class TestDepthNearLimit:
    @pytest.mark.asyncio
    async def test_depth3_sudo_bash_timeout(self):
        cmd = "sudo bash -c 'timeout 30 rm -rf /'"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_depth4_sudo_bash_timeout_nohup(self):
        cmd = "sudo bash -c 'timeout 30 nohup rm -rf /'"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_depth5_sudo_bash_timeout_nohup_env(self):
        """At max depth 5, the innermost rm -rf / MUST still match."""
        cmd = "sudo bash -c 'timeout 30 nohup env FOO=bar rm -rf /'"
        assert _is_deny(await _run(cmd)), (
            f"Depth-5 (at the Sage limit): {cmd!r}. "
            "Sage D6 sets unwrap_max_depth=5; this command MUST deny."
        )


# ---------------------------------------------------------------------------
# Depth 6+ — AMBIGUITY #2 Sage-locked: FAIL-CLOSED with _infra.unwrap-exhausted
# ---------------------------------------------------------------------------


class TestDepthExhaustionFailClosed:
    """Sage ambiguity #2 lockdown.

    When the unwrap pipeline still has an unwrapper prefix after
    ``unwrap_max_depth=5`` rounds, the hook MUST emit SecurityDenied with
    ``pattern_id='_infra.unwrap-exhausted'`` and return
    ``permissionDecision='deny'``. This is the fail-closed interpretation of
    depth exhaustion.
    """

    @pytest.mark.asyncio
    async def test_six_sudo_exhausts_and_denies(self):
        """Six layers of sudo → depth-exhaustion → DENY."""
        cmd = "sudo sudo sudo sudo sudo sudo rm -rf /"
        result = await _run(cmd)
        assert _is_deny(result), (
            "Ambiguity #2: past unwrap_max_depth=5 MUST fail closed. "
            f"Got {result!r} for {cmd!r}"
        )

    @pytest.mark.asyncio
    async def test_six_sudo_pattern_id_is_infra_unwrap_exhausted(self):
        """The emitted event carries ``pattern_id='_infra.unwrap-exhausted'``."""
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook
        from bonfire.events.bus import EventBus
        from bonfire.models.events import SecurityDenied

        bus = EventBus()
        captured: list[SecurityDenied] = []

        async def consumer(event: SecurityDenied) -> None:
            captured.append(event)

        bus.subscribe(SecurityDenied, consumer)

        hook = build_preexec_hook(
            SecurityHooksConfig(), bus=bus, session_id="s", agent_name="a",
        )
        cmd = "sudo sudo sudo sudo sudo sudo rm -rf /"
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": cmd}},
            "tu1",
            {"signal": None},
        )
        assert len(captured) == 1
        assert captured[0].pattern_id == "_infra.unwrap-exhausted", (
            "Ambiguity #2: exhaustion event MUST use reserved pattern_id "
            f"'_infra.unwrap-exhausted'. Got {captured[0].pattern_id!r}"
        )

    @pytest.mark.asyncio
    async def test_depth6_nested_unwrappers_denies(self):
        """Knight-A's depth-6 xfail becomes mandatory per ambiguity #2."""
        cmd = (
            "sudo bash -c 'timeout 30 nohup env FOO=bar "
            "xargs -I{} rm -rf /'"
        )
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_depth7_nested_unwrappers_denies(self):
        cmd = (
            "sudo bash -c 'sh -c \"timeout 30 nohup env FOO=bar "
            "xargs -I{} rm -rf /\"'"
        )
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Chain operators — ; && || |
# ---------------------------------------------------------------------------


class TestChainOperators:
    """Each segment MUST be checked independently."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hi; rm -rf /",
            "echo hi && rm -rf /",
            "ls || rm -rf /",
            "date; pwd; rm -rf /",
            "echo a; rm -rf /; echo b",
            "rm -rf /; echo hi",
            "cat /etc/passwd | rm -rf /",
        ],
    )
    async def test_chain_each_segment_checked(self, cmd: str):
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_safe_chain_passes(self):
        result = await _run("echo hi; ls; pwd")
        assert result == {}


# ---------------------------------------------------------------------------
# Command substitution — $(...) and backticks
# ---------------------------------------------------------------------------


class TestCommandSubstitution:
    @pytest.mark.asyncio
    async def test_dollar_paren_with_dangerous_inside(self):
        result = await _run("echo $(rm -rf /)")
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_backtick_with_dangerous_inside(self):
        result = await _run("echo `rm -rf /`")
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_nested_substitution(self):
        result = await _run("echo $(echo $(rm -rf /))")
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# find -exec and xargs
# ---------------------------------------------------------------------------


class TestFindAndXargs:
    @pytest.mark.asyncio
    async def test_find_exec_rm_rf(self):
        result = await _run("find . -exec rm -rf {} +")
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_find_delete_direct(self):
        result = await _run("find / -delete")
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_xargs_rm_rf(self):
        result = await _run("echo / | xargs -I{} rm -rf {}")
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# Unwrap order and quoting edges
# ---------------------------------------------------------------------------


class TestQuotingAndUnwrapOrder:
    @pytest.mark.asyncio
    async def test_bash_c_single_quotes(self):
        result = await _run("bash -c 'rm -rf /'")
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_bash_c_double_quotes(self):
        result = await _run('bash -c "rm -rf /"')
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_bash_c_no_quotes_complex(self):
        result = await _run("bash -c rm")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_bash_c_with_flags_between(self):
        result = await _run("bash -x -c 'rm -rf /'")
        assert _is_deny(result), (
            "bash -x -c 'rm -rf /' — unwrap MUST handle interleaved flags."
        )

    @pytest.mark.asyncio
    async def test_timeout_with_flags(self):
        result = await _run("timeout --preserve-status 30 rm -rf /")
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_env_with_multiple_vars(self):
        result = await _run("env A=1 B=2 C=3 rm -rf /")
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# Adversarial mixed chains
# ---------------------------------------------------------------------------


class TestMixedChainsAndUnwraps:
    @pytest.mark.asyncio
    async def test_chain_of_wrapped_commands(self):
        cmd = "echo hi; sudo bash -c 'rm -rf /'"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_two_wrapped_deny_commands(self):
        cmd = "sudo rm -rf /; nohup rm -rf /"
        assert _is_deny(await _run(cmd))

    @pytest.mark.asyncio
    async def test_unwrap_followed_by_safe_segment(self):
        cmd = "sudo rm -rf /home/user; echo ok"
        assert _is_deny(await _run(cmd))


# ---------------------------------------------------------------------------
# Pass-through after unwrap — safe wrappers
# ---------------------------------------------------------------------------


class TestWrappedSafeCommands:
    @pytest.mark.asyncio
    async def test_wrapped_safe_does_not_deny_sudo_apt(self):
        """sudo apt-get update is C5 WARN only — not a hard deny."""
        result = await _run("sudo apt-get update")
        assert result == {} or not (
            result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        )

    @pytest.mark.asyncio
    async def test_wrapped_safe_bash_c_echo(self):
        result = await _run("bash -c 'echo hi'")
        assert result == {}

    @pytest.mark.asyncio
    async def test_wrapped_safe_timeout_pytest(self):
        result = await _run("timeout 30 pytest tests/")
        assert result == {}

    @pytest.mark.asyncio
    async def test_wrapped_safe_env_python(self):
        result = await _run("env PYTHONPATH=. python run.py")
        assert result == {}

    @pytest.mark.asyncio
    async def test_wrapped_safe_nohup_python(self):
        result = await _run("nohup python long_job.py &")
        assert result == {}

    @pytest.mark.asyncio
    async def test_git_force_with_lease_allowed(self):
        result = await _run("git push --force-with-lease origin feat")
        assert result == {}

    @pytest.mark.asyncio
    async def test_rm_rf_node_modules_allowed(self):
        result = await _run("rm -rf node_modules")
        assert result == {}

    @pytest.mark.asyncio
    async def test_rm_rf_venv_allowed(self):
        result = await _run("rm -rf .venv")
        assert result == {}

    @pytest.mark.asyncio
    async def test_rm_rf_tmp_allowed(self):
        result = await _run("rm -rf /tmp/my-build")
        assert result == {}


# ---------------------------------------------------------------------------
# Recursion-bomb guard — bounded, fail-closed
# ---------------------------------------------------------------------------


class TestRecursionBomb:
    @pytest.mark.asyncio
    async def test_deep_nested_sudo_chain_denies_via_exhaustion(self):
        """A cmd with 20 layers of sudo wrap — ambiguity #2 requires DENY."""
        chain = "sudo " * 20 + "rm -rf /"
        result = await _run(chain)
        assert isinstance(result, dict)
        assert _is_deny(result), (
            "Ambiguity #2: past max_depth=5, fail-closed. 20x sudo must deny."
        )

    @pytest.mark.asyncio
    async def test_very_long_command_bounded(self):
        cmd = "echo " + "x " * 5000 + "; rm -rf /"
        result = await _run(cmd)
        assert _is_deny(result)
