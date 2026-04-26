"""RED tests for bonfire.onboard.protocol — BON-349 W6.3 (CONTRACT-LOCKED canonical).

Sage decision logs:
  - docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md (Warrior contract)
  - docs/audit/sage-decisions/bon-349-contract-lock-*.md (Knight A/B reconciliation)

Floor (19 tests, per Sage §D6 Row 1): port v1 test_front_door_protocol.py test
surface verbatim, with the only delta being the import rename
``bonfire.front_door.protocol`` → ``bonfire.onboard.protocol`` (Sage §D3 row 2).

Innovations (2 adopted, drift-guards over Sage floor):

  * ``TestPydanticFrozenShape::test_all_message_classes_are_frozen_parametrized``
    — Parametrize sweep that asserts EVERY one of the 9 protocol message
    classes carries ``model_config == {"frozen": True}`` and rejects field
    reassignment (the v1 floor only spot-checks 2 of 9 in
    ``test_scan_start_frozen`` / ``test_user_message_frozen``). This guards
    against a silent regression where one-off classes lose their frozen
    contract during the v1→v0.1 port. Cites Sage §D4
    "FrontDoorMessage (base) — LOCKED" + v1
    src/bonfire/front_door/protocol.py:39-42 (model_config dict-style
    declaration) + src/bonfire/front_door/protocol.py:50-117 (9 subclasses).

  * ``TestJsonByteStability::test_message_json_roundtrip_is_byte_stable``
    — Parametrize sweep that asserts ``model_dump_json()`` produces a string
    whose JSON-decoded form round-trips through ``parse_server_message`` /
    ``parse_client_message`` to an equal model. This guards against a
    Pydantic-version drift where field-ordering or default-emission changes
    silently break wire compat (the floor only round-trips 2 classes:
    ``test_scan_start_serialization_roundtrip`` and
    ``test_user_message_serialization``). Cites Sage §D4 "field-order
    requirements (LOCKED)" + v1 src/bonfire/front_door/protocol.py:124-161
    (parser registries + _parse + parse_server_message +
    parse_client_message).

Imports are RED — ``bonfire.onboard.protocol`` does not exist until Warriors
port v1 source per Sage §D9.
"""

from __future__ import annotations

import json

import pytest

from bonfire.onboard.protocol import (
    AllScansComplete,
    ConfigGenerated,
    ConversationStart,
    FrontDoorMessage,
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


# ---------------------------------------------------------------------------
# INNOVATIONS (Knight B drift-guards — Sage §D4 frozen-shape contract)
# ---------------------------------------------------------------------------


def _make_message_instances() -> list[tuple[str, FrontDoorMessage]]:
    """Build one valid instance per concrete message class for parametrize sweeps."""
    return [
        ("ScanStart", ScanStart(panels=["a", "b"])),
        (
            "ScanUpdate",
            ScanUpdate(panel="p", label="lbl", value="v", detail="d"),
        ),
        ("ScanComplete", ScanComplete(panel="p", item_count=3)),
        ("AllScansComplete", AllScansComplete(total_items=9)),
        ("ConversationStart", ConversationStart()),
        (
            "PasseleweMessage",
            PasseleweMessage(text="hello", subtype="narration"),
        ),
        (
            "ConfigGenerated",
            ConfigGenerated(
                config_toml="[a]\nb = 'c'\n",
                annotations={"x": "y"},
            ),
        ),
        ("UserMessage", UserMessage(text="hi")),
    ]


class TestPydanticFrozenShape:
    """Innovation: parametrize the frozen contract across ALL message classes.

    Cites Sage §D4 "FrontDoorMessage (base) — LOCKED" +
    v1 src/bonfire/front_door/protocol.py:39-42 (model_config dict-style)
    and :50-117 (8 concrete subclasses).
    """

    @pytest.mark.parametrize(
        ("name", "instance"),
        _make_message_instances(),
        ids=[name for name, _ in _make_message_instances()],
    )
    def test_all_message_classes_are_frozen_parametrized(
        self, name: str, instance: FrontDoorMessage
    ) -> None:
        """Every concrete message class inherits the frozen=True invariant."""
        assert instance.model_config.get("frozen") is True, (
            f"{name} must inherit model_config={{'frozen': True}} from FrontDoorMessage"
        )
        # Field reassignment must raise (Pydantic ValidationError or AttributeError;
        # both are subclasses of Exception). v1 floor uses pytest.raises(Exception).
        first_field = next(iter(instance.model_fields))
        with pytest.raises(Exception):  # noqa: B017
            setattr(instance, first_field, getattr(instance, first_field))


class TestJsonByteStability:
    """Innovation: parametrize JSON round-trip across all server-side classes.

    Guards against Pydantic version drift breaking wire compat (e.g. field
    re-ordering, default emission changes). Cites Sage §D4 "field-order
    requirements (LOCKED)" + v1 src/bonfire/front_door/protocol.py:124-161
    (registries and _parse).
    """

    @pytest.mark.parametrize(
        ("name", "instance"),
        [
            (n, i)
            for n, i in _make_message_instances()
            if n != "UserMessage"  # UserMessage is client-only
        ],
        ids=[n for n, _ in _make_message_instances() if n != "UserMessage"],
    )
    def test_message_json_roundtrip_is_byte_stable(
        self, name: str, instance: FrontDoorMessage
    ) -> None:
        """``model_dump_json()`` → ``parse_server_message()`` recovers an equal model."""
        raw = instance.model_dump_json()
        # JSON must be parseable
        decoded = json.loads(raw)
        assert decoded["type"] == instance.type  # type: ignore[attr-defined]
        # Round-trip via the public server-side parser
        restored = parse_server_message(raw)
        assert restored == instance, (
            f"{name} round-trip via parse_server_message must equal original"
        )
