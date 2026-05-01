# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Incremental knowledge ingestion with content-hash dedup.

Standalone async functions for ingesting markdown files and session logs
into the knowledge vault via content-hash dedup.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.knowledge.chunker import chunk_markdown as _chunk_canonical
from bonfire.knowledge.hasher import content_hash
from bonfire.protocols import VaultEntry

if TYPE_CHECKING:
    from bonfire.protocols import VaultBackend


# ---------------------------------------------------------------------------
# Text extraction and classification
# ---------------------------------------------------------------------------


def _extract_text(event: dict, event_type: str) -> str | None:
    """Extract meaningful text from a session event for vault storage."""
    if event_type == "dispatch.completed":
        summary = event.get("result_summary", "")
        task = event.get("task", "")
        agent = event.get("agent_id", "")
        if summary:
            return f"Agent {agent} completed: {task}. Result: {summary}"
        return None

    if event_type == "pipeline.completed":
        wf_type = event.get("workflow_type", "")
        stages = event.get("stages_completed", 0)
        status = event.get("status", "")
        cost = event.get("total_cost_usd", 0)
        return f"Pipeline {wf_type} {status}: {stages} stages, ${cost:.2f}"

    if event_type in ("dispatch.failed", "stage.failed"):
        error_type = event.get("error_type", "")
        error_msg = event.get("error_message", "")
        stage = event.get("stage_name", event.get("agent_id", ""))
        if error_msg:
            return f"Failure in {stage}: [{error_type}] {error_msg}"
        return None

    if event_type == "session.ended":
        status = event.get("status", "")
        dispatches = event.get("dispatch_count", 0)
        cost = event.get("total_cost_usd", 0)
        return f"Session ended ({status}): {dispatches} dispatches, ${cost:.2f}"

    return None


def _classify_source(event_type: str) -> str:
    """Map event type to vault entry_type."""
    if event_type in ("dispatch.failed", "stage.failed"):
        return "error_pattern"
    if event_type == "pipeline.completed":
        return "dispatch_outcome"
    return "session_insight"


# ---------------------------------------------------------------------------
# Async ingestion functions
# ---------------------------------------------------------------------------


async def ingest_markdown(
    path: Path,
    *,
    backend: VaultBackend,
    project_name: str = "",
    git_hash: str = "",
) -> int:
    """Read a markdown file, chunk it, and store in vault with dedup.

    Delegates chunking to the canonical ``knowledge.chunker.chunk_markdown``.
    Each chunk's provenance (source_path, project_name, git_hash) flows
    through to the stored VaultEntry.

    Returns count of NEW entries stored (duplicates skipped; 0 if file
    missing or empty).
    """
    p = Path(path)
    if not p.is_file():
        return 0

    try:
        raw = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    if not raw.strip():
        return 0

    entries = _chunk_canonical(
        raw,
        source_path=str(p),
        project_name=project_name,
        git_hash=git_hash,
    )
    if not entries:
        return 0

    now = datetime.now(UTC).isoformat()
    stored = 0

    for entry in entries:
        if await backend.exists(entry.content_hash):
            continue

        customised: VaultEntry = entry.model_copy(update={"scanned_at": now})
        await backend.store(customised)
        stored += 1

    return stored


async def ingest_session(
    session_log_path: Path,
    *,
    backend: VaultBackend,
    project_name: str = "",
    git_hash: str = "",
) -> int:
    """Read JSONL session events, extract knowledge, store with dedup.

    Returns count of NEW entries stored.
    """
    p = Path(session_log_path)
    if not p.is_file():
        return 0

    now = datetime.now(UTC).isoformat()
    stored = 0

    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("event_type", "")
            text = _extract_text(event, event_type)
            if not text:
                continue

            chash = content_hash(text)
            if await backend.exists(chash):
                continue

            entry_type = _classify_source(event_type)
            entry = VaultEntry(
                content=text,
                entry_type=entry_type,
                source_path=str(session_log_path),
                project_name=project_name,
                scanned_at=now,
                git_hash=git_hash,
                content_hash=chash,
                metadata={"session_id": event.get("session_id", "")},
            )
            await backend.store(entry)
            stored += 1

    return stored


async def retrieve_context(
    query: str,
    *,
    backend: VaultBackend,
    limit: int = 5,
) -> list[VaultEntry]:
    """Query vault and return list of matching VaultEntry records.

    Pure delegation to ``backend.query(query, limit=limit)``. Returns
    empty list if no results found.
    """
    return await backend.query(query, limit=limit)
