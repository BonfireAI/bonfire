"""RED tests — BON-341 W5.2 — `bonfire.scan.tech_scanner.TechScanner`.

Sage D3.4 + D8.2:
- Class rename: ``TechFingerprinter`` -> ``TechScanner`` (ADR-001 line 61).
- File rename: ``fingerprinter.py`` -> ``tech_scanner.py`` (ADR-001 line 45).
- entry_type STAYS ``"tech_fingerprint"`` (Sage D9.8 #9: taxonomy strings unchanged).

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import json

import pytest

from bonfire.scan.tech_scanner import TechScanner


class TestTechScannerClassRename:
    """Sage D3.4: class rename to TechScanner, entry_type stays tech_fingerprint."""

    def test_class_name_is_tech_scanner(self) -> None:
        """The class MUST be named ``TechScanner`` (ADR-001 rename)."""
        assert TechScanner.__name__ == "TechScanner"

    # knight-a(innovative): verify the OLD name is not present in the module.
    def test_tech_fingerprinter_name_not_exported(self) -> None:
        """ADR-001 rename: TechFingerprinter name MUST NOT be exported."""
        import bonfire.scan.tech_scanner as tsmod

        assert not hasattr(tsmod, "TechFingerprinter")


class TestScanEntryType:
    async def test_scan_returns_vault_entries_with_tech_fingerprint_type(self, tmp_path) -> None:
        """entry_type lock: ``tech_fingerprint`` (D9.8 #9 — taxonomy unchanged)."""
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'demo'\n[project.dependencies]\n"
        )
        scanner = TechScanner(tmp_path, project_name="demo")
        entries = await scanner.scan()
        assert entries
        for e in entries:
            assert e.entry_type == "tech_fingerprint"


class TestLanguageDetection:
    async def test_detects_python_from_pyproject_toml(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n[project.dependencies]\n")
        (tmp_path / "a.py").write_text("x = 1\n")
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        techs = {e.metadata["technology"] for e in entries}
        assert "Python" in techs

    async def test_detects_javascript_from_package_json(self, tmp_path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"name": "x", "dependencies": {}}))
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        techs = {e.metadata["technology"] for e in entries}
        assert "JavaScript" in techs

    # knight-a(innovative): parametrize language-manifest coverage.
    @pytest.mark.parametrize(
        "manifest,tech",
        [
            ("pyproject.toml", "Python"),
            ("package.json", "JavaScript"),
            ("Cargo.toml", "Rust"),
            ("go.mod", "Go"),
        ],
    )
    async def test_detects_language_from_manifest(self, tmp_path, manifest: str, tech: str) -> None:
        content = "{}" if manifest == "package.json" else "[project]\nname='x'\n"
        (tmp_path / manifest).write_text(content)
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        techs = {e.metadata["technology"] for e in entries}
        assert tech in techs


class TestFrameworkDetection:
    async def test_extracts_pyproject_deps(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'x'\n[project.dependencies]\ndjango = \">=5.0\"\n"
        )
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        techs = {e.metadata["technology"] for e in entries}
        # Framework detection from pyproject.toml deps.
        assert "Django" in techs or any("django" in t.lower() for t in techs)

    async def test_detects_pytest_in_project_dependencies(self, tmp_path) -> None:
        """pytest declared in [project.dependencies] is detected as test_framework.

        Locks the contract for the simplest PEP 621 form.
        """
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'x'\n[project.dependencies]\npytest = \">=8.0\"\n"
        )
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        pytest_entries = [e for e in entries if e.metadata.get("technology") == "pytest"]
        assert pytest_entries, f"pytest not detected; got {[e.metadata for e in entries]}"
        assert pytest_entries[0].metadata["category"] == "test_framework"

    async def test_detects_pytest_in_subsection_table_optional_dependencies(self, tmp_path) -> None:
        """Form A: [project.optional-dependencies.dev] with bare keys.

        Subsection-style optional-dependencies. The header matches the existing
        regex; bare ``pytest = ">=8.0"`` is captured by the key match.
        """
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'x'\n"
            "[project.optional-dependencies.dev]\n"
            'pytest = ">=8.0"\n'
            'mypy = ">=1.0"\n'
        )
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        pytest_entries = [e for e in entries if e.metadata.get("technology") == "pytest"]
        assert pytest_entries, f"pytest not detected; got {[e.metadata for e in entries]}"
        assert pytest_entries[0].metadata["category"] == "test_framework"

    async def test_detects_pytest_in_optional_dependencies_inline_array(self, tmp_path) -> None:
        """Form B: [project.optional-dependencies] header + inline-array values.

        ``dev = ["pytest>=8.0", "mypy>=1.0"]`` — quoted-string scan picks up
        the package specs.
        """
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'x'\n"
            "[project.optional-dependencies]\n"
            'dev = ["pytest>=8.0", "mypy>=1.0"]\n'
            'test = ["pytest-asyncio"]\n'
        )
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        pytest_entries = [e for e in entries if e.metadata.get("technology") == "pytest"]
        assert pytest_entries, f"pytest not detected; got {[e.metadata for e in entries]}"
        assert pytest_entries[0].metadata["category"] == "test_framework"

    async def test_detects_pytest_in_inline_table_optional_dependencies(self, tmp_path) -> None:
        """Form C: [project] section + inline-table optional-dependencies.

        ``optional-dependencies = {dev = ["pytest>=8.0"]}`` — the inline-table
        form lives under [project] and never produces a section header that
        matches the existing regex. Must still extract pytest.
        """
        (tmp_path / "pyproject.toml").write_text(
            "[project]\n"
            "name = 'x'\n"
            'optional-dependencies = {dev = ["pytest>=8.0", "mypy>=1.0"]}\n'
        )
        scanner = TechScanner(tmp_path, project_name="x")
        entries = await scanner.scan()
        pytest_entries = [e for e in entries if e.metadata.get("technology") == "pytest"]
        assert pytest_entries, f"pytest not detected; got {[e.metadata for e in entries]}"
        assert pytest_entries[0].metadata["category"] == "test_framework"


class TestEdgeCases:
    async def test_empty_project_returns_empty_list(self, tmp_path) -> None:
        """No manifests present -> empty list."""
        scanner = TechScanner(tmp_path, project_name="empty")
        entries = await scanner.scan()
        assert entries == []

    # knight-a(innovative): malformed package.json does not crash.
    async def test_malformed_package_json_does_not_crash(self, tmp_path) -> None:
        (tmp_path / "package.json").write_text("{this-is-not-valid-json")
        scanner = TechScanner(tmp_path, project_name="x")
        # Must NOT raise.
        entries = await scanner.scan()
        assert isinstance(entries, list)
        # JavaScript still detected (from manifest presence).
        techs = {e.metadata["technology"] for e in entries}
        assert "JavaScript" in techs


class TestStoreSemantics:
    # knight-a(innovative): scan_and_store dedups via content_hash.
    async def test_scan_and_store_dedups_on_rescan(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n[project.dependencies]\n")

        stored: list = []
        hashes: set[str] = set()

        class FakeVault:
            async def exists(self, h: str) -> bool:
                return h in hashes

            async def store(self, entry) -> str:
                stored.append(entry)
                hashes.add(entry.content_hash)
                return entry.entry_id

            async def query(self, q: str, *, limit=5, entry_type=None):
                return []

            async def get_by_source(self, p: str):
                return []

        vault = FakeVault()
        scanner = TechScanner(tmp_path, project_name="x")
        first = await scanner.scan_and_store(vault)
        second = await scanner.scan_and_store(vault)
        assert first >= 1
        assert second == 0  # all dedup'd
