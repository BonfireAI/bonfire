"""Front Door WebSocket message protocol.

Pydantic models for all messages exchanged between the WebSocket server
and the browser client. Uses ``type`` field as discriminator for tagged
union parsing.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel

__all__ = [
    "AllScansComplete",
    "ConfigGenerated",
    "ConversationStart",
    "FrontDoorMessage",
    "PasseleweMessage",
    "ScanCallback",
    "ScanComplete",
    "ScanStart",
    "ScanUpdate",
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


class PasseleweMessage(FrontDoorMessage):
    """A message from Passelewe -- narration, question, or reflection."""

    type: Literal["passelewe_message"] = "passelewe_message"
    text: str
    subtype: Literal["narration", "question", "reflection"]


class ConfigGenerated(FrontDoorMessage):
    """Generated bonfire.toml config ready for display."""

    type: Literal["config_generated"] = "config_generated"
    config_toml: str
    annotations: dict[str, str]


# ---------------------------------------------------------------------------
# Client -> Server
# ---------------------------------------------------------------------------


class UserMessage(FrontDoorMessage):
    """User's free-text response in the conversation."""

    type: Literal["user_message"] = "user_message"
    text: str


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_SERVER_TYPES: dict[str, type[FrontDoorMessage]] = {
    "scan_start": ScanStart,
    "scan_update": ScanUpdate,
    "scan_complete": ScanComplete,
    "all_scans_complete": AllScansComplete,
    "conversation_start": ConversationStart,
    "passelewe_message": PasseleweMessage,
    "config_generated": ConfigGenerated,
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
