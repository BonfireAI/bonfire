# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""In-memory vault backend.

Stores entries in a list. Query uses substring matching on content.
No embeddings, no external dependencies. Implements VaultBackend protocol.

Originally documented as "for testing," but the knowledge factory returns
this backend as the SHIPPING DEFAULT when knowledge is unconfigured
(``enabled=False`` or ``backend="memory"``). Production users hit this class
on every ``bonfire scan`` unless they explicitly opt into LanceDB, so its
performance characteristics matter accordingly.

Maintains side indices so the hot paths scale linearly:

* ``_hash_set`` -- a ``set[str]`` of stored ``content_hash`` values so
  :py:meth:`exists` is O(1). The earlier ``any(... for e in self._entries)``
  scan made every ``exists`` call linear in vault size and turned ingest
  (which calls ``exists`` once per entry before storing) into O(n²).
* ``_lower_cache`` -- a parallel ``list[str]`` of lowercased ``e.content``
  values, filled lazily on the first :py:meth:`query` call. The earlier
  implementation re-lowered every entry on every call; caching the lowered
  form per entry keeps repeated queries cheap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.knowledge.hasher import content_hash as compute_hash

if TYPE_CHECKING:
    from bonfire.protocols import VaultEntry


class InMemoryVaultBackend:
    """In-memory vault. Substring matching, no embeddings.

    Shipping default when knowledge is unconfigured. ``exists()`` is O(1) via
    the ``_hash_set`` side index; ``query()`` reads pre-lowered content from
    the ``_lower_cache`` side index (filled lazily, once per entry) so it does
    NOT allocate ``e.content.lower()`` per entry per call.

    The ``_entries: list[VaultEntry]`` attribute is the canonical iteration /
    inspection surface and is append-only -- ``store()`` does NOT dedup on
    hash collision (the caller owns the ``exists()``-then-``store()`` guard).
    """

    def __init__(self) -> None:
        self._entries: list[VaultEntry] = []
        # Set of stored content_hash values. O(1) membership for exists().
        # A set is cheaper to maintain than a dict-index since the index
        # mapping is never consulted by callers -- only presence.
        self._hash_set: set[str] = set()
        # Lowercased content, parallel to self._entries (same index). Filled
        # lazily on the first query() pass so store() stays free of any
        # per-entry .lower() allocation -- ingest-heavy workloads (which do
        # not query) never pay the cost. Once populated, repeated queries
        # reuse the cached lowercased strings (no per-call re-lowering).
        self._lower_cache: list[str] = []

    async def store(self, entry: VaultEntry) -> str:
        c_hash = entry.content_hash
        if not c_hash:
            c_hash = compute_hash(entry.content)
            entry = entry.model_copy(update={"content_hash": c_hash})
        self._entries.append(entry)
        # set.add is idempotent; duplicate stores still land in _entries
        # (preserving the prior append-on-duplicate behaviour) but exists()
        # resolves in O(1).
        self._hash_set.add(c_hash)
        return entry.entry_id

    def _ensure_lower_cache(self) -> None:
        """Bring ``_lower_cache`` up to length with ``_entries`` (idempotent).

        Lowercases any entries appended since the last sync. ``.lower()`` runs
        at most once per stored entry across the backend's lifetime.
        """
        if len(self._lower_cache) == len(self._entries):
            return
        # Append lowered content for any new entries since the last sync.
        for entry in self._entries[len(self._lower_cache) :]:
            self._lower_cache.append(entry.content.lower())

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[VaultEntry]:
        self._ensure_lower_cache()
        query_words = query.lower().split()
        scored: list[tuple[VaultEntry, int]] = []
        for idx, entry in enumerate(self._entries):
            if entry_type is not None and entry.entry_type != entry_type:
                continue
            lowered = self._lower_cache[idx]
            score = sum(1 for w in query_words if w in lowered)
            if score > 0:
                scored.append((entry, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:limit]]

    async def exists(self, content_hash: str) -> bool:
        return content_hash in self._hash_set

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        return [e for e in self._entries if e.source_path == source_path]
