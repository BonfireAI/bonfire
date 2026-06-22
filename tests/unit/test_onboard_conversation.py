# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for ConversationEngine concurrency safety and typed completion error.

Regression coverage for: handle_answer mutex (so back-to-back user_message
frames don't double-increment _turn), typed ConversationCompleteError (so
the flow layer can emit a typed error frame instead of swallowing a
bare RuntimeError), and lazy-bound asyncio.Lock (so the engine survives
re-use across asyncio.run blocks).

Imports of ConversationCompleteError and the _lock attribute are deferred to
test bodies so that collection succeeds even before the Warrior implements the
new interface. Each test that needs the new symbol will fail at runtime with a
clear ImportError or AttributeError, not at collection time.
"""

from __future__ import annotations

import asyncio

import pytest

from bonfire.onboard.conversation import ConversationEngine
from bonfire.onboard.protocol import FalcorMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _drive_to_completion(engine: ConversationEngine) -> list[object]:
    """Drive engine through all 3 questions; return all emitted messages."""
    emitted: list[object] = []

    async def emit(msg: object) -> None:
        emitted.append(msg)

    await engine.start(emit)
    await engine.handle_answer("I built a distributed cache layer.", emit)
    await engine.handle_answer("I sketch the data model first.", emit)
    await engine.handle_answer("They don't understand context at all.", emit)
    return emitted


# ---------------------------------------------------------------------------
# TestHandleAnswerConcurrency
# ---------------------------------------------------------------------------


class TestHandleAnswerConcurrency:
    """handle_answer must be protected by an asyncio.Lock.

    Without the lock, two interleaved calls can double-increment _turn past
    the same question — both coroutines read _turn == 1, both advance to 2,
    and Q3 is never asked.  With the lock the calls are serialised: the
    first finishes completely (reads Q1, advances _turn to 2), then the
    second runs (reads Q2, advances _turn to 3).
    """

    async def test_handle_answer_holds_lock_under_interleave(self) -> None:
        """Two concurrent handle_answer calls must serialise via the lock.

        After start() sets _turn=1, gathering two handle_answer calls
        concurrently must produce _turn==3 (not 1 or 4), because the lock
        ensures the first call completes fully before the second starts.
        """
        engine = ConversationEngine()
        emitted: list[object] = []

        async def emit(msg: object) -> None:
            emitted.append(msg)

        await engine.start(emit)
        # _turn is now 1 — Q1 was asked.

        # Gather two concurrent answers.
        await asyncio.gather(
            engine.handle_answer("answer one", emit),
            engine.handle_answer("answer two", emit),
        )

        # With the lock, calls are serialised:
        # first answer → _turn 1→2 (Q2 asked)
        # second answer → _turn 2→3 (Q3 asked)
        assert engine._turn == 3, (  # noqa: PLR2004
            f"After start() + two concurrent handle_answer calls, _turn must be 3 "
            f"(lock serialises: Q1-answer → _turn=2, Q2-answer → _turn=3); "
            f"got _turn={engine._turn}. Without the lock both calls can read "
            f"_turn==1 and both advance to 2, leaving _turn==2 (double-apply "
            f"Q1 answer)."
        )

    async def test_handle_answer_after_complete_raises_conversation_complete_error(
        self,
    ) -> None:
        """A 4th handle_answer after completion must raise ConversationCompleteError."""
        # Deferred import: ConversationCompleteError does not exist until Warrior implements it.
        from bonfire.onboard.conversation import ConversationCompleteError  # noqa: PLC0415

        engine = ConversationEngine()
        await _drive_to_completion(engine)

        assert engine.is_complete

        emitted: list[object] = []

        async def emit(msg: object) -> None:
            emitted.append(msg)

        with pytest.raises(ConversationCompleteError):
            await engine.handle_answer("extra answer", emit)


# ---------------------------------------------------------------------------
# TestConversationCompleteError
# ---------------------------------------------------------------------------


class TestConversationCompleteError:
    """ConversationCompleteError must be a RuntimeError subclass and importable."""

    def test_is_subclass_of_runtimeerror(self) -> None:
        """ConversationCompleteError must be a subclass of RuntimeError."""
        from bonfire.onboard.conversation import ConversationCompleteError  # noqa: PLC0415

        assert issubclass(ConversationCompleteError, RuntimeError), (
            "ConversationCompleteError must subclass RuntimeError so existing "
            "RuntimeError catch sites remain compatible"
        )

    def test_is_importable_from_conversation_module(self) -> None:
        """ConversationCompleteError must be importable from bonfire.onboard.conversation."""
        from bonfire.onboard.conversation import ConversationCompleteError  # noqa: PLC0415

        assert ConversationCompleteError is not None

    def test_message_is_string_representable(self) -> None:
        """ConversationCompleteError instances must have a string representation."""
        from bonfire.onboard.conversation import ConversationCompleteError  # noqa: PLC0415

        exc = ConversationCompleteError("Conversation is already complete.")
        assert "complete" in str(exc).lower(), (
            "ConversationCompleteError message must mention 'complete'"
        )


# ---------------------------------------------------------------------------
# TestLockIsLazy
# ---------------------------------------------------------------------------


class TestLockIsLazy:
    """asyncio.Lock created at __init__ time binds to the current event loop.

    Reusing the engine across two asyncio.run blocks will fail if the lock
    is created eagerly, because the second run creates a new loop and the
    old lock is incompatible. The lock must be created lazily inside start()
    (or on first use inside handle_answer), following the same pattern as
    FrontDoorServer._shutdown_event.
    """

    def test_lock_is_none_before_start(self) -> None:
        """After __init__, _lock must be None (lazy creation mirror of Bug 1 Event pattern)."""
        engine = ConversationEngine()
        lock_val = getattr(engine, "_lock", "ATTRIBUTE_MISSING")
        assert lock_val is None, (
            f"ConversationEngine._lock must be None after __init__; "
            f"the lock is created lazily inside start() or handle_answer() "
            f"to avoid cross-event-loop binding errors. Got: {lock_val!r}"
        )

    def test_lock_is_event_loop_safe_across_runs(self) -> None:
        """Engine must survive two sequential asyncio.run blocks without RuntimeError.

        Pre-fix: asyncio.Lock created in __init__ binds to first loop; the
        second asyncio.run creates a new loop → RuntimeError.
        Post-fix: lock is re-created inside start() each time.
        """
        engine = ConversationEngine()

        async def _start_and_stop(eng: ConversationEngine) -> None:
            emitted: list[object] = []

            async def emit(msg: object) -> None:
                emitted.append(msg)

            # Reset mutable state for the second run.
            eng._turn = 0
            eng._profile = {}
            # Only reset _lock if it exists (post-implementation).
            if hasattr(eng, "_lock"):
                eng._lock = None

            await eng.start(emit)
            # Engine is now in state: _turn=1, lock bound to current loop.

        # Both runs must succeed without RuntimeError.
        asyncio.run(_start_and_stop(engine))
        asyncio.run(_start_and_stop(engine))

    async def test_lock_is_created_after_start(self) -> None:
        """After start(), _lock must be an asyncio.Lock instance (not None)."""
        engine = ConversationEngine()
        emitted: list[object] = []

        async def emit(msg: object) -> None:
            emitted.append(msg)

        await engine.start(emit)

        lock_val = getattr(engine, "_lock", "ATTRIBUTE_MISSING")
        assert lock_val is not None, (
            "ConversationEngine._lock must be an asyncio.Lock after start() is called; "
            "got None — lock was not created in start()"
        )
        assert isinstance(lock_val, asyncio.Lock), (
            f"ConversationEngine._lock must be asyncio.Lock; got {type(lock_val)}"
        )

    async def test_emitted_messages_are_falcor_messages(self) -> None:
        """start() emits ConversationStart + Q1 FalcorMessage; types are correct."""
        engine = ConversationEngine()
        emitted: list[object] = []

        async def emit(msg: object) -> None:
            emitted.append(msg)

        await engine.start(emit)

        assert len(emitted) == 2, (  # noqa: PLR2004
            f"start() must emit exactly 2 messages (ConversationStart + Q1 question); "
            f"got {len(emitted)}"
        )
        q1_msg = emitted[1]
        assert isinstance(q1_msg, FalcorMessage), (
            f"Second emitted message must be FalcorMessage; got {type(q1_msg)}"
        )
        assert q1_msg.subtype == "question"
