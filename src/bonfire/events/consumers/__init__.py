# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Event consumers — decoupled observers for the EventBus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bonfire.events.consumers.cost import CostTracker
from bonfire.events.consumers.display import DisplayConsumer
from bonfire.events.consumers.knowledge_ingest import KnowledgeIngestConsumer
from bonfire.events.consumers.logger import SessionLoggerConsumer

if TYPE_CHECKING:
    from collections.abc import Callable

    from bonfire.events.bus import EventBus

__all__ = [
    "CostTracker",
    "DisplayConsumer",
    "KnowledgeIngestConsumer",
    "SessionLoggerConsumer",
    "wire_consumers",
]


def wire_consumers(
    *,
    bus: EventBus,
    persistence: Any,
    cost_tracker: CostTracker,
    display_callback: Callable[..., Any],
    vault_backend: Any,
) -> None:
    """Create and register all public-v0.1 consumers on the bus.

    Keyword-only. Wires:

    - ``SessionLoggerConsumer(persistence)`` — global subscriber.
    - ``DisplayConsumer(display_callback)`` — four typed subscriptions.
    - ``cost_tracker.register(bus)`` — caller owns the tracker so the
      running total is observable after wiring.
    - ``KnowledgeIngestConsumer(backend=vault_backend, project_name="bonfire")``.
    """
    logger_consumer = SessionLoggerConsumer(persistence=persistence)
    logger_consumer.register(bus)

    display_consumer = DisplayConsumer(callback=display_callback)
    display_consumer.register(bus)

    cost_tracker.register(bus)

    knowledge_consumer = KnowledgeIngestConsumer(backend=vault_backend, project_name="bonfire")
    knowledge_consumer.register(bus)
