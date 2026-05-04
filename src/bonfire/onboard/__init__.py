# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The Front Door — browser-based onboarding scan and conversation."""

from bonfire.onboard.protocol import (
    AllScansComplete,
    ConfigGenerated,
    ConversationStart,
    FalcorMessage,
    FrontDoorMessage,
    ScanComplete,
    ScanStart,
    ScanUpdate,
    UserMessage,
    parse_client_message,
    parse_server_message,
)
from bonfire.onboard.server import FrontDoorServer

__all__ = [
    "AllScansComplete",
    "ConfigGenerated",
    "ConversationStart",
    "FrontDoorMessage",
    "FrontDoorServer",
    "FalcorMessage",
    "ScanComplete",
    "ScanStart",
    "ScanUpdate",
    "UserMessage",
    "parse_client_message",
    "parse_server_message",
]
