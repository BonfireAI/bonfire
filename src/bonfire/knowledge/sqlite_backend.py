# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Persistent vault backend backed by the stdlib ``sqlite3`` module.

This is the *portable* persistent backend: it needs no third-party
dependencies (unlike the LanceDB backend, whose vector deps are absent in
CI), so it runs everywhere CPython does. A single plain table holds one row
per :class:`~bonfire.protocols.VaultEntry`; list/dict fields are stored as
JSON text.

Retrieval is **honest keyword search**, not semantic search. ``query`` does
exactly what :class:`~bonfire.knowledge.memory.InMemoryVaultBackend` does: it
splits the query into words and scores each entry by how many of those words
appear as a case-insensitive substring of the entry's content -- no
embeddings, no vectors. SQLite ``LIKE`` is used only as a parameterized
prefilter to avoid scanning unmatched rows; the final scoring and ranking
mirror the in-memory backend byte-for-byte.

The async methods wrap synchronous ``sqlite3`` calls (the same pattern the
in-memory backend uses) -- no ``aiosqlite`` or other added dependency.

Schema is versioned (BubbleGum): ``_SCHEMA_VERSION`` plus an idempotent,
forward-only ``_ensure_schema``. A ``vault_meta`` row records the version so
a future migration can detect and upgrade an older file.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from bonfire.knowledge.hasher import content_hash as compute_hash
from bonfire.protocols import VaultEntry

if TYPE_CHECKING:
    from collections.abc import Iterable

# Forward-only schema version. Bump only alongside a migration step in
# ``_ensure_schema``; never rewrite history.
_SCHEMA_VERSION = 1

# Ordered VaultEntry fields stored as their own columns. The two structured
# fields (``tags`` -> JSON array, ``metadata`` -> JSON object) are handled
# separately when (de)serializing; everything else round-trips as TEXT.
_TEXT_FIELDS = (
    "entry_id",
    "content",
    "entry_type",
    "source_path",
    "project_name",
    "scanned_at",
    "git_hash",
    "content_hash",
)


class SqliteVaultBackend:
    """Persistent vault over a single ``sqlite3`` connection.

    Pass a filesystem ``db_path`` to persist across process restarts, or
    ``":memory:"`` (the default) for an ephemeral in-process database used by
    tests. Keyword retrieval only -- no embeddings.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        # check_same_thread=False keeps the connection usable from the asyncio
        # event loop's worker context; access here is serialized by the single
        # event loop so no cross-thread races occur.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    # -- schema ----------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create the table and record the schema version (idempotent).

        Forward-only: safe to call on every open. Creating the objects
        ``IF NOT EXISTS`` means an existing file is left intact; the version
        row is inserted only when absent.
        """
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vault_entries (
                entry_id     TEXT PRIMARY KEY,
                content      TEXT NOT NULL,
                entry_type   TEXT NOT NULL,
                source_path  TEXT NOT NULL DEFAULT '',
                project_name TEXT NOT NULL DEFAULT '',
                scanned_at   TEXT NOT NULL DEFAULT '',
                git_hash     TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                tags         TEXT NOT NULL DEFAULT '[]',
                metadata     TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vault_entries_content_hash "
            "ON vault_entries (content_hash)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vault_entries_source_path "
            "ON vault_entries (source_path)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vault_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO vault_meta (key, value) VALUES ('schema_version', ?)",
            (str(_SCHEMA_VERSION),),
        )
        self._conn.commit()

    # -- (de)serialization ----------------------------------------------

    @staticmethod
    def _to_row(entry: VaultEntry) -> tuple[object, ...]:
        """Flatten a VaultEntry into the column tuple (JSON for tags/metadata)."""
        values: list[object] = [getattr(entry, field) for field in _TEXT_FIELDS]
        values.append(json.dumps(entry.tags))
        values.append(json.dumps(entry.metadata))
        return tuple(values)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> VaultEntry:
        """Rebuild a VaultEntry from a stored row (JSON-decode tags/metadata)."""
        data = {field: row[field] for field in _TEXT_FIELDS}
        data["tags"] = json.loads(row["tags"])
        data["metadata"] = json.loads(row["metadata"])
        return VaultEntry(**data)

    # -- protocol methods -----------------------------------------------

    async def store(self, entry: VaultEntry) -> str:
        """Persist *entry* (upsert by ``entry_id``) and return its ``entry_id``.

        Computes ``content_hash`` from the content when the caller left it
        blank, mirroring the in-memory backend.
        """
        if not entry.content_hash:
            entry = entry.model_copy(update={"content_hash": compute_hash(entry.content)})
        columns = (*_TEXT_FIELDS, "tags", "metadata")
        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(columns)
        # Upsert by primary key so re-storing the same entry_id replaces the
        # row rather than failing on the PK constraint.
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns if col != "entry_id")
        self._conn.execute(
            f"INSERT INTO vault_entries ({column_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(entry_id) DO UPDATE SET {updates}",
            self._to_row(entry),
        )
        self._conn.commit()
        return entry.entry_id

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[VaultEntry]:
        """Keyword retrieval: score by per-word substring hits, top *limit*.

        Mirrors :class:`InMemoryVaultBackend.query` exactly -- the query is
        lowercased and split into words; each candidate entry scores one point
        per distinct query word found as a substring of its (lowercased)
        content; only positive-scoring entries are returned, highest score
        first, capped at *limit*. ``LIKE`` is used purely as a parameterized
        prefilter; no semantic/vector matching is involved.
        """
        query_words = query.lower().split()
        if not query_words:
            return []

        rows = self._candidate_rows(query_words, entry_type)
        scored: list[tuple[VaultEntry, int]] = []
        for row in rows:
            lowered = row["content"].lower()
            score = sum(1 for w in query_words if w in lowered)
            if score > 0:
                scored.append((self._from_row(row), score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [entry for entry, _ in scored[:limit]]

    def _candidate_rows(
        self,
        query_words: Iterable[str],
        entry_type: str | None,
    ) -> list[sqlite3.Row]:
        """Fetch rows where content matches ANY query word (parameterized).

        A row scores > 0 in :meth:`query` only if at least one (already
        lowercased) query word is a substring of the entry's lowercased
        content, so an OR of ``LIKE`` clauses against ``lower(content)`` is a
        sound, loss-free prefilter -- it can only over-include. The
        authoritative scoring in :meth:`query` re-checks every word in Python,
        so the returned set and ranking match the in-memory backend exactly.
        """
        params: list[object] = []
        like_clauses: list[str] = []
        for word in query_words:
            like_clauses.append("lower(content) LIKE '%' || ? || '%'")
            params.append(word)
        where = f"({' OR '.join(like_clauses)})"
        if entry_type is not None:
            where += " AND entry_type = ?"
            params.append(entry_type)
        cursor = self._conn.execute(
            f"SELECT * FROM vault_entries WHERE {where}",
            tuple(params),
        )
        return cursor.fetchall()

    async def exists(self, content_hash: str) -> bool:
        """Return ``True`` if a stored entry has this ``content_hash``."""
        cursor = self._conn.execute(
            "SELECT 1 FROM vault_entries WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        )
        return cursor.fetchone() is not None

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        """Return all entries whose ``source_path`` equals *source_path*."""
        cursor = self._conn.execute(
            "SELECT * FROM vault_entries WHERE source_path = ?",
            (source_path,),
        )
        return [self._from_row(row) for row in cursor.fetchall()]
