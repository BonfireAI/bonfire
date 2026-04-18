"""RED contract tests — SDK backend ``hooks=`` wiring.

Sage-canonical (BON-338). Knight-B basis + Knight-A no-BON-337-leakage
regression guards.

Locks Sage D11: ``ClaudeAgentOptions.hooks`` kwarg plumbing + constructor
changes.

- ``ClaudeSDKBackend.__init__`` gains ``bus: EventBus | None = None`` kwarg.
- ``_do_execute`` passes
  ``hooks=_build_security_hooks_dict(options.security_hooks, bus=self._bus, envelope=envelope)``.
- When ``options.security_hooks.enabled=True`` (default), the kwarg is a dict
  with ``"PreToolUse"`` key containing one ``HookMatcher``.
- When ``options.security_hooks.enabled=False``, the kwarg is ``None``.
- The matcher string is exactly ``"Bash|Write|Edit"`` (ambiguity #5 unanchored).
- BON-338 MUST NOT introduce ``tools=``, ``disallowed_tools=``, or ``tool_policy=``
  kwargs — those are BON-337's territory.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bonfire.models.envelope import Envelope

try:
    from bonfire.dispatch.security_hooks import SecurityHooksConfig
    from bonfire.protocols import DispatchOptions
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR_CONFIG: Exception | None = _exc
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
    DispatchOptions = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR_CONFIG = None

try:
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR_BACKEND: Exception | None = _exc
    ClaudeSDKBackend = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR_BACKEND = None


@pytest.fixture(autouse=True)
def _require_modules():
    if _IMPORT_ERROR_CONFIG is not None:
        pytest.fail(
            f"bonfire.dispatch.security_hooks not importable: {_IMPORT_ERROR_CONFIG}"
        )
    if _IMPORT_ERROR_BACKEND is not None:
        pytest.fail(
            f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR_BACKEND}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capturing_options_class(captured: dict):
    """Factory producing a fake ClaudeAgentOptions that records kwargs."""

    class _FakeOptions:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    return _FakeOptions


async def _empty_query(*, prompt, options):
    if False:
        yield None


def _envelope() -> Envelope:
    return Envelope(task="do thing", agent_name="warrior", model="claude-opus")


# ---------------------------------------------------------------------------
# Backend __init__ accepts bus kwarg
# ---------------------------------------------------------------------------


class TestBackendAcceptsBusKwarg:
    def test_accepts_bus_none(self):
        backend = ClaudeSDKBackend(bus=None)
        assert backend is not None

    def test_accepts_bus_instance(self):
        from bonfire.events.bus import EventBus

        bus = EventBus()
        backend = ClaudeSDKBackend(bus=bus)
        assert backend is not None

    def test_stores_bus_as_private(self):
        from bonfire.events.bus import EventBus

        bus = EventBus()
        backend = ClaudeSDKBackend(bus=bus)
        assert backend._bus is bus

    def test_default_bus_is_none(self):
        backend = ClaudeSDKBackend()
        assert backend._bus is None


# ---------------------------------------------------------------------------
# hooks kwarg reaches ClaudeAgentOptions
# ---------------------------------------------------------------------------


class TestHooksKwargWiring:
    @pytest.mark.asyncio
    async def test_default_config_produces_hooks_dict(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=DispatchOptions())

        assert "hooks" in captured, (
            "ClaudeAgentOptions must receive ``hooks`` kwarg."
        )

    @pytest.mark.asyncio
    async def test_default_hooks_has_pretooluse_key(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=DispatchOptions())

        hooks = captured.get("hooks")
        assert hooks is not None
        assert "PreToolUse" in hooks
        assert isinstance(hooks["PreToolUse"], list)
        assert len(hooks["PreToolUse"]) == 1

    @pytest.mark.asyncio
    async def test_disabled_config_sends_none_hooks(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(
                security_hooks=SecurityHooksConfig(enabled=False)
            )
            await backend.execute(_envelope(), options=options)

        assert captured.get("hooks") is None


# ---------------------------------------------------------------------------
# HookMatcher shape — ambiguity #5 locked unanchored
# ---------------------------------------------------------------------------


class TestHookMatcherShape:
    @pytest.mark.asyncio
    async def test_matcher_string_is_bash_write_edit(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=DispatchOptions())

        hooks = captured.get("hooks")
        assert hooks is not None
        matchers = hooks["PreToolUse"]
        assert len(matchers) == 1
        matcher = matchers[0]
        matcher_str = getattr(matcher, "matcher", None)
        assert matcher_str == "Bash|Write|Edit", (
            f"Ambiguity #5: matcher MUST be 'Bash|Write|Edit' unanchored. "
            f"Got {matcher_str!r}"
        )

    @pytest.mark.asyncio
    async def test_matcher_has_one_hook_callback(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=DispatchOptions())

        hooks = captured["hooks"]
        matcher = hooks["PreToolUse"][0]
        cb_list = getattr(matcher, "hooks", None)
        assert cb_list is not None
        assert len(cb_list) == 1


# ---------------------------------------------------------------------------
# Envelope threading — session_id + agent_name flow through
# ---------------------------------------------------------------------------


class TestEnvelopeThreadedIntoHook:
    def test_build_security_hooks_dict_uses_envelope_id(self):
        from bonfire.dispatch.security_hooks import _build_security_hooks_dict

        envelope = Envelope(task="t", agent_name="warrior-x")

        captured_args: dict = {}

        def _capturing(config, *, bus, session_id, agent_name):
            captured_args["config"] = config
            captured_args["bus"] = bus
            captured_args["session_id"] = session_id
            captured_args["agent_name"] = agent_name

            async def _stub(*a, **kw):
                return {}

            return _stub

        with patch(
            "bonfire.dispatch.security_hooks.build_preexec_hook", _capturing,
        ):
            result = _build_security_hooks_dict(
                SecurityHooksConfig(enabled=True),
                bus=None,
                envelope=envelope,
            )

        assert captured_args.get("session_id") == envelope.envelope_id
        assert captured_args.get("agent_name") == "warrior-x"
        assert result is None or "PreToolUse" in result


# ---------------------------------------------------------------------------
# SDK import guard extended with HookMatcher
# ---------------------------------------------------------------------------


class TestSdkImportGuardExtended:
    def test_hook_matcher_symbol_exists(self):
        from bonfire.dispatch import sdk_backend

        assert hasattr(sdk_backend, "HookMatcher")


# ---------------------------------------------------------------------------
# No BON-337 leakage (regression)
# ---------------------------------------------------------------------------


class TestNoBON337Leakage:
    """BON-338 decouple mandate: no ``tools=``, ``disallowed_tools=``, or
    ``tool_policy=`` at the SDK call site."""

    @pytest.mark.asyncio
    async def test_no_disallowed_tools_kwarg(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=DispatchOptions())

        assert "disallowed_tools" not in captured

    @pytest.mark.asyncio
    async def test_no_tool_policy_kwarg(self):
        captured: dict = {}

        with patch(
            "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
            _capturing_options_class(captured),
        ), patch(
            "bonfire.dispatch.sdk_backend.query", _empty_query,
        ):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=DispatchOptions())

        assert "tool_policy" not in captured
