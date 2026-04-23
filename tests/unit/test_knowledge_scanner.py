"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.scanner.

Covers ``ProjectScanner``, ``FileInfo``, ``ModuleSignature``,
``ProjectManifest`` per Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from bonfire.knowledge.scanner import (
    FileInfo,
    ModuleSignature,
    ProjectManifest,
    ProjectScanner,
)


class TestDataclassShapes:
    def test_file_info_is_frozen(self):
        params = dataclasses.fields(FileInfo)
        assert {f.name for f in params} >= {
            "path",
            "category",
            "content_hash",
            "size_bytes",
        }
        fi = FileInfo(
            path=Path("a.py"),
            category="python",
            content_hash="x" * 64,
            size_bytes=1,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            fi.category = "test"  # type: ignore[misc]

    def test_module_signature_is_frozen(self):
        sig = ModuleSignature(
            module_path="pkg.mod",
            source_path="pkg/mod.py",
            classes=[],
            functions=[],
            imports=[],
            docstring="",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            sig.docstring = "changed"  # type: ignore[misc]

    def test_project_manifest_default_factories(self, tmp_path: Path):
        manifest = ProjectManifest(project_root=tmp_path, files=[])
        assert manifest.total_files == 0
        assert manifest.total_python_source == 0
        assert manifest.total_markdown == 0
        assert manifest.total_size_bytes == 0


class TestDiscover:
    def test_discover_walks_tree(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "README.md").write_text("# hi\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        paths = {f.path.name for f in manifest.files}
        assert "a.py" in paths
        assert "README.md" in paths

    def test_discover_classifies_python_as_source_or_test(self, tmp_path: Path):
        (tmp_path / "lib.py").write_text("x = 1\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_lib.py").write_text("x = 1\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        categories = {f.path.name: f.category for f in manifest.files}
        assert categories.get("lib.py") == "python"
        assert categories.get("test_lib.py") == "test"

    def test_discover_classifies_markdown(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text("# hi\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        md = next(f for f in manifest.files if f.path.name == "doc.md")
        assert md.category == "markdown"

    def test_discover_respects_exclude_patterns(self, tmp_path: Path):
        keep = tmp_path / "keep.py"
        keep.write_text("x = 1\n")
        excluded = tmp_path / "skip_me"
        excluded.mkdir()
        (excluded / "inside.py").write_text("x = 1\n")
        scanner = ProjectScanner(tmp_path, exclude_patterns=["skip_me"])
        manifest = scanner.discover()
        names = {f.path.name for f in manifest.files}
        assert "keep.py" in names
        assert "inside.py" not in names

    def test_discover_excludes_pycache_by_default(self, tmp_path: Path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "junk.pyc").write_text("binary")
        (tmp_path / "keep.py").write_text("x = 1\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        names = {f.path.name for f in manifest.files}
        assert "junk.pyc" not in names
        assert "keep.py" in names

    def test_discover_computes_per_file_content_hash(self, tmp_path: Path):
        p = tmp_path / "file.py"
        p.write_text("x = 1\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        fi = next(f for f in manifest.files if f.path.name == "file.py")
        assert len(fi.content_hash) == 64


class TestExtractSignatures:
    def test_extract_signatures_parses_classes_and_functions(self, tmp_path: Path):
        (tmp_path / "m.py").write_text(
            "class Foo:\n    pass\n\n\ndef bar():\n    return 1\n"
        )
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) == 1
        assert "Foo" in sigs[0].classes
        assert "bar" in sigs[0].functions

    def test_extract_signatures_parses_imports(self, tmp_path: Path):
        (tmp_path / "m.py").write_text("import os\nfrom pathlib import Path\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) == 1
        imports = sigs[0].imports
        assert any("os" in i for i in imports)
        assert any("pathlib" in i for i in imports)

    def test_extract_signatures_captures_docstring(self, tmp_path: Path):
        (tmp_path / "m.py").write_text('"""Module docstring."""\nx = 1\n')
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) == 1
        assert "Module docstring." in sigs[0].docstring


class TestDefaults:
    def test_default_excludes_contains_dot_bonfire(self):
        assert ".bonfire" in ProjectScanner.DEFAULT_EXCLUDES

    def test_max_file_size_default_is_one_megabyte(self, tmp_path: Path):
        scanner = ProjectScanner(tmp_path)
        assert scanner.max_file_size == 1_000_000
