"""RED tests — BON-341 W5.2 — `bonfire.knowledge.scanner` (innovative lens).

Sage D8.2 type locks:
- ``FileInfo`` (frozen): ``path, category, content_hash, size_bytes``.
- ``ModuleSignature`` (frozen): ``module_path, source_path, classes, functions, imports, docstring``.
- ``ProjectManifest`` (non-frozen).
- ``ProjectScanner(project_root, *, exclude_patterns=None, max_file_size=1_000_000)``.
- ``DEFAULT_EXCLUDES`` includes ``".bonfire"``.
- ``discover() -> ProjectManifest``.
- ``extract_signatures(manifest) -> list[ModuleSignature]``.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from bonfire.knowledge.scanner import (
    FileInfo,
    ModuleSignature,
    ProjectManifest,
    ProjectScanner,
)


# ---------------------------------------------------------------------------
# Dataclass shape (D8.3)
# ---------------------------------------------------------------------------


class TestFileInfoFrozen:
    def test_file_info_is_frozen(self, tmp_path) -> None:
        info = FileInfo(
            path=tmp_path / "x.py",
            category="python",
            content_hash="abc",
            size_bytes=42,
        )
        with pytest.raises(FrozenInstanceError):
            info.category = "markdown"  # type: ignore[misc]


class TestModuleSignatureFrozen:
    def test_module_signature_is_frozen(self) -> None:
        sig = ModuleSignature(
            module_path="a.b",
            source_path="a/b.py",
            classes=[],
            functions=[],
            imports=[],
            docstring="",
        )
        with pytest.raises(FrozenInstanceError):
            sig.module_path = "other"  # type: ignore[misc]

    def test_module_signature_default_factories(self) -> None:
        sig = ModuleSignature(
            module_path="x",
            source_path="x.py",
            classes=["A"],
            functions=["f"],
            imports=["os"],
            docstring="doc",
        )
        assert sig.classes == ["A"]
        assert sig.functions == ["f"]
        assert sig.imports == ["os"]


class TestProjectManifestDataclass:
    def test_project_manifest_default_factories(self, tmp_path) -> None:
        pm = ProjectManifest(project_root=tmp_path)
        # Default factories
        assert pm.files == []
        assert pm.total_files == 0
        assert pm.total_python_source == 0
        assert pm.total_markdown == 0
        assert pm.total_size_bytes == 0

    # knight-a(innovative): manifest is NOT frozen (mutable per Sage D8.2).
    def test_project_manifest_is_mutable(self, tmp_path) -> None:
        pm = ProjectManifest(project_root=tmp_path)
        pm.total_files = 5  # Sage D8.2: non-frozen.
        assert pm.total_files == 5


# ---------------------------------------------------------------------------
# Discovery (pass 1)
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_project(tmp_path):
    """Project tree with python, test, markdown, config, and noise."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("class A:\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_y(): assert True\n")
    (tmp_path / "README.md").write_text("# Project\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    # Noise
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.pyc").write_bytes(b"\x00")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: master\n")
    return tmp_path


class TestDiscover:
    def test_discover_walks_tree(self, mixed_project) -> None:
        manifest = ProjectScanner(mixed_project).discover()
        paths = {str(f.path) for f in manifest.files}
        assert any("main.py" in p for p in paths)
        assert any("README.md" in p for p in paths)

    def test_discover_classifies_python_as_source_or_test(self, mixed_project) -> None:
        manifest = ProjectScanner(mixed_project).discover()
        categories = {str(f.path): f.category for f in manifest.files}
        # main.py -> python; tests/test_x.py -> test.
        main_cat = next(v for k, v in categories.items() if "main.py" in k)
        test_cat = next(v for k, v in categories.items() if "test_x.py" in k)
        assert main_cat == "python"
        assert test_cat == "test"

    def test_discover_classifies_markdown(self, mixed_project) -> None:
        manifest = ProjectScanner(mixed_project).discover()
        md = [f for f in manifest.files if f.category == "markdown"]
        assert len(md) >= 1

    # knight-a(innovative): classify config files specifically.
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("conf.toml", "config"),
            ("settings.ini", "config"),
            ("data.json", "config"),
            ("pipe.yaml", "config"),
            ("script.sh", "other"),
        ],
    )
    def test_discover_classifies_by_suffix(
        self, tmp_path, name: str, expected: str
    ) -> None:
        (tmp_path / name).write_text("x")
        manifest = ProjectScanner(tmp_path).discover()
        matching = [f for f in manifest.files if f.path.name == name]
        assert len(matching) == 1
        assert matching[0].category == expected

    def test_discover_respects_exclude_patterns(self, mixed_project) -> None:
        """Custom exclude_patterns overrides the default list."""
        scanner = ProjectScanner(mixed_project, exclude_patterns=["src"])
        manifest = scanner.discover()
        paths = {str(f.path) for f in manifest.files}
        assert not any("src/main.py" in p for p in paths)

    def test_discover_excludes_pycache_by_default(self, mixed_project) -> None:
        manifest = ProjectScanner(mixed_project).discover()
        paths = {str(f.path) for f in manifest.files}
        assert not any("__pycache__" in p for p in paths)

    def test_discover_computes_per_file_content_hash(self, mixed_project) -> None:
        manifest = ProjectScanner(mixed_project).discover()
        for f in manifest.files:
            assert f.content_hash, f"{f.path} missing content_hash"

    # knight-a(innovative): manifest counts consistency invariant.
    def test_discover_manifest_counts_match_files(self, mixed_project) -> None:
        manifest = ProjectScanner(mixed_project).discover()
        assert manifest.total_files == len(manifest.files)
        py_count = sum(1 for f in manifest.files if f.category == "python")
        md_count = sum(1 for f in manifest.files if f.category == "markdown")
        assert manifest.total_python_source == py_count
        assert manifest.total_markdown == md_count


