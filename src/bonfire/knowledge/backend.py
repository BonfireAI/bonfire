# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""LanceDB-backed vault backend.

Connects to existing ``.bonfire/vault/`` data. Auto-migrates from ``vault``
table (v1 schema) to ``vault_v2`` (expanded schema) on first connect.
Vectors are NEVER re-embedded during migration.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from bonfire.knowledge.hasher import content_hash as compute_hash

if TYPE_CHECKING:
    from bonfire.knowledge.embeddings import EmbeddingProvider
    from bonfire.protocols import VaultEntry

logger = logging.getLogger(__name__)


class LanceDBBackend:
    """LanceDB-backed vault with auto-migration from v1 schema."""

    def __init__(self, vault_path: str, embedder: EmbeddingProvider) -> None:
        self._vault_path = vault_path
        self._embedder = embedder
        self._db: Any = None
        self._table: Any = None

    async def store(self, entry: VaultEntry) -> str:
        self._ensure_connected()
        vector = self._embedder.embed([entry.content])[0]
        c_hash = entry.content_hash or compute_hash(entry.content)
        scanned = entry.scanned_at or datetime.now(UTC).isoformat()

        row = {
            "entry_id": entry.entry_id,
            "content": entry.content,
            "vector": vector,
            "entry_type": entry.entry_type,
            "source_path": entry.source_path,
            "project_name": entry.project_name,
            "scanned_at": scanned,
            "git_hash": entry.git_hash,
            "content_hash": c_hash,
            "tags_json": json.dumps(entry.tags),
            "metadata_json": json.dumps(entry.metadata),
        }
        self._table.add([row])
        return entry.entry_id

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[VaultEntry]:
        self._ensure_connected()
        if self._table.count_rows() == 0:
            return []

        query_vec = self._embedder.embed([query])[0]
        search = self._table.search(query_vec).limit(limit)

        if entry_type is not None:
            safe_type = entry_type.replace("'", "''")
            search = search.where(f"entry_type = '{safe_type}'")

        try:
            results = search.to_list()
        except Exception as exc:
            logger.warning("Vault query failed: %s", exc)
            return []

        return [self._record_to_entry(r) for r in results]

    async def exists(self, content_hash: str) -> bool:
        self._ensure_connected()
        if self._table.count_rows() == 0:
            return False
        safe_hash = content_hash.replace("'", "''")
        try:
            results = (
                self._table.search([0.0] * self._embedder.dim)
                .where(f"content_hash = '{safe_hash}'")
                .limit(1)
                .to_list()
            )
            return len(results) > 0
        except Exception:
            return False

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        self._ensure_connected()
        if self._table.count_rows() == 0:
            return []
        safe_path = source_path.replace("'", "''")
        try:
            results = (
                self._table.search([0.0] * self._embedder.dim)
                .where(f"source_path = '{safe_path}'")
                .limit(1000)
                .to_list()
            )
            return [self._record_to_entry(r) for r in results]
        except Exception as exc:
            logger.warning("Vault get_by_source failed: %s", exc)
            return []

    def _ensure_connected(self) -> None:
        """Lazy connect. Runs migration if vault_v2 doesn't exist."""
        if self._table is not None:
            return

        import lancedb

        self._db = lancedb.connect(self._vault_path)
        tables = self._db.table_names()

        if "vault_v2" in tables:
            self._table = self._db.open_table("vault_v2")
        elif "vault" in tables:
            logger.info("Migrating vault table to vault_v2 schema...")
            self._table = self._migrate_to_v2()
            logger.info("Migration complete.")
        else:
            self._table = self._create_v2_table()

    def _create_v2_table(self) -> Any:
        """Create a fresh vault_v2 table."""
        import pyarrow as pa

        schema = pa.schema(
            [
                pa.field("entry_id", pa.utf8()),
                pa.field("content", pa.utf8()),
                pa.field("vector", pa.list_(pa.float32(), self._embedder.dim)),
                pa.field("entry_type", pa.utf8()),
                pa.field("source_path", pa.utf8()),
                pa.field("project_name", pa.utf8()),
                pa.field("scanned_at", pa.utf8()),
                pa.field("git_hash", pa.utf8()),
                pa.field("content_hash", pa.utf8()),
                pa.field("tags_json", pa.utf8()),
                pa.field("metadata_json", pa.utf8()),
            ]
        )
        return self._db.create_table("vault_v2", schema=schema)

    def _migrate_to_v2(self) -> Any:
        """Migrate vault -> vault_v2. Vectors preserved byte-for-byte.

        CRITICAL: vectors are NEVER re-embedded. They are copied exactly.
        """
        old_table = self._db.open_table("vault")
        new_table = self._create_v2_table()

        total = old_table.count_rows()
        if total == 0:
            return new_table

        # Read all records via zero-vector search with high limit.
        dim = len(old_table.search([0.0] * 768).limit(1).to_list()[0]["vector"])
        batch_size = 500
        offset = 0

        while offset < total:
            results = old_table.search([0.0] * dim).limit(batch_size + offset).to_list()
            batch_records = results[offset : offset + batch_size]
            if not batch_records:
                break

            rows = []
            for record in batch_records:
                meta_raw = record.get("metadata_json", "{}")
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else {}

                rows.append(
                    {
                        "entry_id": record.get("source_id", ""),
                        "content": record["text"],
                        "vector": record["vector"],  # SACRED -- byte-for-byte
                        "entry_type": record.get("source_type", "unknown"),
                        "source_path": meta.get("filename", record.get("source_id", "")),
                        "project_name": record.get("project_name", ""),
                        "scanned_at": record.get("timestamp", ""),
                        "git_hash": "",
                        "content_hash": compute_hash(record["text"]),
                        "tags_json": "[]",
                        "metadata_json": json.dumps(
                            {
                                **meta,
                                "migrated_from": "vault_v1",
                                "quality_score": record.get("quality_score"),
                                "contributor_id": record.get("contributor_id"),
                            }
                        ),
                    }
                )

            new_table.add(rows)
            offset += len(batch_records)
            logger.info("Migrated %d / %d records", min(offset, total), total)

        return new_table

    @staticmethod
    def _record_to_entry(record: dict[str, Any]) -> VaultEntry:
        """Convert a LanceDB row dict to a VaultEntry."""
        from bonfire.protocols import VaultEntry

        tags_raw = record.get("tags_json", "[]")
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else []
        meta_raw = record.get("metadata_json", "{}")
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else {}

        return VaultEntry(
            entry_id=record.get("entry_id", ""),
            content=record.get("content", ""),
            entry_type=record.get("entry_type", ""),
            source_path=record.get("source_path", ""),
            project_name=record.get("project_name", ""),
            scanned_at=record.get("scanned_at", ""),
            git_hash=record.get("git_hash", ""),
            content_hash=record.get("content_hash", ""),
            tags=tags,
            metadata=meta,
        )
