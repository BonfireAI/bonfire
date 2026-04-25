"""RED tests for bonfire.onboard.protocol — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 19 tests per Sage §D6 Row 1. Verbatim v1 port. No innovations (conservative lens).
"""

from __future__ import annotations

import json

import pytest

from bonfire.onboard.protocol import (
    AllScansComplete,
    ConfigGenerated,
    ConversationStart,
    PasseleweMessage,
    ScanComplete,
    ScanStart,
    ScanUpdate,
    UserMessage,
    parse_client_message,
    parse_server_message,
)


class TestServerMessages:
    """Server-to-client message models."""

    def test_scan_start(self) -> None:
        msg = ScanStart(panels=["project_structure", "cli_toolchain", "claude_memory"])
        assert msg.type == "scan_start"
        assert len(msg.panels) == 3

    def test_scan_start_serialization_roundtrip(self) -> None:
        msg = ScanStart(panels=["git_state", "mcp_servers"])
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "scan_start"
        assert data["panels"] == ["git_state", "mcp_servers"]
        restored = ScanStart.model_validate(data)
        assert restored == msg

    def test_scan_update(self) -> None:
        msg = ScanUpdate(
            panel="cli_toolchain",
            label="python3",
            value="3.12.3",
            detail="via pyenv",
        )
        assert msg.type == "scan_update"
        assert msg.panel == "cli_toolchain"
        assert msg.label == "python3"
        assert msg.value == "3.12.3"
        assert msg.detail == "via pyenv"

    def test_scan_update_minimal(self) -> None:
        msg = ScanUpdate(panel="git_state", label="branch", value="main")
        assert msg.detail == ""

    def test_scan_complete(self) -> None:
        msg = ScanComplete(panel="project_structure", item_count=7)
        assert msg.type == "scan_complete"
        assert msg.panel == "project_structure"
        assert msg.item_count == 7

    def test_all_scans_complete(self) -> None:
        msg = AllScansComplete(total_items=42)
        assert msg.type == "all_scans_complete"
        assert msg.total_items == 42

    def test_conversation_start(self) -> None:
        msg = ConversationStart()
        assert msg.type == "conversation_start"

    def test_passelewe_message_narration(self) -> None:
        msg = PasseleweMessage(text="The collection grows.", subtype="narration")
        assert msg.type == "passelewe_message"
        assert msg.text == "The collection grows."
        assert msg.subtype == "narration"

    def test_passelewe_message_subtypes(self) -> None:
        for subtype in ("narration", "question", "reflection"):
            msg = PasseleweMessage(text="Test.", subtype=subtype)
            assert msg.subtype == subtype

    def test_config_generated(self) -> None:
        msg = ConfigGenerated(
            config_toml="[bonfire]\npersona = 'passelewe'\n",
            annotations={"persona": "Derived from conversation Q1"},
        )
        assert msg.type == "config_generated"
        assert "persona" in msg.config_toml
        assert "persona" in msg.annotations


class TestClientMessages:
    """Client-to-server message models."""

    def test_user_message(self) -> None:
        msg = UserMessage(text="I test first, then build.")
        assert msg.type == "user_message"
        assert msg.text == "I test first, then build."

    def test_user_message_serialization(self) -> None:
        msg = UserMessage(text="Ship it.")
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "user_message"
        assert data["text"] == "Ship it."


class TestMessageParsing:
    """parse_client_message and parse_server_message from raw JSON."""

    def test_parse_client_user_message(self) -> None:
        raw = '{"type": "user_message", "text": "hello"}'
        msg = parse_client_message(raw)
        assert isinstance(msg, UserMessage)
        assert msg.text == "hello"

    def test_parse_server_scan_start(self) -> None:
        raw = '{"type": "scan_start", "panels": ["a", "b"]}'
        msg = parse_server_message(raw)
        assert isinstance(msg, ScanStart)
        assert msg.panels == ["a", "b"]

    def test_parse_server_scan_update(self) -> None:
        raw = json.dumps(
            {
                "type": "scan_update",
                "panel": "cli",
                "label": "git",
                "value": "2.43.0",
                "detail": "",
            }
        )
        msg = parse_server_message(raw)
        assert isinstance(msg, ScanUpdate)
        assert msg.label == "git"

    def test_parse_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            parse_client_message("not json")

    def test_parse_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            parse_client_message('{"type": "bogus", "text": "x"}')


class TestFrozenModels:
    """All protocol messages must be immutable."""

    def test_scan_start_frozen(self) -> None:
        msg = ScanStart(panels=["a"])
        with pytest.raises(Exception):  # noqa: B017
            msg.panels = ["b"]  # type: ignore[misc]

    def test_user_message_frozen(self) -> None:
        msg = UserMessage(text="hi")
        with pytest.raises(Exception):  # noqa: B017
            msg.text = "bye"  # type: ignore[misc]
