"""RED tests — BON-1009 — event_id-scoped dedup in ``KnowledgeIngestConsumer``.

Defect (Wave 5 follow-up): ``KnowledgeIngestConsumer._store`` derives its
dedup key from the content text alone
(``c_hash = content_hash(content)``). When two *distinct* events produce the
same content text — trivially easy with short standard messages, status
banners, identical error strings, etc. — the second event's hash collides
with the first, ``backend.exists(...)`` returns ``True``, and the second
event is silently dropped as a "duplicate". That is silent data loss: two
legitimately-distinct events collapse to one stored entry.

The fix (consumer.py ONLY): fold ``event.event_id`` into the LOCAL dedup
key so that two distinct events with identical text are stored as two
distinct entries. The shared ``content_hash(text)`` signature in
``knowledge/hasher.py`` MUST NOT change (9 callers).

Acceptance criteria (BON-1009):
1. The dedup key includes ``event_id`` so two distinct events with identical
   text are stored as two distinct entries.
2. Regression test exercises two events with identical content text and
   asserts BOTH end up in the vault.
3. Genuine duplicate-suppression (re-firing the SAME event, same event_id +
   same content) is preserved — the fix must not over-correct into
   "never dedup".

These tests assert the FIXED behavior and FAIL on current ``origin/main``
(where the second distinct event is silently dropped).
"""

from __future__ import annotations

from typing import Any

from bonfire.knowledge.consumer import KnowledgeIngestConsumer
from bonfire.models.events import StageCompleted
from bonfire.protocols import VaultBackend, VaultEntry

# ---------------------------------------------------------------------------
# Realistic fake backend — exists() reflects what has actually been stored.
#
# A real VaultBackend dedups by remembering the content_hash of every stored
# entry: a subsequent exists(hash) returns True once an entry with that hash
# is present. The existing test_knowledge_consumer.py fake only reports
# pre-seeded hashes (it never learns from store()), which masks this defect.
# This fake closes that gap so the content-level collision actually fires.
# ---------------------------------------------------------------------------


class _StatefulBackend:
    """VaultBackend whose ``exists`` reflects prior ``store`` calls.

    Mirrors a real backend's content-hash dedup: a hash is "known" once an
    entry carrying it has been stored.
    """

    def __init__(self) -> None:
        self.stored: list[VaultEntry] = []
        self._known_hashes: set[str] = set()

    async def store(self, entry: VaultEntry) -> str:
        self.stored.append(entry)
        self._known_hashes.add(entry.content_hash)
        return entry.entry_id

    async def exists(self, content_hash: str) -> bool:
        return content_hash in self._known_hashes

    async def query(
        self, query: str, *, limit: int = 5, entry_type: str | None = None
    ) -> list[VaultEntry]:
        return []

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        return []


# ---------------------------------------------------------------------------
# Event factory — same content text, distinct event_id.
#
# StageCompleted.content text is derived from session_id/stage_name/agent_name/
# duration_seconds/cost_usd (see consumer.on_stage_completed). Holding all of
# those fixed across two events makes their CONTENT identical while event_id
# (default_factory uuid4) differs — exactly the collision the ticket describes.
# ---------------------------------------------------------------------------


_SESSION = "bon1009-session"


def _identical_text_stage_completed(**overrides: Any) -> StageCompleted:
    """A StageCompleted whose content text is constant across instances."""
    return StageCompleted(
        session_id=_SESSION,
        sequence=1,
        stage_name="knight",
        agent_name="knight-a",
        duration_seconds=1.0,
        cost_usd=0.1,
        **overrides,
    )


class TestEventIdScopedDedup:
    async def test_two_distinct_events_identical_text_both_stored(self) -> None:
        """AC#2: two distinct events with identical content text → BOTH stored.

        On origin/main the dedup key is ``content_hash(content)`` alone, so the
        second event collides with the first and is silently dropped — this
        assertion fails with ``len == 1``. The fix folds event_id into the
        dedup key so both land.
        """
        backend = _StatefulBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")

        first = _identical_text_stage_completed()
        second = _identical_text_stage_completed()

        # Precondition: the events are genuinely distinct yet carry the same text.
        assert first.event_id != second.event_id
        assert first.event_id  # non-empty
        assert second.event_id

        await consumer.on_stage_completed(first)
        await consumer.on_stage_completed(second)

        assert len(backend.stored) == 2, (
            "Two distinct events with identical content text were collapsed to "
            "one stored entry — silent data loss (BON-1009)."
        )

    async def test_both_stored_entries_preserve_their_event_ids(self) -> None:
        """The two stored entries are distinguishable by their event_id.

        Beyond merely counting two stores, the surviving entries must carry the
        two DISTINCT event_ids — proving they are the two real events and not a
        duplicated single one.
        """
        backend = _StatefulBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")

        first = _identical_text_stage_completed()
        second = _identical_text_stage_completed()

        await consumer.on_stage_completed(first)
        await consumer.on_stage_completed(second)

        stored_event_ids = {e.metadata["event_id"] for e in backend.stored}
        assert stored_event_ids == {first.event_id, second.event_id}

    async def test_same_event_refired_is_still_deduped(self) -> None:
        """AC#3: re-firing the SAME event (same event_id + text) → one store.

        The fix must scope dedup by (event_id, content), NOT abandon dedup. A
        replay of the identical event must still collapse to a single entry.
        """
        backend = _StatefulBackend()
        consumer = KnowledgeIngestConsumer(backend=backend, project_name="p")

        event = _identical_text_stage_completed()
        await consumer.on_stage_completed(event)
        await consumer.on_stage_completed(event)

        assert len(backend.stored) == 1, (
            "Re-firing the identical event (same event_id + content) must "
            "still dedup to a single entry."
        )

    def test_stateful_backend_satisfies_vault_backend_protocol(self) -> None:
        """Guard: the fake is a real VaultBackend so the test is not tautological."""
        assert isinstance(_StatefulBackend(), VaultBackend)
