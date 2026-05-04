# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""In-memory vault backend for testing.

Stores entries in a list. Query uses substring matching on content.
No embeddings, no external dependencies. Implements VaultBackend protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.knowledge.hasher import content_hash as compute_hash

if TYPE_CHECKING:
    from bonfire.protocols import VaultEntry


class InMemoryVaultBackend:
    """In-memory vault for tests. No embeddings, substring matching."""

    def __init__(self) -> None:
        self._entries: list[VaultEntry] = []

    async def store(self, entry: VaultEntry) -> str:
        if not entry.content_hash:
            entry = entry.model_copy(update={"content_hash": compute_hash(entry.content)})
        self._entries.append(entry)
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
        query_lower = query.lower()
        query_words = query_lower.split()
        scored = [(e, sum(1 for w in query_words if w in e.content.lower())) for e in candidates]
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored[:limit]]

    async def exists(self, content_hash: str) -> bool:
        return any(e.content_hash == content_hash for e in self._entries)

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        return [e for e in self._entries if e.source_path == source_path]
