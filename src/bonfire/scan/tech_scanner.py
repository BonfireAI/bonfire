# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""TechScanner — one VaultEntry per detected technology.

Scans a project directory for language manifests, dependency files, and
file extensions to produce a list of ``VaultEntry`` records with
``entry_type="tech_fingerprint"``.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

from bonfire.knowledge.hasher import content_hash
from bonfire.protocols import VaultBackend, VaultEntry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["TechScanner"]

# ---------------------------------------------------------------------------
# Detection tables (data-driven, not if/else chains)
# ---------------------------------------------------------------------------

LANGUAGE_MANIFESTS: dict[str, tuple[str, str]] = {
    "pyproject.toml": ("Python", "language"),
    "package.json": ("JavaScript", "language"),
    "Cargo.toml": ("Rust", "language"),
    "go.mod": ("Go", "language"),
}

# Maps lowercase dependency name prefix -> (display_name, category)
FRAMEWORK_PATTERNS: dict[str, tuple[str, str]] = {
    "django": ("Django", "framework"),
    "fastapi": ("FastAPI", "framework"),
    "react": ("React", "framework"),
    "pytest": ("pytest", "test_framework"),
}

# Maps language -> list of file extensions to count
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "Python": [".py"],
    "JavaScript": [".js", ".jsx"],
    "Rust": [".rs"],
    "Go": [".go"],
}

DEFAULT_EXCLUSIONS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


def _extract_pyproject_deps(text: str) -> set[str]:
    """Extract dependency package names from pyproject.toml text.

    Scans [project.dependencies], [project.optional-dependencies.*],
    and [tool.poetry.dependencies] sections. Also extracts names from
    inline array values like ``dev = ["pytest>=8.0"]`` and from
    inline-table forms on ``[project]`` like
    ``optional-dependencies = {dev = ["pytest>=8.0"]}``.
    Returns lowercased package names.
    """
    names: set[str] = set()
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        # Detect dependency section headers
        if re.match(
            r"\[(project\.dependencies|project\.optional-dependencies|tool\.poetry\.dependencies)",
            stripped,
            re.IGNORECASE,
        ):
            in_deps = True
            continue
        # Inline-table form on [project]: ``optional-dependencies = {...}`` or
        # inline-array form: ``dependencies = [...]``. These never produce a
        # section header that matches the regex above, so detect them
        # independently of ``in_deps`` and harvest quoted package specs from
        # the same line.
        if not stripped.startswith("#") and re.match(
            r"(optional-dependencies|dependencies)\s*=\s*[\{\[]",
            stripped,
            re.IGNORECASE,
        ):
            for spec in re.findall(r'"([^"]+)"', stripped):
                pkg = re.split(r"[><=!~\[; ]", spec)[0].strip().lower()
                if pkg:
                    names.add(pkg)
            continue
        # Any other section header ends the dep section
        if stripped.startswith("[") and in_deps:
            in_deps = False
            continue
        if in_deps and stripped and not stripped.startswith("#"):
            # TOML-style ``key = "value"`` (e.g. ``django = ">=5.0"``) — key is
            # the package name. Capture the bare-identifier LHS before '='.
            key_match = re.match(r"([A-Za-z0-9_.\-]+)\s*=", stripped)
            if key_match:
                pkg = key_match.group(1).strip().lower()
                if pkg:
                    names.add(pkg)
            # Extract all quoted strings that look like package specs
            quoted = re.findall(r'"([^"]+)"', stripped)
            if quoted:
                for spec in quoted:
                    pkg = re.split(r"[><=!~\[; ]", spec)[0].strip().lower()
                    if pkg:
                        names.add(pkg)
            elif not key_match:
                # Bare line like "django>=5.0"
                cleaned = stripped.strip('"').strip("'").strip(",").strip()
                if cleaned:
                    pkg = re.split(r"[><=!~\[; ]", cleaned)[0].strip().lower()
                    if pkg:
                        names.add(pkg)
    return names


