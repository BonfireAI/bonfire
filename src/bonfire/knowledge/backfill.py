# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Batch backfill for session handoffs and memory files.

Scans directories for matching markdown files and ingests them into the
vault using the standard ``ingest_markdown`` pipeline.  Dedup is handled
by the underlying ingestion layer (content-hash based).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.knowledge.ingest import ingest_markdown

if TYPE_CHECKING:
    from bonfire.protocols import VaultBackend


async def backfill_sessions(
    sessions_dir: Path,
    *,
    backend: VaultBackend,
    project_name: str = "",
    pattern: str = "*-handoff.md",
) -> int:
    """Ingest matching handoff files from a directory. Returns total stored entries.

    Missing directory returns 0 — does not raise.
    Pattern defaults to ``*-handoff.md``; non-matching files are ignored.
    """
    p = Path(sessions_dir)
    if not p.is_dir():
        return 0

    candidates = sorted(f for f in p.glob(pattern) if f.suffix == ".md")
    # If pattern didn't match anything, fall back to all *.md files. This
    # keeps the "count stored entries" contract meaningful for arbitrary
    # session-handoff naming schemes. Empty dirs still return 0.
    if not candidates:
        candidates = sorted(f for f in p.glob("*.md"))

    total_stored = 0
    for file_path in candidates:
        stored = await ingest_markdown(
            file_path,
            backend=backend,
            project_name=project_name,
        )
        total_stored += stored
    return total_stored


async def backfill_memory(
    memory_dir: Path,
    *,
    backend: VaultBackend,
    project_name: str = "",
) -> int:
    """Ingest all ``.md`` files from a memory directory. Returns total stored.

    Non-markdown files are ignored. Missing directory returns 0.
    """
    p = Path(memory_dir)
    if not p.is_dir():
        return 0

    candidates = sorted(f for f in p.iterdir() if f.suffix == ".md" and f.is_file())
    total_stored = 0
    for file_path in candidates:
        stored = await ingest_markdown(
            file_path,
            backend=backend,
            project_name=project_name,
        )
        total_stored += stored
    return total_stored


async def backfill_all(
    root: Path,
    *,
    backend: VaultBackend,
    project_name: str = "",
) -> dict[str, int]:
    """Run full backfill from *root*: ``root/sessions/`` and ``root/memory/``.

    Returns ``{"sessions": int, "memory": int}`` — counts of newly stored
    entries per subtree. Missing subdirectories contribute 0.
    """
    root_path = Path(root)
    sessions_dir = root_path / "sessions"
    memory_dir = root_path / "memory"
    sessions = await backfill_sessions(sessions_dir, backend=backend, project_name=project_name)
    memory = await backfill_memory(memory_dir, backend=backend, project_name=project_name)
    return {"sessions": sessions, "memory": memory}
