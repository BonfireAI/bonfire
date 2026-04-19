"""RED contract tests — concurrency + stateful closure runtime (BON-338).

Sage-canonical. Knight-A basis — covers closure isolation, concurrent
dispatch, real EventBus integration.

Locks Sage D5 (factory returns independent closures) and Scout-1/338 §7
(stateful closures + concurrency caveats).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


class _CollectingBus:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self._lock = asyncio.Lock()

    async def emit(self, event: Any) -> None:
        async with self._lock:
            self.events.append(event)


# ---------------------------------------------------------------------------
# Independent closures
# ---------------------------------------------------------------------------


class TestIndependentClosures:
    def test_two_builds_return_different_callables(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        h1 = build_preexec_hook(SecurityHooksConfig())
        h2 = build_preexec_hook(SecurityHooksConfig())
        assert h1 is not h2, "Each build call must produce a fresh closure."

    @pytest.mark.asyncio
    async def test_two_hooks_with_different_agent_names(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        bus1 = _CollectingBus()
        bus2 = _CollectingBus()
        h1 = build_preexec_hook(
            SecurityHooksConfig(), bus=bus1, session_id="s1", agent_name="agent-alpha",  # type: ignore[arg-type]
        )
        h2 = build_preexec_hook(
            SecurityHooksConfig(), bus=bus2, session_id="s2", agent_name="agent-beta",  # type: ignore[arg-type]
        )

        input_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        }
        await h1(input_data, "tu1", {"signal": None})
        await h2(input_data, "tu2", {"signal": None})

        assert len(bus1.events) == 1
        assert len(bus2.events) == 1
        assert bus1.events[0].agent_name == "agent-alpha"
        assert bus2.events[0].agent_name == "agent-beta"
        assert bus1.events[0].session_id == "s1"
        assert bus2.events[0].session_id == "s2"


# ---------------------------------------------------------------------------
# Concurrent dispatch on different hooks
# ---------------------------------------------------------------------------


class TestConcurrentDifferentHooks:
    @pytest.mark.asyncio
    async def test_gather_distinct_agents(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        bus1 = _CollectingBus()
        bus2 = _CollectingBus()
        h1 = build_preexec_hook(
            SecurityHooksConfig(), bus=bus1, session_id="alpha", agent_name="A",  # type: ignore[arg-type]
        )
        h2 = build_preexec_hook(
            SecurityHooksConfig(), bus=bus2, session_id="beta", agent_name="B",  # type: ignore[arg-type]
        )

        input_a = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        }
        input_b = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        }

        r1, r2 = await asyncio.gather(
            h1(input_a, "tu-a", {"signal": None}),
            h2(input_b, "tu-b", {"signal": None}),
        )

        assert r1["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert r2["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert len(bus1.events) == 1
        assert len(bus2.events) == 1
        assert bus1.events[0].agent_name == "A"
        assert bus2.events[0].agent_name == "B"
        assert bus1.events[0].pattern_id.startswith("C1.")
        assert bus2.events[0].pattern_id.startswith("C2.")


# ---------------------------------------------------------------------------
# Concurrent invocations of the SAME hook
# ---------------------------------------------------------------------------


class TestConcurrentSameHook:
    @pytest.mark.asyncio
    async def test_same_hook_parallel_denials(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        bus = _CollectingBus()
        hook = build_preexec_hook(
            SecurityHooksConfig(), bus=bus, session_id="s", agent_name="a",  # type: ignore[arg-type]
        )
        inputs = [
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}}
            for _ in range(10)
        ]
        results = await asyncio.gather(
            *(hook(i, f"tu-{n}", {"signal": None}) for n, i in enumerate(inputs))
        )
        assert all(
            r["hookSpecificOutput"]["permissionDecision"] == "deny" for r in results
        )
        assert len(bus.events) == 10

    @pytest.mark.asyncio
    async def test_same_hook_mixed_allow_deny(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        bus = _CollectingBus()
        hook = build_preexec_hook(
            SecurityHooksConfig(), bus=bus, session_id="s", agent_name="a",  # type: ignore[arg-type]
        )
        commands = [
            "rm -rf /",
            "echo hi",
            "git push --force origin main",
            "pytest tests/",
            "cat ~/.ssh/id_rsa",
            "ls",
        ]
        expected_deny_count = sum(
            1 for c in commands
            if "rm -rf /" in c or "--force" in c or "id_rsa" in c
        )

        results = await asyncio.gather(
            *(
                hook(
                    {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                     "tool_input": {"command": c}},
                    f"tu-{n}",
                    {"signal": None},
                )
                for n, c in enumerate(commands)
            )
        )
        deny_count = sum(
            1 for r in results
            if r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        )
        assert deny_count == expected_deny_count
        assert len(bus.events) == expected_deny_count


# ---------------------------------------------------------------------------
# Config isolation across closures
# ---------------------------------------------------------------------------


class TestConfigIsolation:
    @pytest.mark.asyncio
    async def test_enabled_vs_disabled_emission(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        bus_emit = _CollectingBus()
        bus_silent = _CollectingBus()
        h_emit = build_preexec_hook(
            SecurityHooksConfig(emit_denial_events=True),
            bus=bus_emit, session_id="s", agent_name="a",  # type: ignore[arg-type]
        )
        h_silent = build_preexec_hook(
            SecurityHooksConfig(emit_denial_events=False),
            bus=bus_silent, session_id="s", agent_name="a",  # type: ignore[arg-type]
        )

        input_data = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        }
        r1 = await h_emit(input_data, "tu1", {"signal": None})
        r2 = await h_silent(input_data, "tu2", {"signal": None})

        assert r1["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert r2["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert len(bus_emit.events) == 1
        assert len(bus_silent.events) == 0

    @pytest.mark.asyncio
    async def test_extra_deny_isolation(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        h_a = build_preexec_hook(
            SecurityHooksConfig(extra_deny_patterns=[r"alpha-tool"]),
        )
        h_b = build_preexec_hook(
            SecurityHooksConfig(extra_deny_patterns=[r"beta-tool"]),
        )

        input_alpha = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "alpha-tool do-stuff"},
        }
        input_beta = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "beta-tool do-stuff"},
        }

        r_a_alpha = await h_a(input_alpha, "tu1", {"signal": None})
        r_a_beta = await h_a(input_beta, "tu2", {"signal": None})
        assert r_a_alpha["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert r_a_beta == {}

        r_b_alpha = await h_b(input_alpha, "tu3", {"signal": None})
        r_b_beta = await h_b(input_beta, "tu4", {"signal": None})
        assert r_b_alpha == {}
        assert r_b_beta["hookSpecificOutput"]["permissionDecision"] == "deny"


# ---------------------------------------------------------------------------
# Async contract
# ---------------------------------------------------------------------------


class TestHookIsAsync:
    def test_hook_is_coroutine_function(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        assert asyncio.iscoroutinefunction(hook)

    @pytest.mark.asyncio
    async def test_hook_returns_awaitable(self):
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook

        hook = build_preexec_hook(SecurityHooksConfig())
        coro = hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "ls"}},
            "tu1",
            {"signal": None},
        )
        assert asyncio.iscoroutine(coro)
        result = await coro
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Real EventBus integration
# ---------------------------------------------------------------------------


class TestWithRealEventBus:
    @pytest.mark.asyncio
    async def test_real_bus_typed_subscriber(self):
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
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu1",
            {"signal": None},
        )
        assert len(captured) == 1
        assert captured[0].sequence == 1

    @pytest.mark.asyncio
    async def test_real_bus_sequence_monotonic_across_denies(self):
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
        for cmd in ("rm -rf /", "git push --force origin main", "cat ~/.ssh/id_rsa"):
            await hook(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": cmd}},
                "tu",
                {"signal": None},
            )
        assert [e.sequence for e in captured] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_real_bus_subscribe_all_receives_security_denied(self):
        """SessionLoggerConsumer uses subscribe_all — SecurityDenied flows through."""
        from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook
        from bonfire.events.bus import EventBus
        from bonfire.models.events import BonfireEvent, SecurityDenied

        bus = EventBus()
        captured: list[BonfireEvent] = []

        async def global_consumer(event: BonfireEvent) -> None:
            captured.append(event)

        bus.subscribe_all(global_consumer)

        hook = build_preexec_hook(
            SecurityHooksConfig(), bus=bus, session_id="s", agent_name="a",
        )
        await hook(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "rm -rf /"}},
            "tu",
            {"signal": None},
        )
        assert len(captured) == 1
        assert isinstance(captured[0], SecurityDenied)
