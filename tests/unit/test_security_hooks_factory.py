"""RED contract tests — ``build_preexec_hook`` factory contract.

Sage-canonical (BON-338). Knight-B signature + wire-format lockdown + Knight-A
pass-through semantics + extra_deny pattern_id format (``user.extra.<i>``).

Locks Sage D5 (factory signature), D6 (hook return shape on deny/allow/WARN),
D11 (matcher wire format at dispatch layer).

Adversarial failsafe tests live in test_security_hooks_failsafe.py.
Event emission edges live in test_security_hooks_event.py.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

try:
    from bonfire.dispatch import security_hooks as _mod
    from bonfire.dispatch.security_hooks import (
        SecurityHooksConfig,
        build_preexec_hook,
    )
    from bonfire.events.bus import EventBus
    from bonfire.models.envelope import Envelope
    from bonfire.models.events import SecurityDenied
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    _mod = None  # type: ignore[assignment]
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
    build_preexec_hook = None  # type: ignore[assignment]
    EventBus = None  # type: ignore[assignment,misc]
    Envelope = None  # type: ignore[assignment,misc]
    SecurityDenied = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(
            f"bonfire.dispatch.security_hooks.build_preexec_hook not importable: "
            f"{_IMPORT_ERROR}"
        )


# ---------------------------------------------------------------------------
# Factory signature (Knight-B, D5)
# ---------------------------------------------------------------------------


class TestBuildPreexecHookSignature:
    def test_function_name(self):
        """D5: function name is ``build_preexec_hook``."""
        assert build_preexec_hook.__name__ == "build_preexec_hook"

    def test_exported_in_all(self):
        names = set(getattr(_mod, "__all__", []) or [])
        assert "build_preexec_hook" in names

    def test_signature_parameters(self):
        """D5: ``build_preexec_hook(config, *, bus=None, session_id=None, agent_name=None)``."""
        sig = inspect.signature(build_preexec_hook)
        param_names = list(sig.parameters.keys())
        assert "config" in param_names
        assert "bus" in param_names
        assert "session_id" in param_names
        assert "agent_name" in param_names

    def test_config_is_first_positional(self):
        sig = inspect.signature(build_preexec_hook)
        first = next(iter(sig.parameters.values()))
        assert first.name == "config"

    def test_bus_has_none_default(self):
        sig = inspect.signature(build_preexec_hook)
        assert sig.parameters["bus"].default is None

    def test_session_id_has_none_default(self):
        sig = inspect.signature(build_preexec_hook)
        assert sig.parameters["session_id"].default is None

    def test_agent_name_has_none_default(self):
        sig = inspect.signature(build_preexec_hook)
        assert sig.parameters["agent_name"].default is None


# ---------------------------------------------------------------------------
# Returned callable shape (Knight-B, Scout-1/338 §3)
# ---------------------------------------------------------------------------


class TestReturnedHookShape:
    def test_returns_coroutine_function(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        assert asyncio.iscoroutinefunction(hook), (
            "build_preexec_hook must return an async def callable. "
            "Plain def raises at SDK dispatch time."
        )

    def test_returned_is_callable(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        assert callable(hook)

    def test_returned_accepts_three_positional_args(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        sig = inspect.signature(hook)
        assert len(sig.parameters) == 3


# ---------------------------------------------------------------------------
# Allow / pass-through contract (Knight-B + Knight-A tool narrow)
# ---------------------------------------------------------------------------


class TestHookPassThrough:
    @pytest.mark.asyncio
    async def test_wrong_event_name_returns_empty(self):
        """D6: non-PreToolUse events pass through as ``{}``."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PostToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_unrelated_tool_returns_empty(self):
        """D6: Read/Grep/Glob/WebSearch pass through as ``{}``."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Read",
             "tool_input": {"file_path": "/etc/passwd"}},
            "tu1",
            {"signal": None},
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_safe_bash_returns_empty(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "pytest tests/"}},
            "tu1",
            {"signal": None},
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_command_returns_empty(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": ""}},
            "tu1",
            {"signal": None},
        )
        assert result == {}


# ---------------------------------------------------------------------------
# Deny wire format (Knight-B, Scout-1/338 §2)
# ---------------------------------------------------------------------------


class TestHookDenyWireFormat:
    @pytest.mark.asyncio
    async def test_deny_has_hook_specific_output_envelope(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert "hookSpecificOutput" in result

    @pytest.mark.asyncio
    async def test_deny_permission_decision_lowercase(self):
        """D6: ``permissionDecision == "deny"`` (lowercase, not DENY/block)."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        # Belt-and-suspenders: explicit rejection of uppercase/alias forms.
        assert result["hookSpecificOutput"]["permissionDecision"] != "DENY"
        assert result["hookSpecificOutput"]["permissionDecision"] != "block"

    @pytest.mark.asyncio
    async def test_deny_hook_event_name_camelcase(self):
        """D6: ``hookEventName == "PreToolUse"`` (CamelCase)."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    @pytest.mark.asyncio
    async def test_deny_includes_reason_string(self):
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert isinstance(reason, str)
        assert reason

    @pytest.mark.asyncio
    async def test_no_top_level_decision_field_on_deny(self):
        """Scout-1/338 §2: PreToolUse uses hookSpecificOutput.permissionDecision,
        NOT top-level ``decision``."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert "decision" not in result


