# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the petri-box headless conversational driver.

Covers:

1. URL parsing from a simulated ``bonfire scan`` stdout line.
2. Event handler dispatch — every server event type from the protocol
   reaches the right handler exactly once.
3. Interleaved ``scan_update`` / ``scan_complete`` handling — a
   ``scan_complete`` from one panel arriving while another panel is
   still emitting ``scan_update``s does NOT terminate the driver, and
   subsequent ``scan_update``s on the still-running panel are still
   handled. (Major-correctness-bug scenario flagged by the PR #70 self
   review of the state-machine diagram.)
4. ``config_generated`` is the only event that sets the driver's done
   flag, and unknown event types log a warning without crashing.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

_DRIVER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "petri_conversational_driver.py"
_spec = importlib.util.spec_from_file_location("petri_conversational_driver", _DRIVER_PATH)
assert _spec is not None and _spec.loader is not None
driver = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve cls.__module__ in sys.modules.
sys.modules["petri_conversational_driver"] = driver
_spec.loader.exec_module(driver)


# ---------------------------------------------------------------------------
# 1. URL parsing
# ---------------------------------------------------------------------------


class TestParseWsUrl:
    def test_parses_http_url_and_converts_to_ws(self) -> None:
        line = "Front Door listening at http://127.0.0.1:53219"
        assert driver.parse_ws_url(line) == "ws://127.0.0.1:53219/ws"

    def test_parses_with_trailing_newline(self) -> None:
        line = "Front Door listening at http://127.0.0.1:8080\n"
        assert driver.parse_ws_url(line) == "ws://127.0.0.1:8080/ws"

    def test_returns_none_when_no_url(self) -> None:
        assert driver.parse_ws_url("Waiting for browser connection...") is None

    def test_returns_none_for_empty_line(self) -> None:
        assert driver.parse_ws_url("") is None

    def test_extracts_url_from_noisy_line(self) -> None:
        line = "  Front Door listening at http://127.0.0.1:65535  "
        assert driver.parse_ws_url(line) == "ws://127.0.0.1:65535/ws"


# ---------------------------------------------------------------------------
# 2. Event handler dispatch
# ---------------------------------------------------------------------------


def _evt(type_: str, **fields: Any) -> dict[str, Any]:
    """Build a server event dict (matches Pydantic dump shape)."""
    return {"type": type_, **fields}


@pytest.fixture
def drv() -> Any:
    """A driver with default canned answers and a quiet logger."""
    return driver.ConversationalDriver(logger=logging.getLogger("test"))


class TestEventDispatch:
    async def test_scan_start_does_not_reply_and_is_not_done(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt("scan_start", panels=["project_structure", "cli_toolchain"])
        )
        assert reply is None
        assert drv.is_done is False

    async def test_scan_update_does_not_reply_and_is_not_done(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt(
                "scan_update",
                panel="project_structure",
                label="Python files",
                value="42",
                detail="",
            )
        )
        assert reply is None
        assert drv.is_done is False

    async def test_scan_complete_does_not_reply_and_is_not_done(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt("scan_complete", panel="project_structure", item_count=7)
        )
        assert reply is None
        assert drv.is_done is False, "scan_complete must NOT terminate the driver"

    async def test_all_scans_complete_does_not_reply_and_is_not_done(self, drv: Any) -> None:
        reply = await drv.handle_event(_evt("all_scans_complete", total_items=42))
        assert reply is None
        assert drv.is_done is False

    async def test_conversation_start_does_not_reply(self, drv: Any) -> None:
        reply = await drv.handle_event(_evt("conversation_start"))
        assert reply is None
        assert drv.is_done is False

    async def test_falcor_narration_does_not_reply(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt("falcor_message", text="A spark catches.", subtype="narration")
        )
        assert reply is None
        assert drv.is_done is False

    async def test_falcor_reflection_does_not_reply(self, drv: Any) -> None:
        reply = await drv.handle_event(_evt("falcor_message", text="Noted.", subtype="reflection"))
        assert reply is None
        assert drv.is_done is False

    async def test_falcor_question_replies_with_user_message(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt(
                "falcor_message",
                text="Tell me about the last thing you built that you were proud of.",
                subtype="question",
            )
        )
        assert reply is not None
        assert reply["type"] == "user_message"
        assert isinstance(reply["text"], str)
        assert reply["text"].strip() != ""
        assert drv.is_done is False

    async def test_three_questions_get_three_distinct_canned_answers(self, drv: Any) -> None:
        replies = []
        for _ in range(3):
            reply = await drv.handle_event(_evt("falcor_message", text="…", subtype="question"))
            assert reply is not None
            replies.append(reply["text"])
        # Driver should walk through its canned answer table in order.
        assert len(set(replies)) == 3, "Each question should get a distinct canned answer"

    async def test_question_after_canned_answers_exhausted_falls_back_safely(
        self, drv: Any
    ) -> None:
        for _ in range(3):
            await drv.handle_event(_evt("falcor_message", text="…", subtype="question"))
        # A 4th question should not crash; driver returns *some* user_message.
        reply = await drv.handle_event(_evt("falcor_message", text="…", subtype="question"))
        assert reply is not None
        assert reply["type"] == "user_message"

    async def test_config_generated_marks_done(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt(
                "config_generated",
                config_toml="[bonfire]\n",
                annotations={"bonfire.version": "Conversation"},
            )
        )
        assert reply is None
        assert drv.is_done is True

    async def test_unknown_event_type_logs_warning_does_not_crash(
        self, caplog: pytest.LogCaptureFixture, drv: Any
    ) -> None:
        with caplog.at_level(logging.WARNING):
            reply = await drv.handle_event(_evt("invented_event_type", payload="anything"))
        assert reply is None
        assert drv.is_done is False
        assert any("invented_event_type" in rec.message for rec in caplog.records)

    async def test_handle_event_accepts_raw_json_string(self, drv: Any) -> None:
        raw = json.dumps(_evt("scan_update", panel="git_state", label="branch", value="v0.1"))
        reply = await drv.handle_event(raw)
        assert reply is None

    async def test_handle_event_accepts_dict(self, drv: Any) -> None:
        reply = await drv.handle_event(
            _evt("scan_update", panel="git_state", label="branch", value="v0.1")
        )
        assert reply is None

    async def test_invalid_json_string_logs_and_does_not_crash(
        self, caplog: pytest.LogCaptureFixture, drv: Any
    ) -> None:
        with caplog.at_level(logging.WARNING):
            reply = await drv.handle_event("{not valid json")
        assert reply is None
        assert drv.is_done is False


