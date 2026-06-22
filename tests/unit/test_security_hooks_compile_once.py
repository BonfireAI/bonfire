"""RED regression tests — BON-910.

The pre-exec security hook must compile user-supplied ``extra_deny_patterns``
exactly once, at ``build_preexec_hook`` factory time, NOT on every
Bash/Write/Edit hook fire.

Current behaviour: ``build_preexec_hook`` returns a closure that calls
``_compile_user_patterns(list(user_patterns_source))`` inside the hook body,
so ``re.compile`` runs once per pattern *per tool call*. On a long agent
dispatch (hundreds of tool calls) that is wasted, repeated work — the
compile result is stable because the config is frozen and the pattern
tuple is captured at factory time.

Contract pinned here:
  * N patterns + 1000 hook calls  ->  ``re.compile`` invoked exactly N times.
  * 0 patterns + many hook calls   ->  ``re.compile`` not invoked at all
    (no user patterns to compile).
  * Fail-safe preserved: a broken user pattern still produces a DENY
    envelope from the hook (compile error surfaces as ``_infra.error`` DENY).

Until the compile call is hoisted into the factory body, the count-based
tests below FAIL (re.compile fires once per call -> ~1000 calls, not N).
"""

from __future__ import annotations

import re

import pytest

try:
    from bonfire.dispatch.security_hooks import (
        SecurityHooksConfig,
        build_preexec_hook,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
    build_preexec_hook = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.security_hooks not importable: {_IMPORT_ERROR}")


def _bash_event(command: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class TestUserPatternsCompiledOncePerFactory:
    """BON-910 — user regex patterns compile once per factory, not per call."""

    @pytest.mark.asyncio
    async def test_compile_called_n_times_for_n_patterns_over_many_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """N patterns + 1000 hook calls => re.compile invoked exactly N times."""
        patterns = [r"\bdanger_one\b", r"\bdanger_two\b", r"\bdanger_three\b"]
        n = len(patterns)

        real_compile = re.compile
        calls: list[str] = []

        def _counting_compile(pattern, *args, **kwargs):
            calls.append(pattern if isinstance(pattern, str) else repr(pattern))
            return real_compile(pattern, *args, **kwargs)

        # Patch the re module the hook module imports through.
        monkeypatch.setattr("bonfire.dispatch.security_hooks.re.compile", _counting_compile)

        cfg = SecurityHooksConfig(extra_deny_patterns=patterns)
        hook = build_preexec_hook(cfg)

        # 1000 benign Bash calls — none match a user pattern.
        for _ in range(1000):
            await hook(_bash_event("echo hello world"), "tu", {"signal": None})

        assert len(calls) == n, (
            f"re.compile must run exactly {n} times (once per user pattern at "
            f"factory time), got {len(calls)} — patterns are being recompiled "
            f"on every hook fire (BON-910)."
        )

    @pytest.mark.asyncio
    async def test_no_user_patterns_means_no_compile_on_hook_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """0 user patterns + many calls => re.compile never invoked by the hook."""
        real_compile = re.compile
        calls: list[str] = []

        def _counting_compile(pattern, *args, **kwargs):
            calls.append(pattern if isinstance(pattern, str) else repr(pattern))
            return real_compile(pattern, *args, **kwargs)

        cfg = SecurityHooksConfig()  # no extra_deny_patterns
        hook = build_preexec_hook(cfg)

        # Patch AFTER factory build so we only measure per-call compiles.
        monkeypatch.setattr("bonfire.dispatch.security_hooks.re.compile", _counting_compile)

        for _ in range(500):
            await hook(_bash_event("ls -la"), "tu", {"signal": None})

        assert calls == [], (
            f"With no user patterns, the hook must not call re.compile on any "
            f"tool call — got {len(calls)} calls (BON-910)."
        )

    @pytest.mark.asyncio
    async def test_broken_user_pattern_still_denies(self):
        """Fail-safe preserved: an invalid user regex still yields a DENY envelope."""
        cfg = SecurityHooksConfig(extra_deny_patterns=[r"([unclosed"])
        hook = build_preexec_hook(cfg)
        result = await hook(
            _bash_event("echo harmless"),
            "tu",
            {"signal": None},
        )
        assert result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (
            "A broken user pattern must fail CLOSED — the hook must DENY "
            "regardless of when the compile happens (BON-910 AC: fail-safe "
            "semantics preserved)."
        )
