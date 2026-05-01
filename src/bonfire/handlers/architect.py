# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Analyst pipeline stage handler.

Scans a project, extracts module signatures, chunks content, and stores
everything in the vault with content-hash deduplication.

The module exposes ``ROLE: AgentRole = AgentRole.ANALYST`` for generic-
vocabulary discipline. Display translation (analyst -> "Architect")
happens in the display layer via ``ROLE_DISPLAY[ROLE].gamified``; this
module never hardcodes the gamified display name in code.

Note: the ``bonfire.knowledge`` subsystem (``ProjectScanner``, ``chunker``,
``hasher``, ``memory.InMemoryVaultBackend``) is loaded lazily to defer module
load until the Architect stage is dispatched. Imports are performed lazily
inside :meth:`ArchitectHandler.handle` to defer loading of ``ast``, ``fnmatch``,
and dataclass machinery until the stage runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import ErrorDetail

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec
    from bonfire.protocols import VaultBackend

# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.ANALYST


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class ArchitectHandler:
    """Pipeline stage handler for the analyst role.

    Scans a project root, extracts signatures, chunks source and
    markdown, and stores the results in the vault with content-hash
    dedup. Emits a JSON summary in ``envelope.result``.
    """

    def __init__(
        self,
        *,
        vault: VaultBackend,
        project_root: Path,
        project_name: str = "",
        git_hash: str = "",
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self._vault = vault
        self._project_root = project_root
        self._project_name = project_name
        self._git_hash = git_hash
        self._exclude_patterns = exclude_patterns

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Execute project scan. Returns envelope with JSON summary in result."""
        try:
            # Lazy imports — defer knowledge module load until handler.handle() is invoked.
            from bonfire.knowledge.chunker import chunk_markdown, chunk_source_file
            from bonfire.knowledge.hasher import content_hash
            from bonfire.knowledge.scanner import ProjectScanner
            from bonfire.protocols import VaultEntry

            scanner = ProjectScanner(
                self._project_root,
                exclude_patterns=self._exclude_patterns,
            )

            # Pass 1: discover files.
            manifest = scanner.discover()

            # Pass 2: extract signatures.
            signatures = scanner.extract_signatures(manifest)

            entries_stored = 0
            entries_skipped = 0
            now = datetime.now(UTC).isoformat()

            # Store project manifest entry.
            manifest_content = json.dumps(
                {
                    "project_root": str(manifest.project_root),
                    "total_files": manifest.total_files,
                    "total_python_source": manifest.total_python_source,
                    "total_markdown": manifest.total_markdown,
                    "total_size_bytes": manifest.total_size_bytes,
                    "files": [
                        {
                            "path": str(f.path),
                            "category": f.category,
                            "content_hash": f.content_hash,
                            "size_bytes": f.size_bytes,
                        }
                        for f in manifest.files
                    ],
                }
            )
            manifest_hash = content_hash(manifest_content)
            manifest_entry = VaultEntry(
                content=manifest_content,
                entry_type="project_manifest",
                content_hash=manifest_hash,
                source_path=str(manifest.project_root),
                project_name=self._project_name,
                git_hash=self._git_hash,
                scanned_at=now,
                tags=["manifest"],
            )

            if not await self._vault.exists(manifest_hash):
                await self._vault.store(manifest_entry)
                entries_stored += 1
            else:
                entries_skipped += 1

            # Store module signatures.
            sig_count = 0
            for sig in signatures:
                sig_content = json.dumps(
                    {
                        "module_path": sig.module_path,
                        "source_path": sig.source_path,
                        "classes": sig.classes,
                        "functions": sig.functions,
                        "imports": sig.imports,
                        "docstring": sig.docstring,
                    }
                )
                sig_hash = content_hash(sig_content)
                sig_entry = VaultEntry(
                    content=sig_content,
                    entry_type="module_signature",
                    content_hash=sig_hash,
                    source_path=sig.source_path,
                    project_name=self._project_name,
                    git_hash=self._git_hash,
                    scanned_at=now,
                    tags=["signature", "python"],
                )

                if not await self._vault.exists(sig_hash):
                    await self._vault.store(sig_entry)
                    entries_stored += 1
                    sig_count += 1
                else:
                    entries_skipped += 1

            # Chunk and store file contents.
            chunk_count = 0
            for file_info in manifest.files:
                full_path = self._project_root / file_info.path
                try:
                    text = full_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue

                if not text.strip():
                    continue

                if file_info.category == "markdown":
                    chunks: list[Any] = chunk_markdown(
                        text,
                        source_path=str(file_info.path),
                        project_name=self._project_name,
                        git_hash=self._git_hash,
                    )
                else:
                    chunks = chunk_source_file(
                        text,
                        source_path=str(file_info.path),
                        project_name=self._project_name,
                        git_hash=self._git_hash,
                    )

                for chunk in chunks:
                    if not await self._vault.exists(chunk.content_hash):
                        await self._vault.store(chunk)
                        entries_stored += 1
                        chunk_count += 1
                    else:
                        entries_skipped += 1

            summary = {
                "total_files": manifest.total_files,
                "entries_stored": entries_stored,
                "entries_skipped": entries_skipped,
                "module_signatures": sig_count,
                "code_chunks": chunk_count,
            }

            return envelope.with_result(json.dumps(summary))
        except Exception as exc:
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    stage_name=stage.name,
                ),
            )