# ---------------------------------------------------------------------------
# 3. Interleaved scan_complete handling — the bug the spec diagram has
# ---------------------------------------------------------------------------


class TestInterleavedScanComplete:
    async def test_scan_complete_is_not_a_barrier(self, drv: Any) -> None:
        """Panel A's scan_complete arriving before panel B's last scan_update
        must NOT terminate the scan phase. Per orchestrator.py:104-110 each
        panel emits ScanComplete the instant *its* scan() returns, while the
        other panels are still running and emitting scan_updates. The driver
        must process every scan_update it sees, regardless of order.
        """
        # Track which scan_updates the driver successfully processed.
        sequence = [
            _evt("scan_start", panels=["A", "B"]),
            _evt("scan_update", panel="A", label="x", value="1"),
            _evt("scan_complete", panel="A", item_count=1),
            # Panel B is STILL emitting after A has completed:
            _evt("scan_update", panel="B", label="y", value="2"),
            _evt("scan_update", panel="B", label="z", value="3"),
            _evt("scan_complete", panel="B", item_count=2),
            _evt("all_scans_complete", total_items=3),
        ]
        for event in sequence:
            reply = await drv.handle_event(event)
            assert reply is None
            assert drv.is_done is False, (
                f"Driver terminated prematurely on event {event['type']}; "
                "only config_generated should set is_done."
            )

        # After ALL of the above events, driver must have observed both panels'
        # updates. The driver records every scan_update it processes.
        observed_panels = {u["panel"] for u in drv.scan_updates_seen}
        assert observed_panels == {"A", "B"}

    async def test_full_session_with_interleaving_terminates_only_on_config(self, drv: Any) -> None:
        """End-to-end interleaved sequence including conversation. is_done must
        flip on config_generated and not before.
        """
        events: list[dict[str, Any]] = [
            _evt("scan_start", panels=["A", "B"]),
            _evt("scan_update", panel="A", label="x", value="1"),
            _evt("scan_complete", panel="A", item_count=1),
            _evt("scan_update", panel="B", label="y", value="2"),
            _evt("scan_complete", panel="B", item_count=1),
            _evt("all_scans_complete", total_items=2),
            _evt("conversation_start"),
            _evt("falcor_message", text="Q1?", subtype="question"),
            _evt("falcor_message", text="r1", subtype="reflection"),
            _evt("falcor_message", text="Q2?", subtype="question"),
            _evt("falcor_message", text="r2", subtype="reflection"),
            _evt("falcor_message", text="Q3?", subtype="question"),
            _evt("falcor_message", text="r3", subtype="reflection"),
        ]
        for evt in events:
            await drv.handle_event(evt)
            assert drv.is_done is False

        # Only config_generated terminates the driver.
        await drv.handle_event(_evt("config_generated", config_toml="x", annotations={}))
        assert drv.is_done is True


# ---------------------------------------------------------------------------
# 4. Custom canned answers
# ---------------------------------------------------------------------------


class TestCustomAnswers:
    async def test_custom_answers_are_returned_in_order(self) -> None:
        custom = {
            1: "answer one",
            2: "answer two",
            3: "answer three",
        }
        d = driver.ConversationalDriver(answers=custom, logger=logging.getLogger("test"))
        replies = []
        for _ in range(3):
            reply = await d.handle_event(_evt("falcor_message", text="?", subtype="question"))
            assert reply is not None
            replies.append(reply["text"])
        assert replies == ["answer one", "answer two", "answer three"]
