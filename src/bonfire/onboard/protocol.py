# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Front Door WebSocket message protocol.

Pydantic models for all messages exchanged between the WebSocket server
and the browser client. Uses ``type`` field as discriminator for tagged
union parsing.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Final, Literal

from pydantic import BaseModel, Field

# Max byte/char length of a single ``user_message.text`` frame. Bounds a
# CPU-DoS shape against the WebSocket front-door: ``websockets`` defaults
# to 1 MiB per frame, and ``ConversationEngine`` analyzers iterate
# ``text.lower().split()`` on the single event loop, so an attacker-sized
# frame would stall the loop. 4 KiB is long enough for the real
# Q1/Q2/Q3 free-text answers and short enough to bound per-frame
# analyzer cost. Tightening this constant is fine; widening requires a
# fresh DoS bracket.
MAX_USER_MESSAGE_LEN: Final = 4096

__all__ = [
    "MAX_USER_MESSAGE_LEN",
    "AllScansComplete",
    "ConfigGenerated",
    "ConversationStart",
    "FrontDoorMessage",
    "FalcorMessage",
    "ScanCallback",
    "ScanComplete",
    "ScanStart",
    "ScanUpdate",
    "ServerError",
    "UserMessage",
    "parse_client_message",
    "parse_server_message",
]


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class FrontDoorMessage(BaseModel):
    """Base for all Front Door WebSocket messages."""

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Server -> Client
# ---------------------------------------------------------------------------


class ScanStart(FrontDoorMessage):
    """Sent when the scan begins. Lists all panel names."""

    type: Literal["scan_start"] = "scan_start"
    panels: list[str]


class ScanUpdate(FrontDoorMessage):
    """A single discovery within a scan panel."""

    type: Literal["scan_update"] = "scan_update"
    panel: str
    label: str
    value: str
    detail: str = ""


ScanCallback = Callable[[ScanUpdate], Awaitable[None]]
"""Async callback for streaming scan events."""


class ScanComplete(FrontDoorMessage):
    """One scan panel has finished."""

    type: Literal["scan_complete"] = "scan_complete"
    panel: str
    item_count: int


class AllScansComplete(FrontDoorMessage):
    """All scan panels have finished."""

    type: Literal["all_scans_complete"] = "all_scans_complete"
    total_items: int


class ConversationStart(FrontDoorMessage):
    """Transition from scan phase to conversation phase."""

    type: Literal["conversation_start"] = "conversation_start"


class FalcorMessage(FrontDoorMessage):
    """A message from Falcor -- narration, question, or reflection."""

    type: Literal["falcor_message"] = "falcor_message"
    text: str
    subtype: Literal["narration", "question", "reflection"]


class ConfigGenerated(FrontDoorMessage):
    """Generated bonfire.toml config ready for display."""

    type: Literal["config_generated"] = "config_generated"
    config_toml: str
    annotations: dict[str, str]


class ServerError(FrontDoorMessage):
    """A typed error frame from the server.

    Used by the flow layer to surface application-level errors (e.g. attempting
    to send a user_message after the conversation has completed) back to the
    browser client.
    """

    type: Literal["server_error"] = "server_error"
    code: str
    message: str


# ---------------------------------------------------------------------------
# Client -> Server
# ---------------------------------------------------------------------------


class UserMessage(FrontDoorMessage):
    """User's free-text response in the conversation.

    ``text`` is capped at ``MAX_USER_MESSAGE_LEN`` (4 KiB) at construction
    time. Overlong payloads raise ``pydantic.ValidationError`` before any
    downstream analyzer sees them, closing the WebSocket CPU-DOS surface.
    """

    type: Literal["user_message"] = "user_message"
    text: Annotated[str, Field(max_length=MAX_USER_MESSAGE_LEN)]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_SERVER_TYPES: dict[str, type[FrontDoorMessage]] = {
    "scan_start": ScanStart,
    "scan_update": ScanUpdate,
    "scan_complete": ScanComplete,
    "all_scans_complete": AllScansComplete,
    "conversation_start": ConversationStart,
    "falcor_message": FalcorMessage,
    "config_generated": ConfigGenerated,
    "server_error": ServerError,
}

_CLIENT_TYPES: dict[str, type[FrontDoorMessage]] = {
    "user_message": UserMessage,
}


def _parse(raw: str, registry: dict[str, type[FrontDoorMessage]]) -> FrontDoorMessage:
    """Parse a raw JSON string into the appropriate message model."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON: {exc}"
        raise ValueError(msg) from exc
    msg_type = data.get("type")
    cls = registry.get(msg_type) if msg_type else None
    if cls is None:
        msg = f"Unknown message type: {msg_type!r}"
        raise ValueError(msg)
    return cls.model_validate(data)


def parse_client_message(raw: str) -> FrontDoorMessage:
    """Parse a raw JSON string from the browser client."""
    return _parse(raw, _CLIENT_TYPES)


def parse_server_message(raw: str) -> FrontDoorMessage:
    """Parse a raw JSON string from the server (for testing)."""
    return _parse(raw, _SERVER_TYPES)
