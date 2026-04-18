"""Vault ingest consumer — public v0.1 surface stub.

The full storage semantics (content hashing, dedup, VaultEntry construction,
backend.store interaction) live in the future ``bonfire.vault`` transfer
wave. In public v0.1 this module exposes just the surface contract required
by ``wire_consumers``: a class that subscribes to four pipeline event types
and invokes the backend without crashing the pipeline on failure.

Resilience: all handlers catch exceptions from the backend so that a
storage failure never propagates into the bus.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bonfire.models.events import (
    DispatchFailed,
    SessionEnded,
    StageCompleted,
    StageFailed,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)


class VaultIngestConsumer:
    """Subscribes to pipeline events and feeds the vault backend.

    Public v0.1 stub: the handler bodies are deliberately minimal — they
    attempt a best-effort ``backend.store(event)`` when the backend exposes
    such a coroutine, and swallow any exception. Hashing, dedup, and the
    VaultEntry schema arrive with the full vault transfer.
    """

    def __init__(self, backend: Any, project_name: str) -> None:
        self.backend = backend
        self.project_name = project_name

    async def _safe_store(self, event: Any) -> None:
        """Best-effort store; never raises."""
        store = getattr(self.backend, "store", None)
        if store is None:
            return
        try:
            await store(event)
        except Exception:
            logger.warning("Vault store failed", exc_info=True)

    async def on_stage_completed(self, event: StageCompleted) -> None:
        await self._safe_store(event)

    async def on_stage_failed(self, event: StageFailed) -> None:
        await self._safe_store(event)

    async def on_dispatch_failed(self, event: DispatchFailed) -> None:
        await self._safe_store(event)

    async def on_session_ended(self, event: SessionEnded) -> None:
        await self._safe_store(event)

    def register(self, bus: EventBus) -> None:
        """Subscribe all four handlers to their respective event types."""
        bus.subscribe(StageCompleted, self.on_stage_completed)
        bus.subscribe(StageFailed, self.on_stage_failed)
        bus.subscribe(DispatchFailed, self.on_dispatch_failed)
        bus.subscribe(SessionEnded, self.on_session_ended)
