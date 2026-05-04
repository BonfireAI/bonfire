# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""DecisionRecorder — extract architectural decisions from markdown documents.

Scans markdown files for decision patterns (ADR format, "Use X not Y",
"We chose X over Y", "X won", rejected alternatives) and produces
``VaultEntry`` records with ``entry_type="decision_record"``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from bonfire.knowledge.hasher import content_hash
from bonfire.protocols import VaultBackend, VaultEntry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["DecisionRecorder"]

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# "Use X for ... Do not use Y." — single-line only (no DOTALL)
_USE_NOT_RE = re.compile(
    r"[Uu]se\s+[`\"]?([^\n]+?)[`\"]?\s+for\s+[^\n]+?\.\s*[Dd]o\s+not\s+use\s+[`\"]?([^\n]+?)[`\"]?\s*\.",
)

# "Use X, not Y" inline form
_USE_NOT_INLINE_RE = re.compile(
    r"[Uu]se\s+[`\"]?([^\n]+?)[`\"]?,?\s+not\s+[`\"]?([^\n]+?)[`\"]?\s*(?:[.\n]|$)",
)

# "We chose/selected/picked X over Y"
_CHOSE_OVER_RE = re.compile(
    r"[Ww]e\s+(?:chose|selected|picked)\s+(.+?)\s+over\s+(.+?)(?:\s+for|\s*(?:[.\n]|$))",
)

# "X won" / "X approach won" — case-insensitive
_X_WON_RE = re.compile(
    r"([A-Za-z][A-Za-z]+(?:\s+[a-zA-Z]+)?)\s+(?:approach\s+)?won\b",
    re.IGNORECASE,
)

# "Rejected: Y (reason)" lines
_REJECTED_RE = re.compile(
    r"[Rr]ejected:\s*(.+?)(?:\n|$)",
)

# Numbered items in a Decision section: "1. blah" "2. blah"
_NUMBERED_ITEM_RE = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)


def _detect_source_format(text: str) -> str:
    """Determine the source format of a markdown document."""
    has_context = bool(re.search(r"^##\s+Context", text, re.MULTILINE))
    has_decision = bool(re.search(r"^##\s+Decision", text, re.MULTILINE))

    if has_context and has_decision:
        return "adr"

    # Handoff indicators — require "X won" or "approach won" pattern, not bare "won"
    if _X_WON_RE.search(text) or re.search(r"(?i)handoff|session\s+\d+", text):
        return "handoff"

    return "prose"


