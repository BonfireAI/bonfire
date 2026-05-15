"""RED contract tests — WS user-message size cap.

Closes Mirror Probe N+1 finding **S1.8** — CPU DOS via large WebSocket
message.

The defect:

``UserMessage.text`` (``onboard/protocol.py``) has no length cap.
``websockets`` will deliver up to 1 MiB per frame by default. A 1 MiB ASCII
payload runs through ``ConversationEngine.handle_answer`` ->
``_analyze_q1``/``_q2``/``_q3``, each of which calls ``text.lower().split()``
(yielding ~250k words) plus a set-membership scan per word — O(N·K) per
analyzer, single-event-loop blocking. The scan-emit pipeline shares the same
loop. A CSWSH-style attacker (W5.A) replaying N such messages halts the
process.

The contract this file pins:

1. ``UserMessage(text=…)`` rejects strings longer than the cap at
   construction time, raising ``pydantic.ValidationError``.
2. The cap is exactly 4096 characters (Sage default; bikeshed-locked here
   so a future widener has to defend the change).
3. ``parse_client_message`` on overlong wire JSON also raises (defense in
   depth — the parser, not just the model).
4. ``flow.dispatch_user_message`` (or whatever surface the Warrior extracts
   from ``run_front_door``'s ``on_message`` closure) catches the
   ``ValidationError`` and broadcasts a polite ``server_error``-shaped frame
   on the server, WITHOUT invoking ``ConversationEngine.handle_answer``.
5. Off-by-one tightness: 4096 bytes exactly = OK; 4097 = rejected.

Knight scope: write the RED tests. Warrior scope: add the
``max_length=4096`` Field on ``UserMessage.text``, extract / harden
``flow``'s dispatch path, and add the ``server_error`` frame type.

Open design questions (FYI for Warrior + Sage):

- ``server_error`` frame type — current protocol has no error message
  class. Warrior will need to add one. Tests assert the broadcast happens
  but accept ``server_error`` as the typed name; if Sage prefers a
  different name (``ServerError`` / ``error_message`` / ``front_door_error``)
  the test asserts via substring match so the cosmetic name is bikeshed-free.
- Cap configurability — 4096 hardcoded here. If Sage rules in favor of a
  ``SecurityHooksConfig``-style knob, the off-by-one tests will need a
  fixture override. Defer to Sage on first review.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

# Exact-cap constant. If Sage moves the cap, this constant is the single
# source of truth for the test suite.
MAX_USER_MESSAGE_LEN = 4096


# ---------------------------------------------------------------------------
# UserMessage Pydantic-level cap
# ---------------------------------------------------------------------------


class TestUserMessageCapAtConstruction:
    """``UserMessage(text=…)`` rejects overlong payloads at Pydantic
    construction time via a ``max_length`` Field constraint."""

    def test_overlong_text_raises_validation_error(self) -> None:
        from bonfire.onboard.protocol import UserMessage

        too_long = "x" * (MAX_USER_MESSAGE_LEN + 1)
        with pytest.raises(ValidationError):
            UserMessage(text=too_long)

    def test_one_megabyte_payload_raises(self) -> None:
        # The actual attack shape: a 1 MiB ASCII payload (the websockets
        # default per-frame ceiling). Must be rejected before it reaches
        # the analyzers.
        from bonfire.onboard.protocol import UserMessage

        megabyte = "a" * (1024 * 1024)
        with pytest.raises(ValidationError):
            UserMessage(text=megabyte)

    def test_exactly_at_cap_is_accepted(self) -> None:
        from bonfire.onboard.protocol import UserMessage

        at_cap = "y" * MAX_USER_MESSAGE_LEN
        msg = UserMessage(text=at_cap)
        assert len(msg.text) == MAX_USER_MESSAGE_LEN

    def test_short_text_is_accepted(self) -> None:
        from bonfire.onboard.protocol import UserMessage

        msg = UserMessage(text="hello there")
        assert msg.text == "hello there"


# ---------------------------------------------------------------------------
# Wire-parser defense in depth
# ---------------------------------------------------------------------------


class TestParseClientMessageRejectsOverlong:
    """``parse_client_message`` on overlong JSON must surface the same
    validation failure. The server already calls this implicitly when it
    constructs models; the explicit assertion guards against a future
    parser refactor that bypasses Pydantic."""

    def test_parse_client_message_rejects_overlong_text(self) -> None:
        import json

        from bonfire.onboard.protocol import parse_client_message

        too_long = "z" * (MAX_USER_MESSAGE_LEN + 1)
        raw = json.dumps({"type": "user_message", "text": too_long})
        # ValidationError is a ValueError subclass — accept either.
        with pytest.raises((ValidationError, ValueError)):
            parse_client_message(raw)


# ---------------------------------------------------------------------------
# Flow dispatch path — overlong payload does NOT reach the analyzer
# ---------------------------------------------------------------------------


class TestFlowDispatchRejectsOverlong:
    """``flow.dispatch_user_message`` (or the equivalent extracted surface)
    catches a too-long payload and broadcasts a polite error frame, WITHOUT
    invoking ``ConversationEngine.handle_answer``.

    The Warrior extracts the ``on_message`` closure inside ``run_front_door``
    to a module-level helper named ``dispatch_user_message`` so it is unit
    testable. Today the closure is private; importing it RED-fails.
    """

    @pytest.mark.asyncio
    async def test_overlong_payload_does_not_invoke_analyzer(self) -> None:
        from bonfire.onboard import flow as flow_module

        # Importable surface — the Warrior must expose this.
        dispatch = flow_module.dispatch_user_message

        # Build a fake conversation engine with a spied handle_answer.
        conversation = AsyncMock()
        conversation.is_complete = False
        # Spy emit / broadcast.
        broadcast = AsyncMock()
        conversation_done = AsyncMock()

        too_long = "x" * (MAX_USER_MESSAGE_LEN + 1)
        data: dict[str, Any] = {"type": "user_message", "text": too_long}

        # Must NOT raise — must catch ValidationError and emit error frame.
        await dispatch(
            data,
            conversation=conversation,
            broadcast=broadcast,
            conversation_done=conversation_done,
        )

        # CRITICAL: the analyzer-driving handle_answer was NOT called.
        conversation.handle_answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_overlong_payload_broadcasts_error_frame(self) -> None:
        from bonfire.onboard import flow as flow_module

        dispatch = flow_module.dispatch_user_message

        conversation = AsyncMock()
        conversation.is_complete = False
        broadcast = AsyncMock()
        conversation_done = AsyncMock()

        too_long = "x" * (MAX_USER_MESSAGE_LEN + 1)
        data: dict[str, Any] = {"type": "user_message", "text": too_long}

        await dispatch(
            data,
            conversation=conversation,
            broadcast=broadcast,
            conversation_done=conversation_done,
        )

        # Some error frame must have been broadcast. Substring-match on
        # the serialized form so the exact type name ("server_error" vs
        # "error_message" vs whatever Sage chooses) stays bikeshed-free.
        assert broadcast.await_count >= 1
        broadcast_payloads = [call.args[0] for call in broadcast.await_args_list]
        joined = repr(broadcast_payloads).lower()
        assert "error" in joined, f"no error frame broadcast: {broadcast_payloads!r}"
        assert "too long" in joined or "too_long" in joined or "message_too_long" in joined, (
            f"error frame does not signal length cause: {broadcast_payloads!r}"
        )

    @pytest.mark.asyncio
    async def test_normal_payload_reaches_analyzer(self) -> None:
        """Negative test — a normal-length payload IS forwarded to the
        conversation engine. Off-by-one canary that the cap isn't
        over-tightened."""
        from bonfire.onboard import flow as flow_module

        dispatch = flow_module.dispatch_user_message

        conversation = AsyncMock()
        conversation.is_complete = False
        broadcast = AsyncMock()
        conversation_done = AsyncMock()

        data: dict[str, Any] = {
            "type": "user_message",
            "text": "I shipped a small CLI last week and I'm proud of it.",
        }

        await dispatch(
            data,
            conversation=conversation,
            broadcast=broadcast,
            conversation_done=conversation_done,
        )

        conversation.handle_answer.assert_awaited_once()
