# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Content chunking for vault ingestion.

Split markdown and source files into VaultEntry chunks suitable for
embedding and retrieval.  This is the canonical chunker — all callers
(including knowledge/ingest.py) delegate here.
"""

from __future__ import annotations

import re

from bonfire.knowledge.hasher import content_hash
from bonfire.protocols import VaultEntry

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n?", re.DOTALL)


def chunk_markdown(
    content: str,
    *,
    source_path: str,
    project_name: str = "",
    git_hash: str = "",
    max_chunk_size: int = 2000,
) -> list[VaultEntry]:
    """Split markdown by H1-H3 headers, then by size. Returns VaultEntry list."""
    if not content.strip():
        return []

    # Strip YAML frontmatter before chunking
    content = _FRONTMATTER_RE.sub("", content)

    if not content.strip():
        return []

    # Split on H1-H3 headers, keeping the header with its section
    sections = re.split(r"(?=^#{1,3}\s+)", content, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]

    if not sections:
        return []

    # Build header chain tracking
    header_stack: list[str] = []
    chunks_raw: list[tuple[str, str]] = []  # (text, header_chain)

    for section in sections:
        # Extract header if present
        header_match = re.match(r"^(#{1,3})\s+(.+)", section)
        if header_match:
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            # Trim stack to current level
            header_stack = header_stack[: level - 1]
            header_stack.append(title)

        chain = " > ".join(header_stack) if header_stack else ""

        # If section is too large, split at paragraph boundaries
        if len(section) > max_chunk_size:
            paragraphs = section.split("\n\n")
            current = ""
            for para in paragraphs:
                # If a single paragraph exceeds max, split it by words
                if len(para) > max_chunk_size:
                    if current.strip():
                        chunks_raw.append((current.strip(), chain))
                        current = ""
                    words = para.split()
                    word_chunk = ""
                    for word in words:
                        if word_chunk and len(word_chunk) + len(word) + 1 > max_chunk_size:
                            chunks_raw.append((word_chunk.strip(), chain))
                            word_chunk = word
                        else:
                            word_chunk = word_chunk + " " + word if word_chunk else word
                    if word_chunk.strip():
                        current = word_chunk
                elif current and len(current) + len(para) + 2 > max_chunk_size:
                    chunks_raw.append((current.strip(), chain))
                    current = para
                else:
                    current = current + "\n\n" + para if current else para
            if current.strip():
                chunks_raw.append((current.strip(), chain))
        else:
            chunks_raw.append((section.strip(), chain))

    total = len(chunks_raw)
    entries: list[VaultEntry] = []

    for i, (text, chain) in enumerate(chunks_raw):
        entries.append(
            VaultEntry(
                content=text,
                entry_type="code_chunk",
                content_hash=content_hash(text),
                source_path=source_path,
                project_name=project_name,
                git_hash=git_hash,
                tags=["chunk", "markdown"],
                metadata={
                    "chunk_index": i,
                    "total_chunks": total,
                    "header_chain": chain,
                },
            )
        )

    return entries


def chunk_source_file(
    content: str,
    *,
    source_path: str,
    project_name: str = "",
    git_hash: str = "",
    max_chunk_size: int = 2000,
) -> list[VaultEntry]:
    """Split source code at class/function boundaries. Fallback to size-based."""
    if not content.strip():
        return []

    chunks_raw: list[str] = []

    # Try to split at top-level class/function definitions
    if source_path.endswith(".py"):
        # Split at lines that start with 'class ' or 'def ' or 'async def '
        pattern = r"(?=^(?:class |def |async def ))"
        parts = re.split(pattern, content, flags=re.MULTILINE)
        parts = [p for p in parts if p.strip()]

        if len(parts) >= 2:
            chunks_raw = [p.strip() for p in parts]
        else:
            # Single or no definitions, use size-based
            chunks_raw = _size_based_split(content, max_chunk_size)
    else:
        # Non-Python: size-based splitting
        chunks_raw = _size_based_split(content, max_chunk_size)

    total = len(chunks_raw)
    tag = "python" if source_path.endswith(".py") else "source"
    entries: list[VaultEntry] = []

    for i, text in enumerate(chunks_raw):
        entries.append(
            VaultEntry(
                content=text,
                entry_type="code_chunk",
                content_hash=content_hash(text),
                source_path=source_path,
                project_name=project_name,
                git_hash=git_hash,
                tags=["chunk", tag],
                metadata={
                    "chunk_index": i,
                    "total_chunks": total,
                    "header_chain": "",
                },
            )
        )

    return entries


def _size_based_split(content: str, max_chunk_size: int) -> list[str]:
    """Fall back to splitting by size at line boundaries."""
    lines = content.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1  # +1 for newline
        if current and current_size + line_size > max_chunk_size:
            chunks.append("\n".join(current).strip())
            current = [line]
            current_size = line_size
        else:
            current.append(line)
            current_size += line_size

    if current:
        text = "\n".join(current).strip()
        if text:
            chunks.append(text)

    return chunks if chunks else [content.strip()]