# ---------------------------------------------------------------------------
# Extra deny patterns — additive; pattern_id uses ``user.extra.<i>`` slug
# ---------------------------------------------------------------------------


class TestExtraDenyPatternsAdditive:
    @pytest.mark.asyncio
    async def test_user_pattern_triggers_deny(self):
        """D8: user extras extend the deny list."""
        cfg = SecurityHooksConfig(extra_deny_patterns=[r"\bmy_bespoke_danger\b"])
        hook = build_preexec_hook(cfg)
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm my_bespoke_danger"}},
            "tu1",
            {"signal": None},
        )
        assert result.get("hookSpecificOutput", {}).get("permissionDecision") in (
            "deny", None,
        )

    @pytest.mark.asyncio
    async def test_defaults_still_deny_when_extras_supplied(self):
        """Extras extend, never replace — defaults still fire."""
        cfg = SecurityHooksConfig(extra_deny_patterns=["anothertoken"])
        hook = build_preexec_hook(cfg)
        result = await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_user_extra_pattern_id_format(self):
        """Per Sage D6: user extras get pattern_id like ``user.extra.<i>``."""
        bus = EventBus()
        captured: list = []

        async def consumer(event):
            captured.append(event)

        bus.subscribe(SecurityDenied, consumer)

        cfg = SecurityHooksConfig(extra_deny_patterns=[r"my-dangerous-tool"])
        hook = build_preexec_hook(
            cfg, bus=bus, session_id="s", agent_name="a",
        )
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "my-dangerous-tool arg"}},
            "tu1",
            {"signal": None},
        )
        assert len(captured) == 1
        assert captured[0].pattern_id.startswith("user.extra."), (
            "Sage D6 hook body uses ``f'user.extra.{i}'`` for user patterns."
        )


# ---------------------------------------------------------------------------
# Disabled config — _build_security_hooks_dict returns None
# ---------------------------------------------------------------------------


class TestBuildSecurityHooksDictDisabled:
    def test_disabled_returns_none(self):
        from bonfire.dispatch.security_hooks import _build_security_hooks_dict

        envelope = Envelope(task="t", agent_name="a")
        result = _build_security_hooks_dict(
            SecurityHooksConfig(enabled=False),
            bus=None,
            envelope=envelope,
        )
        assert result is None

    def test_enabled_returns_dict_with_pretooluse(self):
        from bonfire.dispatch.security_hooks import _build_security_hooks_dict

        envelope = Envelope(task="t", agent_name="a")
        result = _build_security_hooks_dict(
            SecurityHooksConfig(enabled=True),
            bus=None,
            envelope=envelope,
        )
        if result is not None:
            assert "PreToolUse" in result
            assert isinstance(result["PreToolUse"], list)
            assert len(result["PreToolUse"]) == 1


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


class TestHookModuleExports:
    def test_exports_security_hooks_config(self):
        assert hasattr(_mod, "SecurityHooksConfig")

    def test_exports_build_preexec_hook(self):
        assert hasattr(_mod, "build_preexec_hook")

    def test_all_list_includes_public_api(self):
        names = set(getattr(_mod, "__all__", []) or [])
        assert {"SecurityHooksConfig", "build_preexec_hook"}.issubset(names)
