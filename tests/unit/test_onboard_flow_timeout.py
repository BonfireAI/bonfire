"""`run_front_door` shuts down cleanly on browser-close + timeout.

The original ``run_front_door`` did ``await conversation_done.wait()``
unguarded — if the browser closed mid-conversation, the CLI hung
forever until Ctrl-C. The fix races the wait against
``server.shutdown_event`` and a configurable wall-clock timeout so the
CLI exits cleanly with a distinct exception in either case.

Tests pin:

1. Browser-disconnect mid-conversation -> ``BrowserDisconnectedError``
   raised within timeout; ``write_config`` is NOT called.
2. Wall-clock timeout while browser stays open ->
   ``ConversationTimeoutError`` raised; ``write_config`` is NOT called.
3. Happy path — conversation completes -> Act III runs.
4. The named exceptions subclass useful builtins so existing callers
   that catch ``TimeoutError`` keep working.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bonfire.onboard import flow as flow_module
from bonfire.onboard.flow import (
    DEFAULT_CONVERSATION_TIMEOUT,
    BrowserDisconnectedError,
    ConversationTimeoutError,
    run_front_door,
)


def _make_server(loop_shutdown: asyncio.Event) -> MagicMock:
    """Build a FrontDoorServer mock with the minimum surface flow needs."""
    server = MagicMock()
    server.broadcast = AsyncMock()
    server.shutdown_event = loop_shutdown
    server.on_message = None
    return server


class TestExceptionShape:
    def test_browser_disconnected_is_runtime_error(self) -> None:
        # CLI catch-all paths often do ``except RuntimeError`` — make
        # sure that path still works.
        assert issubclass(BrowserDisconnectedError, RuntimeError)

    def test_conversation_timeout_is_timeout_error(self) -> None:
        # ``except TimeoutError`` is the idiomatic Python catch for
        # wall-clock budgets; preserve it.
        assert issubclass(ConversationTimeoutError, TimeoutError)

    def test_default_timeout_is_positive_finite_float(self) -> None:
        assert isinstance(DEFAULT_CONVERSATION_TIMEOUT, float)
        assert DEFAULT_CONVERSATION_TIMEOUT > 0


class TestBrowserDisconnect:
    """Browser closes mid-conversation: ``shutdown_event`` fires before
    ``conversation_done``. Flow MUST raise
    :class:`BrowserDisconnectedError` and MUST NOT advance to Act III.
    """

    @pytest.mark.asyncio
    async def test_disconnect_raises_browser_disconnected_error(self, tmp_path: Path) -> None:
        shutdown = asyncio.Event()
        server = _make_server(shutdown)

        # Pre-set shutdown so the wait returns immediately.
        shutdown.set()

        # Stub out Act I (run_scan) + Act II conversation.start so we
        # land at the wait-block instantly.
        with (
            patch.object(flow_module, "run_scan", new=AsyncMock()),
            patch.object(flow_module, "ConversationEngine") as ConvCls,
            patch.object(flow_module, "write_config") as write_config,
            patch.object(flow_module, "generate_config") as generate_config,
        ):
            conv = MagicMock()
            conv.start = AsyncMock()
            conv.profile = MagicMock()
            conv.is_complete = False
            ConvCls.return_value = conv
            generate_config.return_value = MagicMock(model_dump=lambda: {"config_toml": ""})

            with pytest.raises(BrowserDisconnectedError):
                # Sleep delay on the wait keeps the test fast — we
                # rely on FIRST_COMPLETED to fire because shutdown is
                # already set.
                await asyncio.wait_for(
                    run_front_door(
                        server,
                        tmp_path,
                        conversation_timeout=5.0,
                    ),
                    timeout=2.0,
                )

            # Act III MUST NOT run.
            write_config.assert_not_called()


class TestWallClockTimeout:
    """Browser stays open but user never answers: wait exceeds
    ``conversation_timeout`` -> :class:`ConversationTimeoutError`
    raised; Act III not entered.
    """

    @pytest.mark.asyncio
    async def test_timeout_raises_conversation_timeout_error(self, tmp_path: Path) -> None:
        # shutdown_event never fires; conversation_done never fires.
        shutdown = asyncio.Event()
        server = _make_server(shutdown)

        with (
            patch.object(flow_module, "run_scan", new=AsyncMock()),
            patch.object(flow_module, "ConversationEngine") as ConvCls,
            patch.object(flow_module, "write_config") as write_config,
            patch.object(flow_module, "generate_config") as generate_config,
        ):
            conv = MagicMock()
            conv.start = AsyncMock()
            conv.profile = MagicMock()
            conv.is_complete = False
            ConvCls.return_value = conv
            generate_config.return_value = MagicMock(model_dump=lambda: {"config_toml": ""})

            # Short timeout so the test runs in ~0.1s.
            with pytest.raises(ConversationTimeoutError):
                await run_front_door(
                    server,
                    tmp_path,
                    conversation_timeout=0.1,
                )

            write_config.assert_not_called()


class TestHappyPath:
    """When the conversation completes within budget, Act III runs and
    the returned config path comes from ``write_config``.

    Strategy: patch ``asyncio.Event`` as seen by ``flow_module`` so the
    ``conversation_done`` instance flow creates is captured. Make
    ``conversation.start`` set that event (mirrors the production code
    path where ``handle_answer`` would set it on the third answer).
    """

    @pytest.mark.asyncio
    async def test_completion_advances_to_act_iii(self, tmp_path: Path) -> None:
        shutdown = asyncio.Event()
        server = _make_server(shutdown)

        completion_path = tmp_path / "bonfire.toml"

        # Capture the conversation_done event so the fake start() can
        # fire it. flow_module creates the event AFTER constructing the
        # ConversationEngine but BEFORE awaiting start(), so by the
        # time start runs, the most-recently-created event is the
        # right one.
        real_event_cls = asyncio.Event
        created: list[asyncio.Event] = []

        def event_factory() -> asyncio.Event:
            ev = real_event_cls()
            created.append(ev)
            return ev

        async def fake_start(emit: Any) -> None:
            # Fire the conversation_done event the flow just created.
            # Last entry is the conversation_done one.
            assert created, "flow did not create conversation_done event"
            created[-1].set()

        with (
            patch.object(flow_module, "run_scan", new=AsyncMock()),
            patch.object(flow_module, "ConversationEngine") as ConvCls,
            patch.object(flow_module, "write_config") as write_config,
            patch.object(flow_module, "generate_config") as generate_config,
            patch.object(flow_module.asyncio, "Event", event_factory),
        ):
            conv = MagicMock()
            conv.start = fake_start
            conv.profile = MagicMock()
            conv.is_complete = True
            ConvCls.return_value = conv

            generate_config.return_value = MagicMock(
                model_dump=lambda: {"config_toml": "[bonfire]\n"}
            )
            write_config.return_value = completion_path

            result = await asyncio.wait_for(
                run_front_door(server, tmp_path, conversation_timeout=5.0),
                timeout=2.0,
            )

        assert result == completion_path
        write_config.assert_called_once()
        generate_config.assert_called_once()


class TestSignature:
    """The new keyword-only ``conversation_timeout`` parameter is the
    documented knob. ``None`` opts out (legacy behaviour).
    """

    def test_signature_exposes_conversation_timeout(self) -> None:
        import inspect

        sig = inspect.signature(run_front_door)
        param = sig.parameters.get("conversation_timeout")
        assert param is not None, "conversation_timeout kwarg missing"
        assert param.kind == inspect.Parameter.KEYWORD_ONLY
        assert param.default == DEFAULT_CONVERSATION_TIMEOUT
