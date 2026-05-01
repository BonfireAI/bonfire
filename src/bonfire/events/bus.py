# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Typed async EventBus — the nervous system of the Bonfire pipeline.

Architecture
------------
The EventBus implements a publish-subscribe pattern with two subscriber tiers:

1. **Typed subscribers** — registered via ``subscribe(EventType, handler)``.
   Only invoked when the emitted event is an instance of ``EventType``.
2. **Global subscribers** — registered via ``subscribe_all(handler)``.
   Invoked for every event, regardless of type.

Ordering guarantee (C7): typed subscribers always fire BEFORE global
subscribers, regardless of registration order. Within each tier, handlers
execute in registration order. All handlers are awaited sequentially —
correctness over performance.

Consumer isolation: each handler is wrapped in try/except so that a
failing consumer never prevents other consumers from receiving the event.
Errors are logged with the handler name and event type.

Sequence stamping: the bus maintains a monotonically increasing counter.
Each ``emit()`` increments the counter and stamps the event via
``model_copy(update={"sequence": n})``. The original event is never
mutated (frozen Pydantic model).

Dependencies: stdlib + typing + bonfire.models.events only.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, TypeVar

from bonfire.models.events import BonfireEvent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Generic type variable bound to BonfireEvent for type-safe subscriptions
E = TypeVar("E", bound=BonfireEvent)


class EventBus:
    """Async event bus with typed subscriptions and sequence stamping.

    Usage::

        bus = EventBus()

        async def on_stage(event: StageStarted) -> None:
            print(f"Stage {event.stage_name} started")

        bus.subscribe(StageStarted, on_stage)
        await bus.emit(StageStarted(session_id="s", sequence=0, ...))
    """

    def __init__(self) -> None:
        self._typed: dict[type, list[Callable[[BonfireEvent], Awaitable[None]]]] = defaultdict(list)
        self._global: list[Callable[[BonfireEvent], Awaitable[None]]] = []
        self._sequence: int = 0

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], Awaitable[None]],
    ) -> None:
        """Register a handler for a specific event type.

        The handler will only be called when an event of exactly
        ``event_type`` (checked via ``type(event) is event_type``) is
        emitted. Typed handlers always fire before global handlers.
        """
        self._typed[event_type].append(handler)  # type: ignore[arg-type]

    def subscribe_all(
        self,
        handler: Callable[[BonfireEvent], Awaitable[None]],
    ) -> None:
        """Register a handler that receives every emitted event.

        Global handlers fire after all typed handlers for the event's
        type have completed.
        """
        self._global.append(handler)

    async def emit(self, event: BonfireEvent) -> None:
        """Emit an event to all matching subscribers.

        Steps:
        1. Increment the sequence counter.
        2. Create a stamped copy via ``model_copy(update={"sequence": n})``.
        3. Await typed handlers sequentially (registration order).
        4. Await global handlers sequentially (registration order).

        Consumer isolation: each handler is individually try/excepted so
        that a failing consumer never prevents other consumers from
        receiving the event.  Errors are logged, not re-raised.

        The original event is never mutated.
        """
        self._sequence += 1
        stamped = event.model_copy(update={"sequence": self._sequence})

        # Typed subscribers first
        for handler in self._typed.get(type(event), []):
            try:
                await handler(stamped)
            except Exception:
                logger.exception(
                    "Handler %s failed for event %s (seq=%d)",
                    getattr(handler, "__qualname__", repr(handler)),
                    type(event).__name__,
                    self._sequence,
                )

        # Global subscribers second
        for handler in self._global:
            try:
                await handler(stamped)
            except Exception:
                logger.exception(
                    "Global handler %s failed for event %s (seq=%d)",
                    getattr(handler, "__qualname__", repr(handler)),
                    type(event).__name__,
                    self._sequence,
                )
