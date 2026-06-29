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
embeddings, no vectors. It reads the rows with a static ``SELECT`` (optionally
narrowed by ``entry_type``) and does the scoring and ranking in Python, which
mirrors the in-memory backend byte-for-byte. The SQL carries only bound
parameters -- no value is ever formatted into a statement string.

The async methods wrap synchronous ``sqlite3`` calls (the same pattern the
in-memory backend uses) -- no ``aiosqlite`` or other added dependency.

Schema is versioned (BubbleGum): ``_SCHEMA_VERSION`` plus an idempotent,
forward-only ``_ensure_schema``. A ``vault_meta`` row records the version so
a future migration can detect and upgrade an older file.
"""

from __future__ import annotations

import json
import sqlite3

from bonfire.knowledge.hasher import content_hash as compute_hash
from bonfire.protocols import VaultEntry

# Forward-only schema version. Bump only alongside a migration step in
# ``_ensure_schema``; never rewrite history.
_SCHEMA_VERSION = 1

# Static statements. Every value is bound (``?``); no identifier or value is
# ever formatted into the SQL string. The INSERT column order matches
# ``_to_row`` (``_TEXT_FIELDS`` then ``tags``, ``metadata``).
_INSERT_SQL = (
    "INSERT INTO vault_entries "
    "(entry_id, content, entry_type, source_path, project_name, "
    "scanned_at, git_hash, content_hash, tags, metadata) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(entry_id) DO UPDATE SET "
    "content=excluded.content, entry_type=excluded.entry_type, "
    "source_path=excluded.source_path, project_name=excluded.project_name, "
    "scanned_at=excluded.scanned_at, git_hash=excluded.git_hash, "
    "content_hash=excluded.content_hash, tags=excluded.tags, "
    "metadata=excluded.metadata"
)
_SELECT_ALL = "SELECT * FROM vault_entries"
_SELECT_BY_TYPE = "SELECT * FROM vault_entries WHERE entry_type = ?"

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
        # Upsert by primary key so re-storing the same entry_id replaces the
        # row rather than failing on the PK constraint.
        self._conn.execute(_INSERT_SQL, self._to_row(entry))
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
        first, capped at *limit*. The rows are read with a static ``SELECT``
        (optionally narrowed by ``entry_type``); no semantic/vector matching is
        involved.
        """
        query_words = query.lower().split()
        if not query_words:
            return []

        rows = self._candidate_rows(entry_type)
        scored: list[tuple[VaultEntry, int]] = []
        for row in rows:
            lowered = row["content"].lower()
            score = sum(1 for w in query_words if w in lowered)
            if score > 0:
                scored.append((self._from_row(row), score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [entry for entry, _ in scored[:limit]]

    def _candidate_rows(self, entry_type: str | None) -> list[sqlite3.Row]:
        """Read the rows to score, optionally narrowed by ``entry_type``.

        The authoritative scoring in :meth:`query` re-checks every query word
        in Python, exactly as the in-memory backend does, so reading the full
        table (or the ``entry_type`` slice of it) yields the same result set
        and ranking. Both statements are static literals carrying only a bound
        parameter.
        """
        if entry_type is None:
            cursor = self._conn.execute(_SELECT_ALL)
        else:
            cursor = self._conn.execute(_SELECT_BY_TYPE, (entry_type,))
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
