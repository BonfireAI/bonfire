"""Front Door session flow — composition root for the three-act onboarding.

Wires the scan orchestrator, narration engine, conversation engine, and
config generator into a single coherent flow:

- **Act I: Scan Theater** — run all scanners, interleave Passelewe narration
- **Act II: Conversation** — three profiling questions via the conversation engine
- **Act III: Config Generation** — produce bonfire.toml from scan + profile data
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bonfire.onboard.config_generator import generate_config, write_config
from bonfire.onboard.conversation import ConversationEngine
from bonfire.onboard.narration import NarrationEngine
from bonfire.onboard.orchestrator import run_scan
from bonfire.onboard.protocol import (
    FrontDoorMessage,
    ScanUpdate,
)

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.onboard.server import FrontDoorServer

__all__ = ["run_front_door"]

_log = logging.getLogger(__name__)


async def run_front_door(
    server: FrontDoorServer,
    project_path: Path,
) -> Path:
    """Run the complete Front Door flow. Returns path to generated bonfire.toml.

    Orchestrates: scan → narration → conversation → config generation.
    The server must already be started. This function sets the server's
    ``on_message`` callback to route user answers to the conversation engine.
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
        if data.get("type") != "user_message":
            return
        text = data.get("text", "")
        await conversation.handle_answer(text, conversation_emit)
        if conversation.is_complete:
            conversation_done.set()

    # Start conversation (emits ConversationStart + Q1)
    await conversation.start(conversation_emit)

    # Install the message handler AFTER start so early messages
    # don't race with the engine's initial state.
    server.on_message = on_message

    # Wait for all 3 answers.
    # NOTE: If the browser closes mid-conversation, this hangs until Ctrl-C.
    # Acceptable for v1 — a future improvement could race against shutdown_event.
    await conversation_done.wait()

    # ------------------------------------------------------------------
    # Act III: Config Generation
    # ------------------------------------------------------------------

    project_name = project_path.name

    config_event = generate_config(scan_results, conversation.profile, project_name)
    await server.broadcast(config_event.model_dump())

    config_path = write_config(config_event.config_toml, project_path)

    _log.info("Front Door flow complete. Config written to %s", config_path)
    return config_path
