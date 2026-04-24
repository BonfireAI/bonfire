"""Two-pass project scanner for vault ingestion.

Pass 1: discover() — walk file tree, classify files, compute content hashes.
Pass 2: extract_signatures() — AST-parse Python files for module signatures.
"""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bonfire.knowledge.hasher import content_hash

if TYPE_CHECKING:
    import pathlib


@dataclass(frozen=True)
class FileInfo:
    """Immutable record of a discovered file."""

    path: pathlib.Path
    category: str
    content_hash: str
    size_bytes: int


@dataclass(frozen=True)
class ModuleSignature:
    """Extracted signature from a Python module via AST parsing."""

    module_path: str
    source_path: str
    classes: list[str]
    functions: list[str]
    imports: list[str]
    docstring: str


@dataclass
class ProjectManifest:
    """Result of the discovery pass."""

    project_root: pathlib.Path
    files: list[FileInfo] = field(default_factory=list)
    total_files: int = 0
    total_python_source: int = 0
    total_markdown: int = 0
    total_size_bytes: int = 0


def _classify_file(path: pathlib.Path, root: pathlib.Path) -> str:
    """Classify a file into a category based on extension and location."""
    suffix = path.suffix.lower()
    rel = path.relative_to(root)
    rel_parts = rel.parts

    if suffix == ".py":
        # Check if it's a test file
        if path.name.startswith("test_") or any(p == "tests" for p in rel_parts):
            return "test"
        return "python"

    if suffix == ".md":
        return "markdown"

    if suffix in {".toml", ".cfg", ".ini", ".json", ".yaml", ".yml"}:
        return "config"

    return "other"


def _should_exclude(path: pathlib.Path, root: pathlib.Path, exclude_patterns: list[str]) -> bool:
    """Check if a path should be excluded based on patterns."""
    rel = path.relative_to(root)
    rel_str = str(rel)
    for pattern in exclude_patterns:
        # Check each part of the path against the pattern
        for part in rel.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
        # Also check the full relative path
        if fnmatch.fnmatch(rel_str, pattern):
            return True
    return False


class ProjectScanner:
    """Two-pass project scanner.

    Pass 1: discover() — walk tree, classify files, compute hashes.
    Pass 2: extract_signatures() — AST-parse Python files.
    """

    DEFAULT_EXCLUDES = [
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".bonfire",
    ]

    def __init__(
        self,
        project_root: pathlib.Path,
        *,
        exclude_patterns: list[str] | None = None,
        max_file_size: int = 1_000_000,
    ) -> None:
        self._project_root = project_root
        self._exclude_patterns = exclude_patterns or list(self.DEFAULT_EXCLUDES)
        self._max_file_size = max_file_size

    def discover(self) -> ProjectManifest:
        """Walk file tree, classify files, compute content hashes."""
        files: list[FileInfo] = []
        total_size = 0

        for path in sorted(self._project_root.rglob("*")):
            if path.is_symlink():
                continue

            if not path.is_file():
                continue

            if _should_exclude(path, self._project_root, self._exclude_patterns):
                continue

            size = path.stat().st_size
            if size > self._max_file_size:
                continue

            rel_path = path.relative_to(self._project_root)
            category = _classify_file(path, self._project_root)

            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            file_hash = content_hash(text)

            files.append(
                FileInfo(
                    path=rel_path,
                    category=category,
                    content_hash=file_hash,
                    size_bytes=size,
                )
            )
            total_size += size

        python_count = sum(1 for f in files if f.category == "python")
        md_count = sum(1 for f in files if f.category == "markdown")

        return ProjectManifest(
            project_root=self._project_root,
            files=files,
            total_files=len(files),
            total_python_source=python_count,
            total_markdown=md_count,
            total_size_bytes=total_size,
        )

    def extract_signatures(self, manifest: ProjectManifest) -> list[ModuleSignature]:
        """Parse Python files via stdlib ast. Skip non-Python. Handle syntax errors gracefully."""
        signatures: list[ModuleSignature] = []

        for file_info in manifest.files:
            if file_info.category not in ("python", "test"):
                continue

            source_path = str(file_info.path)
            if not source_path.endswith(".py"):
                continue

            full_path = self._project_root / file_info.path

            try:
                source = full_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            try:
                tree = ast.parse(source, filename=source_path)
            except SyntaxError:
                continue

            classes: list[str] = []
            functions: list[str] = []
            imports: list[str] = []
            docstring = ""

            # Extract module docstring
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                docstring = tree.body[0].value.value[:500]

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)

            # Build dotted module path from file path
            module_path = source_path.replace("/", ".").replace("\\", ".")
            if module_path.endswith(".py"):
                module_path = module_path[:-3]
            if module_path.endswith(".__init__"):
                module_path = module_path[: -len(".__init__")]

            signatures.append(
                ModuleSignature(
                    module_path=module_path,
                    source_path=source_path,
                    classes=classes,
                    functions=functions,
                    imports=imports,
                    docstring=docstring,
                )
            )

        return signatures
