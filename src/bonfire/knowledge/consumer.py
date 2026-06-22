# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knowledge ingest consumer — subscribes to pipeline events and stores knowledge.

Listens for StageCompleted, StageFailed, DispatchFailed, and SessionEnded
events on the EventBus. Each event is transformed into a VaultEntry and
stored via the configured VaultBackend.

Dedup: content_hash is computed before store(); if the backend already
contains that hash, the entry is silently skipped.

Resilience: all handlers catch exceptions from the backend so that a
storage failure never crashes the pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bonfire.knowledge.hasher import content_hash
from bonfire.models.events import (
    DispatchFailed,
    SessionEnded,
    StageCompleted,
    StageFailed,
)
from bonfire.protocols import VaultEntry

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus
    from bonfire.protocols import VaultBackend

logger = logging.getLogger(__name__)


class KnowledgeIngestConsumer:
    """Subscribes to pipeline events and stores extracted knowledge in the vault."""

    def __init__(self, backend: VaultBackend, project_name: str) -> None:
        self.backend = backend
        self.project_name = project_name

    async def on_stage_completed(self, event: StageCompleted) -> None:
        """Extract dispatch outcome from a completed stage."""
        text = (
            f"session={event.session_id} stage={event.stage_name} "
            f"agent={event.agent_name} "
            f"duration={event.duration_seconds} cost={event.cost_usd}"
        )
        await self._store(
            content=text,
            entry_type="dispatch_outcome",
            event=event,
        )

    async def on_stage_failed(self, event: StageFailed) -> None:
        """Extract error pattern from a failed stage."""
        text = (
            f"session={event.session_id} stage={event.stage_name} "
            f"agent={event.agent_name} error_message={event.error_message}"
        )
        await self._store(
            content=text,
            entry_type="error_pattern",
            event=event,
        )

    async def on_dispatch_failed(self, event: DispatchFailed) -> None:
        """Extract error pattern from a failed dispatch."""
        text = (
            f"session={event.session_id} agent={event.agent_name} "
            f"error_message={event.error_message}"
        )
        await self._store(
            content=text,
            entry_type="error_pattern",
            event=event,
        )

    async def on_session_ended(self, event: SessionEnded) -> None:
        """Extract session insight from a completed session."""
        text = (
            f"session={event.session_id} status={event.status} "
            f"total_cost_usd={event.total_cost_usd}"
        )
        await self._store(
            content=text,
            entry_type="session_insight",
            event=event,
        )

    def register(self, bus: EventBus) -> None:
        """Subscribe all four handlers to their respective event types."""
        bus.subscribe(StageCompleted, self.on_stage_completed)
        bus.subscribe(StageFailed, self.on_stage_failed)
        bus.subscribe(DispatchFailed, self.on_dispatch_failed)
        bus.subscribe(SessionEnded, self.on_session_ended)

    async def _store(
        self,
        *,
        content: str,
        entry_type: str,
        event: StageCompleted | StageFailed | DispatchFailed | SessionEnded,
    ) -> None:
        """Build a VaultEntry and persist it, with dedup and error resilience."""
        try:
            c_hash = content_hash(content)
            if await self.backend.exists(c_hash):
                return

            entry = VaultEntry(
                content=content,
                entry_type=entry_type,
                project_name=self.project_name,
                content_hash=c_hash,
                scanned_at=datetime.now(UTC).isoformat(),
                metadata={
                    "session_id": event.session_id,
                    "event_id": event.event_id,
                },
            )
            await self.backend.store(entry)
        except Exception:
            logger.warning("Vault store failed for %s event", entry_type, exc_info=True)
