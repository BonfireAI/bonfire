# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight RED tests — ConversationEngine concurrency safety + typed lifecycle exceptions.

The pre-fix ConversationEngine had no per-handler lock and raised bare
``RuntimeError`` for lifecycle violations. Two defects rooted at the same
class:

1. **Back-to-back ``handle_answer`` calls corrupt ``_turn``.** ``handle_answer``
   awaits ``emit(...)`` (which awaits ``broadcast(...)`` on the server) BEFORE
   incrementing ``_turn``. If a second call lands while the first is suspended
   inside the first emit, both calls read the same stale ``_turn``, the analyzer
   fires twice for the same question, and the question-emission sequence
   skips a question. With three answers required for completion, a single
   double-click can push the engine into ``is_complete=True`` after Q2, then
   subsequent legitimate answers raise the bare ``RuntimeError`` and the WS
   handler silently logs without recovery — the engine is permanently broken
   for that session.

2. **Lifecycle violations raise bare ``RuntimeError``.** ``handle_answer``
   before ``start()`` and ``handle_answer`` after completion both raise
   ``RuntimeError("...")``. The WS handler's ``except Exception`` swallows
   them without producing a typed error frame the browser can show. The
   ticket calls out a typed exception that the WS handler can catch
   specifically and respond to with a typed error frame.

This Knight pins:

- ``ConversationEngine`` exposes an ``_lock`` attribute (``asyncio.Lock``).
- ``handle_answer`` acquires the lock for its full body — a second call
  blocks until the first releases.
- Calling ``handle_answer`` before ``start()`` raises ``ConversationNotStarted``
  (subclass of ``RuntimeError`` for backward-compat with existing catchers).
- Calling ``handle_answer`` after completion raises ``ConversationAlreadyComplete``
  (subclass of ``RuntimeError``).
- The legacy bare-``RuntimeError`` catch path still works (typed exceptions
  subclass ``RuntimeError`` so existing ``except RuntimeError`` blocks
  upstream in the WS handler still catch them).

Out of scope (filed for follow-up PR to avoid file overlap with the
in-flight front-door hardening PR):

- WS handler integration — catching ``ConversationNotStarted`` /
  ``ConversationAlreadyComplete`` specifically and emitting a typed
  error frame to the browser. Touches ``server.py`` + ``flow.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from bonfire.onboard.conversation import (
    ConversationAlreadyComplete,
    ConversationEngine,
    ConversationNotStarted,
)
from bonfire.onboard.protocol import FrontDoorMessage


async def _noop_emit(_msg: FrontDoorMessage) -> None:
    """Emit callback that does nothing — for tests not asserting emission shape."""


# ---------------------------------------------------------------------------
# Lock presence + acquire semantics
# ---------------------------------------------------------------------------


class TestLockPresence:
    """``ConversationEngine`` must have an ``asyncio.Lock`` instance attribute."""

    def test_engine_has_lock_attribute(self) -> None:
        engine = ConversationEngine()
        assert isinstance(engine._lock, asyncio.Lock), (
            "ConversationEngine must expose an asyncio.Lock as _lock; "
            "the per-handler lock is the concurrency-safety contract"
        )

    def test_lock_is_per_instance_not_shared(self) -> None:
        """Two engines have independent locks (defaults aren't shared)."""
        e1 = ConversationEngine()
        e2 = ConversationEngine()
        assert e1._lock is not e2._lock, (
            "Each ConversationEngine instance must have its own asyncio.Lock — "
            "shared default-factory output between instances would serialize "
            "unrelated conversations"
        )


