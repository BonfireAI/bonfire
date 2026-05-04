"""RED tests — BON-341 W5.2 — `bonfire.knowledge.consumer.KnowledgeIngestConsumer`.

The bon-333 §2 deferred semantic contract — dedup, hashing, VaultEntry construction,
and per-event-type entry_type mapping — now lands in BON-341 per Sage D3.13.

Sage D8.2 type locks:
- ``__init__(self, backend: VaultBackend, project_name: str) -> None``
- ``on_stage_completed`` -> entry_type="dispatch_outcome"
- ``on_stage_failed`` -> entry_type="error_pattern"
- ``on_dispatch_failed`` -> entry_type="error_pattern"
- ``on_session_ended`` -> entry_type="session_insight"
- ``register(bus) -> None`` subscribes all four.
- ``_store`` dedups via content_hash, catches exceptions, logs WARNING.
- ``VaultEntry.metadata`` keys LOCKED: ``session_id: str``, ``event_id: str`` (no others).
- ``content_hash`` via ``bonfire.knowledge.hasher.content_hash``.
- ``scanned_at`` is UTC ISO-8601 string.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pytest

from bonfire.events.bus import EventBus
from bonfire.knowledge.consumer import KnowledgeIngestConsumer
from bonfire.knowledge.hasher import content_hash as _ch
from bonfire.models.events import (
    DispatchFailed,
    SessionEnded,
    StageCompleted,
    StageFailed,
)
from bonfire.protocols import VaultBackend, VaultEntry

# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------


class _FakeBackend:
    """Test backend satisfying VaultBackend protocol."""

    def __init__(self, *, pre_existing: set[str] | None = None) -> None:
        self.stored: list[VaultEntry] = []
        self.exists_calls: list[str] = []
        self._pre = pre_existing or set()

    async def store(self, entry: VaultEntry) -> str:
        self.stored.append(entry)
        return entry.entry_id

    async def exists(self, content_hash: str) -> bool:
        self.exists_calls.append(content_hash)
        return content_hash in self._pre

    async def query(
        self, query: str, *, limit: int = 5, entry_type: str | None = None
    ) -> list[VaultEntry]:
        return []

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        return []


class _ExplodingStoreBackend(_FakeBackend):
    async def store(self, entry: VaultEntry) -> str:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Event factories
# ---------------------------------------------------------------------------


_SESSION = "test-session-007"


def _stage_completed(**overrides: Any) -> StageCompleted:
    return StageCompleted(
        session_id=_SESSION,
        sequence=1,
        stage_name="knight",
        agent_name="knight-a",
        duration_seconds=1.5,
        cost_usd=0.25,
        **overrides,
    )


def _stage_failed(**overrides: Any) -> StageFailed:
    return StageFailed(
        session_id=_SESSION,
        sequence=2,
        stage_name="knight",
        agent_name="knight-b",
        error_message="boom",
        **overrides,
    )


def _dispatch_failed(**overrides: Any) -> DispatchFailed:
    return DispatchFailed(
        session_id=_SESSION,
        sequence=3,
        agent_name="warrior",
        error_message="timeout",
        **overrides,
    )


def _session_ended(**overrides: Any) -> SessionEnded:
    return SessionEnded(
        session_id=_SESSION,
        sequence=4,
        status="completed",
        total_cost_usd=2.5,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Registration surface
# ---------------------------------------------------------------------------


class TestRegistrationSurface:
    def test_implements_registration_surface(self) -> None:
        """Constructor + register + 4 subscriptions."""
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        assert hasattr(consumer, "register")
        assert callable(consumer.register)

    def test_backend_accepts_vault_backend_protocol(self) -> None:
        """Backend argument can be any VaultBackend-conforming object."""
        backend = _FakeBackend()
        assert isinstance(backend, VaultBackend)
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        assert consumer is not None

    def test_register_subscribes_to_four_event_types(self) -> None:
        """register(bus) subscribes to exactly the 4 locked event types."""
        bus = EventBus()
        consumer = KnowledgeIngestConsumer(backend=_FakeBackend(), project_name="p")
        consumer.register(bus)
        subscribed = {k for k, v in bus._typed.items() if len(v) > 0}
        expected = {StageCompleted, StageFailed, DispatchFailed, SessionEnded}
        assert expected.issubset(subscribed)


# ---------------------------------------------------------------------------
# Per-event-type entry_type mapping (innovative split — one test per event)
# ---------------------------------------------------------------------------


class TestEntryTypeMapping:
    async def test_on_stage_completed_stores_dispatch_outcome_entry(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_stage_completed(_stage_completed())
        assert len(backend.stored) == 1
        assert backend.stored[0].entry_type == "dispatch_outcome"

    async def test_on_stage_failed_stores_error_pattern_entry(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_stage_failed(_stage_failed())
        assert backend.stored[0].entry_type == "error_pattern"

    async def test_on_dispatch_failed_stores_error_pattern_entry(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_dispatch_failed(_dispatch_failed())
        assert backend.stored[0].entry_type == "error_pattern"

    async def test_on_session_ended_stores_session_insight_entry(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_session_ended(_session_ended())
        assert backend.stored[0].entry_type == "session_insight"


# ---------------------------------------------------------------------------
# Content-hash semantics
# ---------------------------------------------------------------------------


class TestContentHashing:
    async def test_content_hash_computed_via_knowledge_hasher(self) -> None:
        """Entry.content_hash == content_hash(entry.content) (byte-stable)."""
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_stage_completed(_stage_completed())
        entry = backend.stored[0]
        assert entry.content_hash == _ch(entry.content)

    async def test_dedup_skips_store_when_hash_exists(self) -> None:
        """If backend.exists(hash) is True, consumer does NOT call store()."""
        # Pre-compute content that matches the consumer's output for stage_completed.
        event = _stage_completed()
        expected_content = (
            f"session={event.session_id} stage={event.stage_name} "
            f"agent={event.agent_name} "
            f"duration={event.duration_seconds} cost={event.cost_usd}"
        )
        expected_hash = _ch(expected_content)
        backend = _FakeBackend(pre_existing={expected_hash})
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_stage_completed(event)
        assert backend.stored == []

    # knight-a(innovative): re-firing same event twice -> only one store.
    async def test_dedup_prevents_duplicate_store_across_calls(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        event = _stage_completed()
        await consumer.on_stage_completed(event)
        # After first store, add the hash to pre_existing so exists() returns True.
        stored_hash = backend.stored[0].content_hash
        backend._pre.add(stored_hash)
        await consumer.on_stage_completed(event)
        assert len(backend.stored) == 1


# ---------------------------------------------------------------------------
# Metadata structure
# ---------------------------------------------------------------------------


class TestMetadata:
    async def test_metadata_contains_session_id_and_event_id(self) -> None:
        """Locked metadata keys: session_id + event_id (no other keys)."""
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        event = _stage_completed()
        await consumer.on_stage_completed(event)
        meta = backend.stored[0].metadata
        assert meta["session_id"] == event.session_id
        assert meta["event_id"] == event.event_id

    # knight-a(innovative): metadata contains ONLY the two locked keys.
    async def test_metadata_contains_only_locked_keys(self) -> None:
        """Sage D8.2: metadata LOCKED keys session_id, event_id (no other keys)."""
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_stage_completed(_stage_completed())
        meta = backend.stored[0].metadata
        assert set(meta.keys()) == {"session_id", "event_id"}


# ---------------------------------------------------------------------------
# Resilience — exceptions are caught + logged
# ---------------------------------------------------------------------------


class TestResilience:
    async def test_backend_store_exception_is_caught_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        backend = _ExplodingStoreBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        with caplog.at_level(logging.WARNING):
            # Must NOT raise.
            await consumer.on_stage_completed(_stage_completed())
        # A warning should be emitted.
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z|\+00:00)$"
)


class TestProvenance:
    async def test_scanned_at_is_utc_iso8601(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")
        await consumer.on_stage_completed(_stage_completed())
        scanned_at = backend.stored[0].scanned_at
        assert _ISO8601_RE.fullmatch(scanned_at), f"Bad ISO-8601: {scanned_at!r}"

    async def test_project_name_propagates_to_vault_entry(self) -> None:
        backend = _FakeBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="my-project")
        await consumer.on_stage_completed(_stage_completed())
        assert backend.stored[0].project_name == "my-project"
