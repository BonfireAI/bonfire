"""A rate-limit event with no info is logged once with a stable code and never fails the run."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk.types import (  # type: ignore[import-untyped]
    AssistantMessage,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
)

from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.protocols import DispatchOptions

try:
    from bonfire.dispatch.sdk_backend import RATE_LIMIT_EVENT_MALFORMED
except ImportError:
    RATE_LIMIT_EVENT_MALFORMED = None

LOGGER = "bonfire.dispatch.sdk_backend"


def _malformed() -> RateLimitEvent:
    return RateLimitEvent(rate_limit_info=None, uuid="uuid-1", session_id="session-1")  # type: ignore[arg-type]


def _text(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    msg = MagicMock(spec=AssistantMessage)
    msg.content = [block]
    return msg


def _result() -> MagicMock:
    msg = MagicMock(spec=ResultMessage)
    msg.total_cost_usd = 0.01
    msg.duration_ms = 1000
    msg.session_id = "sess-1"
    msg.result = None
    msg.is_error = False
    msg.errors = None
    return msg


async def _run(caplog, *events):
    async def mock_query(*, prompt="", options=None):
        for event in events:
            yield event

    envelope = Envelope(task="run something", agent_name="scout", model="claude-sonnet")
    options = DispatchOptions(model="claude-sonnet", max_turns=5, max_budget_usd=1.0, tools=[])
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(envelope, options=options)
    return out, [r for r in caplog.records if r.name == LOGGER]


async def test_malformed_event_alone_does_not_fail(caplog):
    out, _ = await _run(caplog, _malformed())
    assert out.status != TaskStatus.FAILED
    assert out.error is None


async def test_malformed_event_logs_one_warning_with_code(caplog):
    _, records = await _run(caplog, _malformed(), _text("ok"), _result())
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "rate_limit_event_malformed" in records[0].getMessage()


async def test_malformed_event_keeps_reading_the_stream(caplog):
    out, _ = await _run(caplog, _malformed(), _text("still here"), _result())
    assert out.status == TaskStatus.COMPLETED
    assert out.result == "still here"


def test_malformed_code_constant_value():
    assert RATE_LIMIT_EVENT_MALFORMED == "rate_limit_event_malformed"


@pytest.mark.parametrize("status", ["allowed", "allowed_warning"])
async def test_wellformed_events_are_not_reported_malformed(caplog, status):
    event = RateLimitEvent(RateLimitInfo(status=status), "uuid-1", "session-1")
    _, records = await _run(caplog, event, _text("ok"), _result())
    messages = [r.getMessage() for r in records]
    assert not any("rate_limit_event_malformed" in m for m in messages)
    if status == "allowed":
        assert records == []
    else:
        assert any("Rate limit warning" in m for m in messages)