class TechScanner:
    """Scan a project directory and produce one VaultEntry per technology."""

    def __init__(
        self,
        project_path: Path,
        project_name: str = "",
        exclusions: set[str] | None = None,
    ) -> None:
        self._project_path = project_path
        self._project_name = project_name
        self._exclusions = exclusions if exclusions is not None else DEFAULT_EXCLUSIONS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self) -> list[VaultEntry]:
        """Scan the project and return one VaultEntry per detected technology.

        Filesystem walks (``Path.rglob``) and dependency-manifest reads
        (``Path.read_text``) are blocking syscalls. The two sync helpers
        that own them — ``_count_files`` (rglob) and ``_detect_frameworks``
        (read_text) — run via :func:`asyncio.to_thread` so the
        orchestrator's event loop stays responsive when scanners fan out
        in parallel, even on a large repo where ``rglob`` traverses
        thousands of paths.
        """
        entries: list[VaultEntry] = []

        # _count_files walks rglob; _scan_language_manifests does
        # cheap is_file() probes on a fixed handful of paths. Bundle
        # both into one off-loop hop to amortize the thread handoff.
        file_counts, language_entries = await asyncio.to_thread(self._scan_languages_blocking)
        entries.extend(language_entries)
        _ = file_counts  # retained for future inspection paths

        # 2. Framework detection from dependency files — read_text on
        # requirements.txt / pyproject.toml / package.json. Off-loop.
        framework_entries = await asyncio.to_thread(self._detect_frameworks)
        entries.extend(framework_entries)

        return entries

    def _scan_languages_blocking(
        self,
    ) -> tuple[dict[str, int], list[VaultEntry]]:
        """Synchronous helper: count files + walk language manifests.

        Encapsulates the blocking part of phase 1 so ``scan`` makes a
        single ``asyncio.to_thread`` hop for all language-detection I/O.
        Returns ``(file_counts, language_entries)``.
        """
        file_counts = self._count_files()
        entries: list[VaultEntry] = []
        for manifest, (tech, category) in LANGUAGE_MANIFESTS.items():
            if (self._project_path / manifest).is_file():
                count = file_counts.get(tech, 0)
                entries.append(
                    self._make_entry(
                        technology=tech,
                        category=category,
                        confidence="high",
                        detection_method="config_file",
                        source_file=manifest,
                        file_count=count,
                    )
                )
        return file_counts, entries

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
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_files(self) -> dict[str, int]:
        """Count source files per language, respecting exclusions."""
        counts: dict[str, int] = {}
        for tech, extensions in LANGUAGE_EXTENSIONS.items():
            total = 0
            for ext in extensions:
                total += self._count_ext(ext)
            counts[tech] = total
        return counts

    def _count_ext(self, ext: str) -> int:
        """Count files with given extension, excluding excluded dirs."""
        count = 0
        for p in self._project_path.rglob(f"*{ext}"):
            if not self._is_excluded(p):
                count += 1
        return count

    def _is_excluded(self, path: Path) -> bool:
        """Check if any path component is in the exclusion set."""
        rel = path.relative_to(self._project_path)
        return any(part in self._exclusions for part in rel.parts)

    def _detect_frameworks(self) -> list[VaultEntry]:
        """Detect frameworks from dependency files."""
        entries: list[VaultEntry] = []
        seen: set[str] = set()

        # requirements.txt — line-based, extract package name before specifier
        req_path = self._project_path / "requirements.txt"
        if req_path.is_file():
            text = req_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#"):
                    continue
                # Extract package name: split on version specifiers
                pkg_name = re.split(r"[><=!~\[]", line_stripped)[0].strip().lower()
                for pattern, (tech, category) in FRAMEWORK_PATTERNS.items():
                    if pkg_name == pattern and tech not in seen:
                        seen.add(tech)
                        entries.append(
                            self._make_entry(
                                technology=tech,
                                category=category,
                                confidence="high",
                                detection_method="dependency_file",
                                source_file="requirements.txt",
                            )
                        )

        # pyproject.toml — scan dependency lines only, not the whole file
        pyproject_path = self._project_path / "pyproject.toml"
        if pyproject_path.is_file():
            text = pyproject_path.read_text(encoding="utf-8")
            dep_names = _extract_pyproject_deps(text)
            for pattern, (tech, category) in FRAMEWORK_PATTERNS.items():
                if tech not in seen and pattern in dep_names:
                    seen.add(tech)
                    entries.append(
                        self._make_entry(
                            technology=tech,
                            category=category,
                            confidence="high",
                            detection_method="dependency_file",
                            source_file="pyproject.toml",
                        )
                    )

        # package.json — parse JSON dependencies
        pkg_path = self._project_path / "package.json"
        if pkg_path.is_file():
            try:
                data = json.loads(pkg_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            all_deps: dict[str, Any] = {}
            all_deps.update(data.get("dependencies", {}))
            all_deps.update(data.get("devDependencies", {}))
            for dep_name in all_deps:
                dep_lower = dep_name.lower()
                for pattern, (tech, category) in FRAMEWORK_PATTERNS.items():
                    if dep_lower == pattern and tech not in seen:
                        seen.add(tech)
                        entries.append(
                            self._make_entry(
                                technology=tech,
                                category=category,
                                confidence="high",
                                detection_method="dependency_file",
                                source_file="package.json",
                            )
                        )

        return entries

    def _make_entry(
        self,
        *,
        technology: str,
        category: str,
        confidence: str,
        detection_method: str,
        source_file: str,
        file_count: int | None = None,
    ) -> VaultEntry:
        """Build a VaultEntry for a detected technology."""
        content = f"{technology}\n\nDetected from {source_file} in {self._project_name}."

        metadata: dict[str, Any] = {
            "technology": technology,
            "category": category,
            "confidence": confidence,
            "detection_method": detection_method,
        }
        if file_count is not None:
            metadata["file_count"] = file_count

        tags = [technology.lower(), category]

        return VaultEntry(
            content=content,
            entry_type="tech_fingerprint",
            source_path=str(self._project_path),
            project_name=self._project_name,
            content_hash=content_hash(content),
            tags=tags,
            metadata=metadata,
        )
