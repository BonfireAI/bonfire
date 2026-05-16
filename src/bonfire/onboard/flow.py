# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Front Door session flow — composition root for the three-act onboarding.

Wires the scan orchestrator, narration engine, conversation engine, and
config generator into a single coherent flow:

- **Act I: Scan Theater** — run all scanners, interleave Falcor narration
- **Act II: Conversation** — three profiling questions via the conversation engine
- **Act III: Config Generation** — produce bonfire.toml from scan + profile data
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from bonfire.onboard.config_generator import generate_config, write_config
from bonfire.onboard.conversation import ConversationCompleteError, ConversationEngine
from bonfire.onboard.narration import NarrationEngine
from bonfire.onboard.orchestrator import run_scan
from bonfire.onboard.protocol import (
    FrontDoorMessage,
    ScanUpdate,
    ServerError,
    UserMessage,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from bonfire.onboard.server import FrontDoorServer

__all__ = [
    "DEFAULT_CONVERSATION_TIMEOUT",
    "BrowserDisconnectedError",
    "ConversationTimeoutError",
    "dispatch_user_message",
    "run_front_door",
]

_log = logging.getLogger(__name__)

# Default wall-clock cap on Act II (conversation). 5 minutes is long
# enough for a deliberate user, short enough that a closed-browser hang
# becomes a clean exit rather than an indefinite CLI block. Callers may
# override via ``run_front_door(..., conversation_timeout=...)``; pass
# ``None`` to disable the timeout entirely.
DEFAULT_CONVERSATION_TIMEOUT: float = 300.0


class BrowserDisconnectedError(RuntimeError):
    """Raised when the browser disconnects before the conversation completes.

    Surfaces the disconnect distinctly from a wall-clock timeout so the
    CLI can offer a tailored remediation message ("relaunch ``bonfire
    scan``") versus a stall message.
    """


class ConversationTimeoutError(TimeoutError):
    """Raised when Act II exceeds the configured wall-clock budget.

    Subclasses :class:`TimeoutError` so existing handlers that already
    catch built-in timeouts continue to work.
    """


async def dispatch_user_message(
    data: dict[str, Any],
    *,
    conversation: ConversationEngine,
    broadcast: Callable[[FrontDoorMessage], Awaitable[None]],
    conversation_done: asyncio.Event,
) -> None:
    """Route a single client frame into the conversation engine.

    Extracted from ``run_front_door``'s ``on_message`` closure so it is
    unit-testable. Mirrors the original closure semantics:

    - Non-``user_message`` frames are ignored.
    - Overlong payloads (>``MAX_USER_MESSAGE_LEN``) trigger a
      ``server_error`` frame with code ``message_too_long`` and never reach
      the conversation analyzer.
    - ``ConversationCompleteError`` after the third answer is broadcast as
      a polite ``server_error`` and is NOT propagated.
    - Once the conversation is complete, ``conversation_done`` is signalled
      so the outer ``run_front_door`` can advance to Act III.

    ``broadcast`` is the model-accepting emit callable (same shape as the
    ``ConversationEngine``'s ``emit`` parameter); ``run_front_door`` wraps
    it around ``server.broadcast`` with a ``model_dump`` adapter.
    """
    if data.get("type") != "user_message":
        return

    try:
        msg = UserMessage.model_validate(data)
    except ValidationError:
        await broadcast(
            ServerError(
                code="message_too_long",
                message="Message too long; please keep under 4 KiB.",
            )
        )
        return

    try:
        await conversation.handle_answer(msg.text, broadcast)
    except ConversationCompleteError as exc:
        await broadcast(
            ServerError(
                code="conversation_complete",
                message=str(exc),
            )
        )
        return

    if conversation.is_complete:
        conversation_done.set()


async def run_front_door(
    server: FrontDoorServer,
    project_path: Path,
    *,
    conversation_timeout: float | None = DEFAULT_CONVERSATION_TIMEOUT,
) -> Path:
    """Run the complete Front Door flow. Returns path to generated bonfire.toml.

    Orchestrates: scan → narration → conversation → config generation.
    The server must already be started. This function sets the server's
    ``on_message`` callback to route user answers to the conversation engine.

    ``conversation_timeout`` (seconds) caps Act II. If the browser
    disconnects before the user answers all three questions, raises
    :class:`BrowserDisconnectedError`. If the user simply walks away
    while the browser stays open, raises
    :class:`ConversationTimeoutError` after the budget elapses. Pass
    ``None`` to wait indefinitely (legacy behaviour).
    """
    # ------------------------------------------------------------------
    # Act I: Scan Theater
    # ------------------------------------------------------------------

    narration = NarrationEngine()
    scan_results: list[ScanUpdate] = []

    async def scan_emit(event: FrontDoorMessage) -> None:
        """Broadcast scan events and interleave narration."""
        await server.broadcast(event.model_dump())

        if isinstance(event, ScanUpdate):
            scan_results.append(event)
            narration_msg = narration.get_narration(event)
            if narration_msg is not None:
                await server.broadcast(narration_msg.model_dump())

    await run_scan(project_path, scan_emit)

    # Brief pause between scan and conversation
    await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # Act II: Conversation
    # ------------------------------------------------------------------

    conversation = ConversationEngine()
    conversation_done: asyncio.Event = asyncio.Event()

    async def conversation_emit(event: FrontDoorMessage) -> None:
        """Broadcast conversation events."""
        await server.broadcast(event.model_dump())

    async def on_message(data: dict[str, Any]) -> None:
        """Route incoming user messages to the conversation engine."""
        await dispatch_user_message(
            data,
            conversation=conversation,
            broadcast=conversation_emit,
            conversation_done=conversation_done,
        )

    # Start conversation (emits ConversationStart + Q1)
    await conversation.start(conversation_emit)

    # Install the message handler AFTER start so early messages
    # don't race with the engine's initial state.
    server.on_message = on_message

    # Wait for all 3 answers, racing against:
    #   - browser disconnect (server.shutdown_event fires when the last
    #     WebSocket client drops)
    #   - wall-clock timeout (configurable; defaults to
    #     DEFAULT_CONVERSATION_TIMEOUT)
    # Whichever fires first wins. The losing tasks are cancelled cleanly
    # so the loop returns to the caller (the CLI) without leaked tasks.
    done_task = asyncio.create_task(conversation_done.wait())
    shutdown_task = asyncio.create_task(server.shutdown_event.wait())
    pending: set[asyncio.Task[Any]] = {done_task, shutdown_task}
    try:
        finished, pending = await asyncio.wait(
            pending,
            timeout=conversation_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in pending:
            task.cancel()
        # Drain cancelled tasks so they don't dangle as "Task was
        # destroyed but it is pending!" warnings.
        for task in pending:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                # Swallow — we're already handling the race outcome.
                pass

    if done_task in finished:
        # Happy path: all three answers in, advance to Act III.
        pass
    elif shutdown_task in finished:
        _log.warning(
            "Front Door browser disconnected before conversation completed; "
            "aborting Act III. Re-run `bonfire scan` to retry."
        )
        raise BrowserDisconnectedError(
            "Browser closed before the onboarding conversation completed."
        )
    else:
        # Neither task finished — wall-clock timeout fired.
        _log.warning(
            "Front Door conversation timed out after %s seconds; "
            "aborting Act III. Re-run `bonfire scan` to retry.",
            conversation_timeout,
        )
        raise ConversationTimeoutError(
            f"Onboarding conversation did not complete within {conversation_timeout} seconds."
        )

    # ------------------------------------------------------------------
    # Act III: Config Generation
    # ------------------------------------------------------------------

    project_name = project_path.name

    config_event = generate_config(scan_results, conversation.profile, project_name)
    await server.broadcast(config_event.model_dump())

    config_path = write_config(config_event.config_toml, project_path)

    _log.info("Front Door flow complete. Config written to %s", config_path)
    return config_path