# ---------------------------------------------------------------------------
# Signatures (pass 2)
# ---------------------------------------------------------------------------


class TestExtractSignatures:
    def test_extract_signatures_parses_classes_and_functions(self, tmp_path) -> None:
        (tmp_path / "m.py").write_text(
            "class Foo:\n    pass\n\ndef bar(): pass\n\nasync def baz(): pass\n"
        )
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) == 1
        sig = sigs[0]
        assert "Foo" in sig.classes
        assert "bar" in sig.functions
        assert "baz" in sig.functions

    def test_extract_signatures_parses_imports(self, tmp_path) -> None:
        (tmp_path / "m.py").write_text(
            "import os\nimport sys\nfrom pathlib import Path\n\ndef f(): pass\n"
        )
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) >= 1
        sig = sigs[0]
        assert "os" in sig.imports
        assert "sys" in sig.imports
        assert "pathlib" in sig.imports

    def test_extract_signatures_captures_docstring(self, tmp_path) -> None:
        (tmp_path / "m.py").write_text('"""Module docstring here."""\n\ndef f(): pass\n')
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) >= 1
        assert "Module docstring here" in sigs[0].docstring

    # knight-a(innovative): syntax error files do NOT crash; they are skipped.
    def test_extract_signatures_skips_syntax_errors(self, tmp_path) -> None:
        (tmp_path / "good.py").write_text("def f(): pass\n")
        (tmp_path / "bad.py").write_text("def f(:\n")  # broken
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        # good.py parsed; bad.py skipped; no crash.
        source_paths = {s.source_path for s in sigs}
        assert any("good.py" in p for p in source_paths)


# ---------------------------------------------------------------------------
# Constructor defaults
# ---------------------------------------------------------------------------


class TestScannerDefaults:
    def test_default_excludes_contains_dot_bonfire(self) -> None:
        """D3.11: ``.bonfire`` stays in default excludes."""
        assert ".bonfire" in ProjectScanner.DEFAULT_EXCLUDES

    @pytest.mark.parametrize(
        "expected",
        ["__pycache__", ".git", ".venv", ".bonfire"],
    )
    def test_default_excludes_contains_standard_patterns(self, expected: str) -> None:
        """Innovative split: parametrize known exclusions."""
        assert expected in ProjectScanner.DEFAULT_EXCLUDES

    def test_max_file_size_default_is_one_megabyte(self, tmp_path) -> None:
        """Constructor default: max_file_size=1_000_000."""
        import inspect

        sig = inspect.signature(ProjectScanner.__init__)
        assert sig.parameters["max_file_size"].default == 1_000_000

    # knight-a(innovative): large-file exclusion behavior.
    def test_discover_excludes_files_over_max_size(self, tmp_path) -> None:
        big = tmp_path / "huge.py"
        big.write_text("x = 1\n" * 1000)  # big enough
        scanner = ProjectScanner(tmp_path, max_file_size=50)
        manifest = scanner.discover()
        paths = {str(f.path) for f in manifest.files}
        assert not any("huge.py" in p for p in paths)

    def test_empty_directory_produces_empty_manifest(self, tmp_path) -> None:
        manifest = ProjectScanner(tmp_path).discover()
        assert manifest.files == []
        assert manifest.total_files == 0
