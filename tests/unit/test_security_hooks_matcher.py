"""RED contract tests — HookMatcher regex anchoring (BON-338).

Sage-canonical. Knight-A basis + Sage ambiguity #5 lockdown.

Ambiguity #5: ``matcher="Bash|Write|Edit"`` (UNANCHORED) wins. The hook BODY
is authoritative (Sage D6 narrows ``tool_name not in ("Bash","Write","Edit")``
inside the callback). MCP tools use namespaced names (``mcp__server__tool``)
so unanchored matcher substring false-positives don't translate into false
denies. Knight-A's anchored-proposal xfail is REMOVED — the unanchored lock
becomes mandatory.
"""

from __future__ import annotations

import re
from typing import Any

import pytest


def _make_envelope() -> Any:
    from bonfire.models.envelope import Envelope

    return Envelope(task="t", agent_name="a")


# ---------------------------------------------------------------------------
# Matcher regex surface — AMBIGUITY #5 lockdown
# ---------------------------------------------------------------------------


class TestMatcherRegexString:
    """Ambiguity #5: matcher is exactly ``Bash|Write|Edit`` (UNANCHORED)."""

    def test_matcher_regex_is_bash_write_edit(self):
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig,
            _build_security_hooks_dict,
        )

        result = _build_security_hooks_dict(
            SecurityHooksConfig(enabled=True),
            bus=None,
            envelope=_make_envelope(),
        )
        assert result is not None
        assert "PreToolUse" in result
        matchers = result["PreToolUse"]
        assert len(matchers) == 1

        matcher_obj = matchers[0]
        matcher_regex = getattr(matcher_obj, "matcher", None)
        assert matcher_regex == "Bash|Write|Edit", (
            f"Ambiguity #5: matcher MUST be 'Bash|Write|Edit' unanchored. Got {matcher_regex!r}"
        )

    def test_matcher_is_unanchored(self):
        """Ambiguity #5: explicit unanchored lockdown — no ``^...$``."""
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig,
            _build_security_hooks_dict,
        )

        result = _build_security_hooks_dict(
            SecurityHooksConfig(),
            bus=None,
            envelope=_make_envelope(),
        )
        assert result is not None
        matcher_regex = getattr(result["PreToolUse"][0], "matcher", "")
        assert not matcher_regex.startswith("^"), (
            "Ambiguity #5: matcher MUST be unanchored. No leading ^."
        )
        assert not matcher_regex.endswith("$"), (
            "Ambiguity #5: matcher MUST be unanchored. No trailing $."
        )

    def test_matcher_compiles_as_regex(self):
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig,
            _build_security_hooks_dict,
        )

        result = _build_security_hooks_dict(
            SecurityHooksConfig(),
            bus=None,
            envelope=_make_envelope(),
        )
        assert result is not None
        matcher_regex = getattr(result["PreToolUse"][0], "matcher", None)
        re.compile(matcher_regex)  # must not raise


# ---------------------------------------------------------------------------
# Hook body narrow — authoritative gate
# ---------------------------------------------------------------------------


class TestHookBodyNarrow:
    """Sage D6: ``tool_name not in ('Bash','Write','Edit')`` inside the hook
    body is the authoritative gate. Unanchored matcher + body narrow combined
    yields correct behavior even for adversarial tool_name values."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name",
        [
            "Read",
            "Grep",
            "Glob",
            "WebSearch",
            "WebFetch",
            "Task",
            "TodoWrite",
            "mcp__some_server__some_tool",
            # Adversarial: tool names that substring-match the unanchored matcher
            # but MUST still pass through per Sage D6 narrow.
            "BashTool",
            "myBash",
            "Bash2",
            "bash",  # lowercase — not in ('Bash','Write','Edit')
        ],
    )
    async def test_non_target_tool_passes_through(self, tool_name: str):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": tool_name,
                "tool_input": {"command": "rm -rf /"},
            },
            "tu1",
            {"signal": None},
        )
        assert result == {}, (
            f"Tool {tool_name!r} is NOT in ('Bash','Write','Edit') — hook body "
            "narrow per Sage D6 MUST pass through."
        )

    @pytest.mark.asyncio
    async def test_target_tool_does_go_through_pipeline(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
            },
            "tu1",
            {"signal": None},
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


# ---------------------------------------------------------------------------
# Ambiguity #5 behavior: BashTool passes through despite unanchored match
# ---------------------------------------------------------------------------


class TestUnanchoredMatcherSafety:
    """Ambiguity #5 guarantees unanchored matcher + body narrow = safe."""

    @pytest.mark.asyncio
    async def test_bashtool_not_target_passes_through(self):
        """Future-proof: unanchored matcher may dispatch ``BashTool``; body narrow
        MUST reject it as non-target."""
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "BashTool",
                "tool_input": {"command": "rm -rf /"},
            },
            "tu1",
            {"signal": None},
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_bash_exact_match_enters_pipeline(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

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
        assert result == {}

    @pytest.mark.asyncio
    async def test_write_exact_match_enters_pipeline(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": "/home/user/script.py"},
            },
            "tu1",
            {"signal": None},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edit_exact_match_enters_pipeline(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "/home/user/config.yml"},
            },
            "tu1",
            {"signal": None},
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Disabled config → no matcher
# ---------------------------------------------------------------------------


class TestDisabledConfigNoMatcher:
    def test_disabled_returns_none(self):
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig,
            _build_security_hooks_dict,
        )

        result = _build_security_hooks_dict(
            SecurityHooksConfig(enabled=False),
            bus=None,
            envelope=_make_envelope(),
        )
        assert result is None

    def test_enabled_true_returns_matcher_list(self):
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig,
            _build_security_hooks_dict,
        )

        result = _build_security_hooks_dict(
            SecurityHooksConfig(enabled=True),
            bus=None,
            envelope=_make_envelope(),
        )
        assert result is not None
        assert isinstance(result, dict)
        assert "PreToolUse" in result
        assert isinstance(result["PreToolUse"], list)
        assert len(result["PreToolUse"]) == 1
