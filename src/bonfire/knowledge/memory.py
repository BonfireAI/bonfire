# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""In-memory vault backend.

Stores entries in a list with O(1)-indexed dedup and a lowercase-content
cache for fast substring query. No embeddings, no external dependencies.
Implements VaultBackend protocol.

Originally documented as "for testing," but the knowledge factory returns
this backend as the SHIPPING DEFAULT when knowledge is unconfigured
(``enabled=False`` or ``backend="memory"``). Production users hit this
class on every ``bonfire scan`` unless they explicitly opt into LanceDB.
The performance characteristics matter accordingly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.knowledge.hasher import content_hash as compute_hash

if TYPE_CHECKING:
    from bonfire.protocols import VaultEntry


class InMemoryVaultBackend:
    """In-memory vault. Substring matching, no embeddings.

    Shipping default when knowledge is unconfigured. O(1) ``exists()`` via a
    side hash-set index; ``query()`` reads pre-computed lowercase content
    from a side cache so it does NOT allocate ``e.content.lower()`` per
    entry per call.

    The public ``_entries: list[VaultEntry]`` attribute is preserved as the
    canonical iteration / inspection surface; ``_hashes`` and
    ``_lower_content`` are private indexes maintained at ``store()`` time.
    All three are append-only — ``store()`` does NOT dedup on hash collision
    (the backend's caller is responsible for the ``exists()``-then-``store()``
    guard pattern).
    """

    def __init__(self) -> None:
        self._entries: list[VaultEntry] = []
        # O(1) ``exists()`` — set of all stored content hashes.
        self._hashes: set[str] = set()
        # ``query()`` lower-case cache, keyed by ``entry_id``. Populated at
        # ``store()``; read in the substring-match hot loop so we never call
        # ``e.content.lower()`` per entry per query.
        self._lower_content: dict[str, str] = {}

    async def store(self, entry: VaultEntry) -> str:
        if not entry.content_hash:
            entry = entry.model_copy(update={"content_hash": compute_hash(entry.content)})
        self._entries.append(entry)
        self._hashes.add(entry.content_hash)
        self._lower_content[entry.entry_id] = entry.content.lower()
        return entry.entry_id

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[VaultEntry]:
        candidates = self._entries
        if entry_type is not None:
            candidates = [e for e in candidates if e.entry_type == entry_type]
        query_words = query.lower().split()
        # Read from the lower-case cache populated at store() — no per-entry
        # ``.lower()`` allocation in this hot path.
        lower_content = self._lower_content
        scored = [
            (e, sum(1 for w in query_words if w in lower_content[e.entry_id])) for e in candidates
        ]
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:limit]]

    async def exists(self, content_hash: str) -> bool:
        # O(1) via side index; replaces the prior O(N) ``any(...)`` scan.
        return content_hash in self._hashes

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        return [e for e in self._entries if e.source_path == source_path]
