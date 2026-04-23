"""BON-341 RED — Knight B (conservative) — bonfire.scan.tech_scanner.

Covers ``TechScanner`` (renamed from ``TechFingerprinter`` per ADR-001)
per Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D3.4, §D8.3.
"""

from __future__ import annotations

from pathlib import Path

from bonfire.scan.tech_scanner import TechScanner


class TestTechScanner:
    def test_class_name_is_tech_scanner(self):
        # Rename assertion per ADR-001 (D3.4).
        assert TechScanner.__name__ == "TechScanner"

    def test_scan_returns_vault_entries_with_tech_fingerprint_type(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.0.1"\n'
        )
        scanner = TechScanner(tmp_path)
        entries = scanner.scan()
        assert len(entries) >= 1
        # entry_type string is UNCHANGED per Sage D8.2 + D9.8 red line #9.
        assert all(e.entry_type == "tech_fingerprint" for e in entries)

    def test_detects_python_from_pyproject_toml(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.0.1"\n'
        )
        scanner = TechScanner(tmp_path)
        entries = scanner.scan()
        joined = " ".join(e.content.lower() for e in entries) + " ".join(
            " ".join(e.tags).lower() for e in entries
        )
        assert "python" in joined

    def test_detects_javascript_from_package_json(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "x", "version": "0.0.1"}\n')
        scanner = TechScanner(tmp_path)
        entries = scanner.scan()
        joined = " ".join(e.content.lower() for e in entries) + " ".join(
            " ".join(e.tags).lower() for e in entries
        )
        assert "javascript" in joined or "node" in joined or "npm" in joined

    def test_extracts_pyproject_deps(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "x"\n'
            'version = "0.0.1"\n'
            'dependencies = ["pydantic>=2.0", "click>=8.0"]\n'
        )
        scanner = TechScanner(tmp_path)
        entries = scanner.scan()
        joined = " ".join(e.content.lower() for e in entries)
        assert "pydantic" in joined or "click" in joined

    def test_empty_project_returns_empty_list(self, tmp_path: Path):
        scanner = TechScanner(tmp_path)
        entries = scanner.scan()
        assert entries == []