def _extract_decision_section(text: str) -> str | None:
    """Extract the content of a ## Decision section."""
    match = re.search(r"^##\s+Decision\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


class DecisionRecorder:
    """Scan markdown files for architectural decision patterns."""

    def __init__(self, source_path: Path, project_name: str = "") -> None:
        self._source_path = source_path
        self._project_name = project_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self) -> list[VaultEntry]:
        """Scan source path for decisions and return VaultEntry list."""
        files = self._collect_files()
        entries: list[VaultEntry] = []
        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not text.strip():
                continue
            entries.extend(self._extract_from_text(text, file_path))
        return entries

    async def scan_and_store(self, vault: VaultBackend) -> int:
        """Scan, deduplicate via content_hash, store new entries. Return count stored."""
        entries = await self.scan()
        stored = 0
        for entry in entries:
            if not await vault.exists(entry.content_hash):
                await vault.store(entry)
                stored += 1
        return stored

    # ------------------------------------------------------------------
    # File collection
    # ------------------------------------------------------------------

    def _collect_files(self) -> list[Path]:
        """Collect markdown files from the source path."""
        p = self._source_path
        if not p.exists():
            return []
        if p.is_file():
            if p.suffix == ".md":
                return [p]
            return []
        # Directory: collect all .md files recursively
        return sorted(p.rglob("*.md"))

    # ------------------------------------------------------------------
    # Extraction engine
    # ------------------------------------------------------------------

    def _extract_from_text(self, text: str, file_path: Path) -> list[VaultEntry]:
        """Extract all decision entries from a single markdown document."""
        source_format = _detect_source_format(text)
        entries: list[VaultEntry] = []
        seen_texts: set[str] = set()

        if source_format == "adr":
            entries.extend(self._extract_adr_decisions(text, file_path, seen_texts))

        # Pattern-based extraction (works across all formats)
        entries.extend(self._extract_pattern_decisions(text, file_path, source_format, seen_texts))

        return entries

    def _extract_adr_decisions(
        self, text: str, file_path: Path, seen_texts: set[str]
    ) -> list[VaultEntry]:
        """Extract decisions from ADR-structured documents."""
        entries: list[VaultEntry] = []
        decision_section = _extract_decision_section(text)
        if not decision_section:
            return entries

        # Collect rejected alternatives from the decision section
        rejected = [m.group(1).strip() for m in _REJECTED_RE.finditer(decision_section)]

        # Check for numbered items
        numbered = _NUMBERED_ITEM_RE.findall(decision_section)
        if numbered:
            for item in numbered:
                item_clean = item.strip()
                norm = item_clean.lower()
                if norm not in seen_texts:
                    seen_texts.add(norm)
                    entries.append(
                        self._make_entry(
                            decision_text=item_clean,
                            content=item_clean,
                            source_format="adr",
                            confidence="high",
                            file_path=file_path,
                            rejected_alternatives=[],
                        )
                    )
        else:
            # Single decision block — extract the whole section
            # Strip out "Rejected:" lines from the main decision text
            decision_text = re.sub(r"[Rr]ejected:\s*(.+?)(?:\n|$)", "", decision_section).strip()
            if decision_text:
                norm = decision_text.lower()
                if norm not in seen_texts:
                    seen_texts.add(norm)
                    entries.append(
                        self._make_entry(
                            decision_text=decision_text,
                            content=decision_text,
                            source_format="adr",
                            confidence="high",
                            file_path=file_path,
                            rejected_alternatives=rejected if rejected else [],
                        )
                    )

        return entries

    def _extract_pattern_decisions(
        self,
        text: str,
        file_path: Path,
        source_format: str,
        seen_texts: set[str],
    ) -> list[VaultEntry]:
        """Extract decisions using regex patterns."""
        entries: list[VaultEntry] = []
        confidence = "high" if source_format == "adr" else "medium"

        # "Use X for ... Do not use Y."
        for m in _USE_NOT_RE.finditer(text):
            chosen = m.group(1).strip()
            rejected = m.group(2).strip()
            decision_text = f"Use {chosen}, not {rejected}"
            norm = decision_text.lower()
            if norm not in seen_texts:
                seen_texts.add(norm)
                entries.append(
                    self._make_entry(
                        decision_text=decision_text,
                        content=m.group(0).strip(),
                        source_format=source_format,
                        confidence=confidence,
                        file_path=file_path,
                        rejected_alternatives=[rejected],
                    )
                )

        # "Use X, not Y" inline
        for m in _USE_NOT_INLINE_RE.finditer(text):
            chosen = m.group(1).strip()
            rejected = m.group(2).strip()
            decision_text = f"Use {chosen}, not {rejected}"
            norm = decision_text.lower()
            if norm not in seen_texts:
                seen_texts.add(norm)
                entries.append(
                    self._make_entry(
                        decision_text=decision_text,
                        content=m.group(0).strip(),
                        source_format=source_format,
                        confidence=confidence,
                        file_path=file_path,
                        rejected_alternatives=[rejected],
                    )
                )

        # "We chose X over Y"
        for m in _CHOSE_OVER_RE.finditer(text):
            chosen = m.group(1).strip()
            rejected = m.group(2).strip()
            decision_text = f"We chose {chosen} over {rejected}"
            norm = decision_text.lower()
            if norm not in seen_texts:
                seen_texts.add(norm)
                entries.append(
                    self._make_entry(
                        decision_text=decision_text,
                        content=m.group(0).strip(),
                        source_format=source_format,
                        confidence=confidence,
                        file_path=file_path,
                        rejected_alternatives=[rejected],
                    )
                )

        # "X won" / "X approach won"
        for m in _X_WON_RE.finditer(text):
            subject = m.group(1).strip()
            decision_text = f"{subject} approach won"
            norm = decision_text.lower()
            if norm not in seen_texts:
                seen_texts.add(norm)
                fmt = "handoff" if source_format != "adr" else source_format
                conf = "medium" if fmt == "handoff" else confidence
                entries.append(
                    self._make_entry(
                        decision_text=decision_text,
                        content=m.group(0).strip(),
                        source_format=fmt,
                        confidence=conf,
                        file_path=file_path,
                    )
                )

        return entries

    # ------------------------------------------------------------------
    # Entry builder
    # ------------------------------------------------------------------

    def _make_entry(
        self,
        *,
        decision_text: str,
        content: str,
        source_format: str,
        confidence: str,
        file_path: Path,
        rejected_alternatives: list[str] | None = None,
    ) -> VaultEntry:
        """Build a VaultEntry for a detected decision."""
        metadata: dict[str, Any] = {
            "decision_text": decision_text,
            "source_format": source_format,
            "confidence": confidence,
        }
        if rejected_alternatives:
            metadata["rejected_alternatives"] = rejected_alternatives

        tags = ["decision", source_format]

        return VaultEntry(
            content=content,
            entry_type="decision_record",
            source_path=str(file_path),
            project_name=self._project_name,
            content_hash=content_hash(content),
            tags=tags,
            metadata=metadata,
        )
