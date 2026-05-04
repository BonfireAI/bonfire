"""RED contract tests — fail-closed on ALL exception paths (BON-338).

Sage-canonical. Knight-A basis + Sage ambiguity #3 lockdown.

Locks Sage D7 + ambiguity #3.

- D7: Any exception inside the hook body MUST return DENY with reason
  ``f"security-hook-error: {exc!r}"``.
- Ambiguity #3: the error branch MUST ALSO emit SecurityDenied with
  ``pattern_id="_infra.error"``. Operators grep session logs for this.
- Scout-1/338 §6: Wrap body in try/except; never raise.
- asyncio.CancelledError is BaseException and MUST propagate (not be caught).

The one condition that MUST NEVER hold: a DENY-worthy command slips through
because the hook died internally. Test every variant.
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Malformed input_data
# ---------------------------------------------------------------------------


class TestMalformedToolInput:
    @pytest.mark.asyncio
    async def test_tool_input_is_none(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": None},
            "tu1",
            {"signal": None},
        )
        assert result == {} or _is_deny(result)

    @pytest.mark.asyncio
    async def test_tool_input_missing_key(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash"},
            "tu1",
            {"signal": None},
        )
        assert result == {} or _is_deny(result)

    @pytest.mark.asyncio
    async def test_tool_input_is_list(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": ["command"]},
            "tu1",
            {"signal": None},
        )
        assert isinstance(result, dict), "Must not raise; must return dict."

    @pytest.mark.asyncio
    async def test_command_is_bytes(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": b"rm -rf /"},
            },
            "tu1",
            {"signal": None},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_command_is_int(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": 12345},
            },
            "tu1",
            {"signal": None},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_input_data_is_empty_dict(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook({}, "tu1", {"signal": None})
        assert result == {}

    @pytest.mark.asyncio
    async def test_unexpected_hook_event_name(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        for evt in ("PostToolUse", "UserPromptSubmit", "Stop", "unknown"):
            result = await hook(
                {
                    "hook_event_name": evt,
                    "tool_name": "Bash",
                    "tool_input": {"command": "rm -rf /"},
                },
                "tu1",
                {"signal": None},
            )
            assert result == {}

    @pytest.mark.asyncio
    async def test_tool_name_missing(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert result == {}


# ---------------------------------------------------------------------------
# Broken user regex — hook must DENY, not ALLOW
# ---------------------------------------------------------------------------


class TestBrokenExtraDenyPatterns:
    @pytest.mark.asyncio
    async def test_invalid_regex_denies(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        broken = SecurityHooksConfig(extra_deny_patterns=["[invalid(regex"])
        hook = build_preexec_hook(broken)
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)
        assert "security-hook-error" in _deny_reason(result).lower()

    @pytest.mark.asyncio
    async def test_unbalanced_paren_regex_denies(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        cfg = SecurityHooksConfig(extra_deny_patterns=["(unclosed"])
        hook = build_preexec_hook(cfg)
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_invalid_backref_regex_denies(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        cfg = SecurityHooksConfig(extra_deny_patterns=[r"\g<99>"])
        hook = build_preexec_hook(cfg)
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# AMBIGUITY #3 — error branch MUST emit SecurityDenied with _infra.error
# ---------------------------------------------------------------------------


class TestErrorBranchEmitsInfraEvent:
    """Sage ambiguity #3: on caught exception, hook emits SecurityDenied with
    ``pattern_id='_infra.error'`` and ``reason=f'security-hook-error: {exc!r}'``.
    """

    @pytest.mark.asyncio
    async def test_error_branch_emits_event(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook
        from bonfire.events.bus import EventBus
        from bonfire.models.events import SecurityDenied

        bus = EventBus()
        captured: list[SecurityDenied] = []

        async def consumer(event: SecurityDenied) -> None:
            captured.append(event)

        bus.subscribe(SecurityDenied, consumer)

        cfg = SecurityHooksConfig(extra_deny_patterns=["[invalid(regex"])
        hook = build_preexec_hook(
            cfg,
            bus=bus,
            session_id="s",
            agent_name="a",
        )
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert len(captured) == 1, (
            "Ambiguity #3: error branch MUST emit SecurityDenied for operator observability."
        )

    @pytest.mark.asyncio
    async def test_error_branch_pattern_id_is_infra_error(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook
        from bonfire.events.bus import EventBus
        from bonfire.models.events import SecurityDenied

        bus = EventBus()
        captured: list[SecurityDenied] = []

        async def consumer(event: SecurityDenied) -> None:
            captured.append(event)

        bus.subscribe(SecurityDenied, consumer)

        cfg = SecurityHooksConfig(extra_deny_patterns=["[invalid(regex"])
        hook = build_preexec_hook(
            cfg,
            bus=bus,
            session_id="s",
            agent_name="a",
        )
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert captured[0].pattern_id == "_infra.error", (
            f"Ambiguity #3: error-branch pattern_id MUST equal '_infra.error'. "
            f"Got {captured[0].pattern_id!r}"
        )

    @pytest.mark.asyncio
    async def test_error_branch_reason_contains_security_hook_error(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook
        from bonfire.events.bus import EventBus
        from bonfire.models.events import SecurityDenied

        bus = EventBus()
        captured: list[SecurityDenied] = []

        async def consumer(event: SecurityDenied) -> None:
            captured.append(event)

        bus.subscribe(SecurityDenied, consumer)

        cfg = SecurityHooksConfig(extra_deny_patterns=["[invalid(regex"])
        hook = build_preexec_hook(
            cfg,
            bus=bus,
            session_id="s",
            agent_name="a",
        )
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert "security-hook-error" in captured[0].reason.lower(), (
            "Ambiguity #3: error-branch reason prefix MUST be 'security-hook-error'."
        )


# ---------------------------------------------------------------------------
# Bus emission failure must NOT rescue dangerous commands
# ---------------------------------------------------------------------------


class TestBusEmissionFailure:
    @pytest.mark.asyncio
    async def test_bus_emit_raises_still_denies(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        class BrokenBus:
            async def emit(self, event: Any) -> None:
                raise RuntimeError("bus exploded")

        hook = build_preexec_hook(
            SecurityHooksConfig(),
            bus=BrokenBus(),  # type: ignore[arg-type]
            session_id="s",
            agent_name="a",
        )
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_bus_emit_raises_value_error_still_denies(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        class BrokenBus:
            async def emit(self, event: Any) -> None:
                raise ValueError("serialization failed")

        hook = build_preexec_hook(
            SecurityHooksConfig(),
            bus=BrokenBus(),
            session_id="s",
            agent_name="a",  # type: ignore[arg-type]
        )
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git push --force origin main"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# Monkeypatched internals — simulate bugs in normalize/unwrap/extract
# ---------------------------------------------------------------------------


class TestInternalFunctionRaises:
    @pytest.mark.asyncio
    async def test_normalize_raises_still_denies(self, monkeypatch: pytest.MonkeyPatch):
        import bonfire.dispatch.security_hooks as hooks_mod
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        def broken_normalize(_: str) -> str:
            raise RuntimeError("normalize exploded")

        monkeypatch.setattr(hooks_mod, "_normalize", broken_normalize)

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)
        assert "security-hook-error" in _deny_reason(result).lower()

    @pytest.mark.asyncio
    async def test_unwrap_raises_still_denies(self, monkeypatch: pytest.MonkeyPatch):
        import bonfire.dispatch.security_hooks as hooks_mod
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        def broken_unwrap(*args: Any, **kwargs: Any) -> list[str]:
            raise TypeError("unwrap got wrong type")

        monkeypatch.setattr(hooks_mod, "_unwrap", broken_unwrap)

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_extract_raises_still_denies(self, monkeypatch: pytest.MonkeyPatch):
        import bonfire.dispatch.security_hooks as hooks_mod
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        def broken_extract(*args: Any, **kwargs: Any) -> str:
            raise AttributeError("extract got wrong type")

        monkeypatch.setattr(hooks_mod, "_extract_command", broken_extract)

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)


# ---------------------------------------------------------------------------
# Error reason format
# ---------------------------------------------------------------------------


class TestErrorReasonFormat:
    @pytest.mark.asyncio
    async def test_reason_starts_with_security_hook_error(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        cfg = SecurityHooksConfig(extra_deny_patterns=["[broken"])
        hook = build_preexec_hook(cfg)
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        reason = _deny_reason(result).lower()
        assert reason.startswith("security-hook-error")


# ---------------------------------------------------------------------------
# asyncio.CancelledError — do NOT swallow (BaseException contract)
# ---------------------------------------------------------------------------


class TestCancellationSemantics:
    @pytest.mark.asyncio
    async def test_cancellation_propagates(self, monkeypatch: pytest.MonkeyPatch):
        import bonfire.dispatch.security_hooks as hooks_mod
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        def cancel_during_normalize(_: str) -> str:
            raise asyncio.CancelledError()

        monkeypatch.setattr(hooks_mod, "_normalize", cancel_during_normalize)

        hook = build_preexec_hook(SecurityHooksConfig())
        with pytest.raises(asyncio.CancelledError):
            await hook(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo hi"},
                },
                "tu1",
                {"signal": None},
            )


# ---------------------------------------------------------------------------
# Disabled config — build_dict returns None
# ---------------------------------------------------------------------------


class TestDisabledConfigNeverFailsClosed:
    @pytest.mark.asyncio
    async def test_build_dict_returns_none_when_disabled(self):
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig,
            _build_security_hooks_dict,
        )
        from bonfire.models.envelope import Envelope

        envelope = Envelope(task="t", agent_name="a")
        result = _build_security_hooks_dict(
            SecurityHooksConfig(enabled=False),
            bus=None,
            envelope=envelope,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Error branch MUST NOT return empty dict
# ---------------------------------------------------------------------------


class TestNoAllowByOmission:
    @pytest.mark.asyncio
    async def test_error_branch_is_not_empty_dict(self, monkeypatch: pytest.MonkeyPatch):
        import bonfire.dispatch.security_hooks as hooks_mod
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        def exploding_extract(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(hooks_mod, "_extract_command", exploding_extract)
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert result != {}, (
            "Error branch MUST NOT return empty dict — that is SDK's 'allow' "
            "wire format. MUST return deny envelope per D7."
        )
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_error_branch_uses_correct_wire_format(self, monkeypatch: pytest.MonkeyPatch):
        import bonfire.dispatch.security_hooks as hooks_mod
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        def broken(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(hooks_mod, "_normalize", broken)
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["hookSpecificOutput"]["permissionDecision"] != "DENY"
        assert result["hookSpecificOutput"]["permissionDecision"] != "block"
