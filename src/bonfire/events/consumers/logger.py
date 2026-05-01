# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Session logger consumer — persists every event to session storage."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus
    from bonfire.models.events import BonfireEvent

logger = logging.getLogger(__name__)


class SessionLoggerConsumer:
    """Subscribes to ALL events and persists each one via the persistence backend."""

    def __init__(self, persistence: Any) -> None:
        self._persistence = persistence

    async def on_event(self, event: BonfireEvent) -> None:
        """Persist event. Never crash — log warning on failure."""
        try:
            self._persistence.append_event(event.session_id, event)
        except Exception:
            logger.warning("Failed to persist event %s", event.event_id, exc_info=True)

    def register(self, bus: EventBus) -> None:
        """Subscribe as a global listener on the bus."""
        bus.subscribe_all(self.on_event)
