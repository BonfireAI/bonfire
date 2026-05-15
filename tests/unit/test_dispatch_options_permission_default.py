"""RED contract for DispatchOptions.permission_mode default flip.

Subject: ``bonfire.protocols.DispatchOptions.permission_mode`` currently
defaults to ``"dontAsk"``. Combined with the deny-list-as-only-gate
architecture, this is default-allow-then-best-effort-deny. The v0.1
ship-safe answer is to **flip the default to ``"default"``** (SDK
ask-mode). Explicit ``"dontAsk"`` callers in ``handlers/`` (wizard,
sage_correction_bounce) opt in by name and stay unchanged.

This file pins down:

  * ``DispatchOptions().permission_mode == "default"`` (NEW default).
  * An explicit ``DispatchOptions(permission_mode="dontAsk")`` is
    honored unchanged.
  * ``ClaudeAgentOptions`` (in ``dispatch/sdk_backend.py``) receives
    ``permission_mode="default"`` when called with a default
    ``DispatchOptions``.

The three existing default-asserting tests are updated in their own
test files (see the ``CONTRACT-CHANGE:`` breadcrumbs there).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from bonfire.models.envelope import Envelope
from bonfire.protocols import DispatchOptions

try:
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    ClaudeSDKBackend = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


def _make_capture() -> tuple[dict[str, Any], type]:
    """Return ``(captured_kwargs_dict, FakeClaudeAgentOptions)`` pair."""
    captured: dict[str, Any] = {}

    class _FakeClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

    return captured, _FakeClaudeAgentOptions


async def _empty_query(*, prompt: str = "", options: Any = None):  # type: ignore[no-untyped-def]
    if False:  # pragma: no cover
        yield None


def _envelope() -> Envelope:
    return Envelope(task="do work", agent_name="warrior-agent", model="claude-opus-4-7")


class TestDefaultPermissionModeFlippedToDefault:
    """``DispatchOptions()`` now defaults ``permission_mode`` to ``"default"``."""

    def test_default_is_default_string(self) -> None:
        """The new default is the string ``"default"`` (SDK ask-mode)."""
        opts = DispatchOptions()
        assert opts.permission_mode == "default", (
            f"DispatchOptions.permission_mode default should be 'default' "
            f"(SDK ask-mode); got {opts.permission_mode!r}"
        )

    def test_default_remains_a_string(self) -> None:
        """Type contract — still a plain string, not an enum or alias."""
        opts = DispatchOptions()
        assert isinstance(opts.permission_mode, str)


class TestExplicitDontAskStillHonored:
    """Callers that explicitly pass ``permission_mode='dontAsk'`` opt in."""

    def test_explicit_dont_ask_round_trips(self) -> None:
        """Explicit ``dontAsk`` is preserved verbatim."""
        opts = DispatchOptions(permission_mode="dontAsk")
        assert opts.permission_mode == "dontAsk"

    def test_explicit_default_round_trips(self) -> None:
        """Explicit ``default`` is preserved verbatim."""
        opts = DispatchOptions(permission_mode="default")
        assert opts.permission_mode == "default"

    def test_explicit_other_string_round_trips(self) -> None:
        """Any other explicit string round-trips — no normalization."""
        opts = DispatchOptions(permission_mode="acceptEdits")
        assert opts.permission_mode == "acceptEdits"


class TestSdkBackendReceivesDefaultPermissionMode:
    """``ClaudeAgentOptions`` is built with ``permission_mode='default'`` by default."""

    async def test_default_permission_mode_propagates_through_sdk_backend(self) -> None:
        """The SDK backend forwards the new default verbatim."""
        if _IMPORT_ERROR is not None:  # pragma: no cover
            import pytest

            pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")

        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])  # all other fields default
            await backend.execute(_envelope(), options=options)

        assert captured.get("permission_mode") == "default", (
            f"ClaudeAgentOptions should receive permission_mode='default' from "
            f"a default DispatchOptions; got {captured.get('permission_mode')!r}"
        )

    async def test_explicit_dont_ask_still_propagates_through_sdk_backend(self) -> None:
        """Explicit ``dontAsk`` is still threaded all the way through."""
        if _IMPORT_ERROR is not None:  # pragma: no cover
            import pytest

            pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")

        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(permission_mode="dontAsk", tools=["Read"])
            await backend.execute(_envelope(), options=options)

        assert captured.get("permission_mode") == "dontAsk"
