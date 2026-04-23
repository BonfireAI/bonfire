"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.consumer.

Covers ``KnowledgeIngestConsumer`` semantic contract (dedup, hashing,
VaultEntry construction, per-event-type entry_type mapping, resilience).

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3
(the ``bon-333 §2`` deferred contract).
"""

from __future__ import annotations

import logging

import pytest

from bonfire.events.bus import EventBus
from bonfire.knowledge.consumer import KnowledgeIngestConsumer
from bonfire.knowledge.hasher import content_hash
from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.models.events import (
    DispatchFailed,
    SessionEnded,
    StageCompleted,
    StageFailed,
)
from bonfire.protocols import VaultEntry


# --- helper builders (inline; one-to-one with Sage contract) ----------------


def _stage_completed(session_id: str = "sess-1", sequence: int = 1) -> StageCompleted:
    return StageCompleted(
        session_id=session_id,
        sequence=sequence,
        stage_name="knight",
        agent_name="knight-b",
        duration_seconds=1.0,
        cost_usd=0.01,
    )


def _stage_failed(session_id: str = "sess-1", sequence: int = 2) -> StageFailed:
    return StageFailed(
        session_id=session_id,
        sequence=sequence,
        stage_name="warrior",
        agent_name="warrior-a",
        error_message="boom",
    )


def _dispatch_failed(session_id: str = "sess-1", sequence: int = 3) -> DispatchFailed:
    return DispatchFailed(
        session_id=session_id,
        sequence=sequence,
        agent_name="agent-x",
        error_message="network",
    )


def _session_ended(session_id: str = "sess-1", sequence: int = 4) -> SessionEnded:
    return SessionEnded(
        session_id=session_id,
        sequence=sequence,
        status="completed",
        total_cost_usd=0.25,
    )


# --- fakes -------------------------------------------------------------------


class _FailingBackend(InMemoryVaultBackend):
    """Backend whose ``store`` always raises — for resilience test."""

    async def store(self, entry: VaultEntry) -> str:  # type: ignore[override]
        raise RuntimeError("backend down")


# --- tests -------------------------------------------------------------------


class TestRegistrationSurface:
    def test_implements_registration_surface(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        assert hasattr(consumer, "register")
        assert callable(consumer.register)

        bus = EventBus()
        consumer.register(bus)
        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        assert {StageCompleted, StageFailed, DispatchFailed, SessionEnded}.issubset(
            subscribed_types
        )


class TestEntryTypeMapping:
    async def test_on_stage_completed_stores_dispatch_outcome_entry(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        await consumer.on_stage_completed(_stage_completed())
        assert len(backend._entries) == 1
        assert backend._entries[0].entry_type == "dispatch_outcome"

    async def test_on_stage_failed_stores_error_pattern_entry(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        await consumer.on_stage_failed(_stage_failed())
        assert len(backend._entries) == 1
        assert backend._entries[0].entry_type == "error_pattern"

    async def test_on_dispatch_failed_stores_error_pattern_entry(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        await consumer.on_dispatch_failed(_dispatch_failed())
        assert len(backend._entries) == 1
        assert backend._entries[0].entry_type == "error_pattern"

    async def test_on_session_ended_stores_session_insight_entry(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        await consumer.on_session_ended(_session_ended())
        assert len(backend._entries) == 1
        assert backend._entries[0].entry_type == "session_insight"


class TestHashingAndDedup:
    async def test_content_hash_computed_via_knowledge_hasher(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        event = _stage_completed()
        await consumer.on_stage_completed(event)
        stored = backend._entries[0]
        # content_hash must equal content_hash(stored.content) — the hasher
        # locked by Sage D8.2.
        assert stored.content_hash == content_hash(stored.content)

    async def test_dedup_skips_store_when_hash_exists(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        event = _stage_completed()
        await consumer.on_stage_completed(event)
        first_count = len(backend._entries)
        # Same event → same content → same hash → second call is a no-op.
        await consumer.on_stage_completed(event)
        assert len(backend._entries) == first_count


class TestMetadataAndTimestamp:
    async def test_metadata_contains_session_id_and_event_id(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        event = _stage_completed(session_id="sess-42", sequence=7)
        await consumer.on_stage_completed(event)
        stored = backend._entries[0]
        assert stored.metadata.get("session_id") == "sess-42"
        assert stored.metadata.get("event_id") == event.event_id

    async def test_scanned_at_is_utc_iso8601(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        await consumer.on_stage_completed(_stage_completed())
        stored = backend._entries[0]
        # UTC ISO-8601 suffix is either 'Z' or '+00:00'.
        assert stored.scanned_at != ""
        assert stored.scanned_at.endswith("Z") or stored.scanned_at.endswith("+00:00")


class TestProjectNamePropagation:
    async def test_project_name_propagates_to_vault_entry(self):
        backend = InMemoryVaultBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire-x")
        await consumer.on_stage_completed(_stage_completed())
        stored = backend._entries[0]
        assert stored.project_name == "bonfire-x"


class TestResilience:
    async def test_backend_store_exception_is_caught_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ):
        backend = _FailingBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="bonfire")
        with caplog.at_level(logging.WARNING):
            # Must NOT raise — consumer swallows backend errors.
            await consumer.on_stage_completed(_stage_completed())
        # Some WARNING-level log record was emitted about the failure.
        assert any(
            record.levelno == logging.WARNING for record in caplog.records
        )
