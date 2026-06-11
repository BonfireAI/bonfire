# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""TechScanner — one VaultEntry per detected technology.

Scans a project directory for language manifests, dependency files, and
file extensions to produce a list of ``VaultEntry`` records with
``entry_type="tech_fingerprint"``.
"""

from __future__ import annotations

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


_DEP_SECTION_RE = re.compile(
    r"\[(project\.dependencies|project\.optional-dependencies|tool\.poetry\.dependencies)",
    re.IGNORECASE,
)
# Inline-table form on [project]: ``optional-dependencies = {...}`` or
# inline-array form: ``dependencies = [...]``. These never produce a section
# header matching _DEP_SECTION_RE, so they are detected independently.
_INLINE_DEP_RE = re.compile(
    r"(optional-dependencies|dependencies)\s*=\s*[\{\[]",
    re.IGNORECASE,
)


def _pkg_from_spec(spec: str) -> str:
    """Lowercased package name from a PEP 508-ish spec like ``pytest>=8.0``."""
    return re.split(r"[><=!~\[; ]", spec)[0].strip().lower()


def _pkgs_from_quoted_specs(line: str) -> set[str]:
    """Harvest package names from every double-quoted spec on the line."""
    names: set[str] = set()
    for spec in re.findall(r'"([^"]+)"', line):
        pkg = _pkg_from_spec(spec)
        if pkg:
            names.add(pkg)
    return names


def _pkgs_from_dep_line(stripped: str) -> set[str]:
    """Harvest package names from one non-comment line inside a dep section."""
    names: set[str] = set()
    # TOML-style ``key = "value"`` (e.g. ``django = ">=5.0"``) — key is
    # the package name. Capture the bare-identifier LHS before '='.
    key_match = re.match(r"([A-Za-z0-9_.\-]+)\s*=", stripped)
    if key_match:
        pkg = key_match.group(1).strip().lower()
        if pkg:
            names.add(pkg)
    # Extract all quoted strings that look like package specs
    quoted_names = _pkgs_from_quoted_specs(stripped)
    if quoted_names:
        names.update(quoted_names)
    elif not key_match:
        # Bare line like "django>=5.0"
        cleaned = stripped.strip('"').strip("'").strip(",").strip()
        if cleaned:
            pkg = _pkg_from_spec(cleaned)
            if pkg:
                names.add(pkg)
    return names


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
        if _DEP_SECTION_RE.match(stripped):
            in_deps = True
            continue
        if not stripped.startswith("#") and _INLINE_DEP_RE.match(stripped):
            names.update(_pkgs_from_quoted_specs(stripped))
            continue
        # Any other section header ends the dep section
        if stripped.startswith("[") and in_deps:
            in_deps = False
            continue
        if in_deps and stripped and not stripped.startswith("#"):
            names.update(_pkgs_from_dep_line(stripped))
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
        """Scan the project and return one VaultEntry per detected technology."""
        entries: list[VaultEntry] = []
        file_counts = self._count_files()

        # 1. Language detection from config files
        for manifest, (tech, category) in LANGUAGE_MANIFESTS.items():
            if (self._project_path / manifest).is_file():
                count = file_counts.get(tech, 0)
                entry = self._make_entry(
                    technology=tech,
                    category=category,
                    confidence="high",
                    detection_method="config_file",
                    source_file=manifest,
                    file_count=count,
                )
                entries.append(entry)

        # 2. Framework detection from dependency files
        entries.extend(self._detect_frameworks())

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
        entries.extend(self._frameworks_from_requirements(seen))
        entries.extend(self._frameworks_from_pyproject(seen))
        entries.extend(self._frameworks_from_package_json(seen))
        return entries

    def _framework_entry(self, *, technology: str, category: str, source_file: str) -> VaultEntry:
        """Build the dependency-file framework entry (shared shape)."""
        return self._make_entry(
            technology=technology,
            category=category,
            confidence="high",
            detection_method="dependency_file",
            source_file=source_file,
        )

    def _frameworks_from_requirements(self, seen: set[str]) -> list[VaultEntry]:
        """requirements.txt — line-based, extract package name before specifier."""
        req_path = self._project_path / "requirements.txt"
        if not req_path.is_file():
            return []
        entries: list[VaultEntry] = []
        for line in req_path.read_text(encoding="utf-8").splitlines():
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue
            # Extract package name: split on version specifiers
            pkg_name = re.split(r"[><=!~\[]", line_stripped)[0].strip().lower()
            for pattern, (tech, category) in FRAMEWORK_PATTERNS.items():
                if pkg_name == pattern and tech not in seen:
                    seen.add(tech)
                    entries.append(
                        self._framework_entry(
                            technology=tech,
                            category=category,
                            source_file="requirements.txt",
                        )
                    )
        return entries

    def _frameworks_from_pyproject(self, seen: set[str]) -> list[VaultEntry]:
        """pyproject.toml — scan dependency lines only, not the whole file."""
        pyproject_path = self._project_path / "pyproject.toml"
        if not pyproject_path.is_file():
            return []
        entries: list[VaultEntry] = []
        dep_names = _extract_pyproject_deps(pyproject_path.read_text(encoding="utf-8"))
        for pattern, (tech, category) in FRAMEWORK_PATTERNS.items():
            if tech not in seen and pattern in dep_names:
                seen.add(tech)
                entries.append(
                    self._framework_entry(
                        technology=tech,
                        category=category,
                        source_file="pyproject.toml",
                    )
                )
        return entries

    def _frameworks_from_package_json(self, seen: set[str]) -> list[VaultEntry]:
        """package.json — parse JSON dependencies + devDependencies."""
        pkg_path = self._project_path / "package.json"
        if not pkg_path.is_file():
            return []
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        all_deps: dict[str, Any] = {}
        all_deps.update(data.get("dependencies", {}))
        all_deps.update(data.get("devDependencies", {}))
        entries: list[VaultEntry] = []
        for dep_name in all_deps:
            dep_lower = dep_name.lower()
            for pattern, (tech, category) in FRAMEWORK_PATTERNS.items():
                if dep_lower == pattern and tech not in seen:
                    seen.add(tech)
                    entries.append(
                        self._framework_entry(
                            technology=tech,
                            category=category,
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
