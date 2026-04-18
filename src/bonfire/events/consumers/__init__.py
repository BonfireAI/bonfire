"""Event consumers — decoupled observers for the EventBus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bonfire.events.consumers.cost import CostTracker
from bonfire.events.consumers.display import DisplayConsumer
from bonfire.events.consumers.logger import SessionLoggerConsumer
from bonfire.events.consumers.vault_ingest import VaultIngestConsumer

if TYPE_CHECKING:
    from collections.abc import Callable

    from bonfire.events.bus import EventBus

__all__ = [
    "CostTracker",
    "DisplayConsumer",
    "SessionLoggerConsumer",
    "VaultIngestConsumer",
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
    - ``VaultIngestConsumer(vault_backend, project_name="bonfire")``.
    """
    logger_consumer = SessionLoggerConsumer(persistence=persistence)
    logger_consumer.register(bus)

    display_consumer = DisplayConsumer(callback=display_callback)
    display_consumer.register(bus)

    cost_tracker.register(bus)

    vault_consumer = VaultIngestConsumer(backend=vault_backend, project_name="bonfire")
    vault_consumer.register(bus)