class TestHandleAnswerAcquiresLock:
    """``handle_answer`` must block while the lock is held externally."""

    async def test_handle_answer_blocks_when_lock_held(self) -> None:
        """If something else holds ``engine._lock``, ``handle_answer`` waits."""
        engine = ConversationEngine()
        await engine.start(_noop_emit)
        assert engine._turn == 1

        # Hold the lock externally; handle_answer should block. Use a short
        # timeout to assert blocking behavior without hanging the test.
        async with engine._lock:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    engine.handle_answer(
                        "a sufficiently long answer to trigger the analyzer path",
                        _noop_emit,
                    ),
                    timeout=0.3,
                )

        # After the external hold releases, the same call should succeed.
        # (Construct a fresh call since the previous one was cancelled by
        # the timeout.)
        await engine.handle_answer(
            "a sufficiently long answer to trigger the analyzer path",
            _noop_emit,
        )
        assert engine._turn == 2, (
            "handle_answer should resume after the lock releases and advance _turn"
        )

    async def test_back_to_back_handle_answer_calls_serialize(self) -> None:
        """Two concurrent ``handle_answer`` calls fire questions in order, not interleaved.

        Pre-fix: both calls read the same stale ``_turn``, the question-emission
        sequence races, and questions can be skipped. Post-fix: the lock
        serializes the call bodies, so emissions land in their natural Q1→Q2→Q3
        order.
        """
        engine = ConversationEngine()
        emitted: list[FrontDoorMessage] = []

        async def recording_emit(msg: FrontDoorMessage) -> None:
            # Force a yield to the event loop on every emit, mirroring the
            # broadcast()→asyncio.gather() suspension shape the ticket cites.
            await asyncio.sleep(0)
            emitted.append(msg)

        await engine.start(recording_emit)

        # Fire two answers concurrently — without the lock, the call bodies
        # interleave at the first await emit() and the question-emission
        # sequence races.
        await asyncio.gather(
            engine.handle_answer(
                "first answer with enough words to trigger the analyzer",
                recording_emit,
            ),
            engine.handle_answer(
                "second answer with enough words to trigger the analyzer",
                recording_emit,
            ),
        )

        # _turn should have advanced exactly twice (Q1 → Q2 → Q3 waiting).
        assert engine._turn == 3, (
            f"After two answers, _turn should be 3; got {engine._turn} "
            "(race condition: both calls saw stale _turn or double-incremented)"
        )

        # Extract just the question-shaped emissions (start + each handle_answer
        # emits a reflection + the next question; we only assert on questions
        # to keep the test resilient to reflection-text variations).
        question_texts = [
            m.text  # type: ignore[attr-defined]
            for m in emitted
            if getattr(m, "subtype", None) == "question"
        ]

        # Pre-fix race: questions can be emitted out of order or skipped.
        # Post-fix: Q1 (from start), Q2 (from call A), Q3 (from call B) — in
        # strict ascending order.
        assert len(question_texts) == 3, (
            f"Expected 3 questions emitted; got {len(question_texts)}: {question_texts}"
        )
        # The questions are unique by content; assert ascending-position order
        # by checking that no question is emitted before a higher-indexed one.
        from bonfire.onboard.conversation import _QUESTIONS

        expected_order = list(_QUESTIONS[:3])
        assert question_texts == expected_order, (
            f"Questions emitted out of order under concurrent handle_answer: "
            f"got {question_texts!r}, expected {expected_order!r}"
        )


# ---------------------------------------------------------------------------
# Typed lifecycle exceptions
# ---------------------------------------------------------------------------


class TestTypedLifecycleExceptions:
    """``handle_answer`` raises typed exceptions, not bare ``RuntimeError``."""

    async def test_handle_answer_before_start_raises_typed_not_started(self) -> None:
        """Calling ``handle_answer`` before ``start()`` raises ``ConversationNotStarted``."""
        engine = ConversationEngine()
        with pytest.raises(ConversationNotStarted):
            await engine.handle_answer("anything", _noop_emit)

    async def test_handle_answer_after_complete_raises_typed_already_complete(
        self,
    ) -> None:
        """Calling ``handle_answer`` after all 3 answers raises ``ConversationAlreadyComplete``."""
        engine = ConversationEngine()
        await engine.start(_noop_emit)
        # Provide three answers to drive the engine to completion.
        for i in range(3):
            await engine.handle_answer(
                f"answer {i} with enough words to satisfy the analyzer",
                _noop_emit,
            )
        assert engine.is_complete is True
        with pytest.raises(ConversationAlreadyComplete):
            await engine.handle_answer("one too many", _noop_emit)

    async def test_typed_exceptions_subclass_runtimeerror_for_backcompat(self) -> None:
        """Typed exceptions must subclass ``RuntimeError`` so existing catchers still work.

        The WS handler's ``except Exception`` already catches these, but any
        upstream code that specifically did ``except RuntimeError`` (the
        pre-fix exception type) must continue to work without modification.
        """
        assert issubclass(ConversationNotStarted, RuntimeError)
        assert issubclass(ConversationAlreadyComplete, RuntimeError)
