# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for `bonfire build-agents` — the generator that emits CC-shaped agent files."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bonfire.agent.role_metadata import ALL_PUBLISHABLE_ROLES, CADRE_ROLES, CATCHALL_ROLE
from bonfire.cadre import CADRE_CONTRACT_VERSION
from bonfire.cli.app import app

runner = CliRunner()


class TestMetadataShape:
    def test_cadre_has_six_roles(self) -> None:
        """v1 ships exactly six cadre roles (not counting the catch-all)."""
        assert len(CADRE_ROLES) == 6

    def test_catchall_is_separate(self) -> None:
        """The catch-all is NOT inside the plugin's CADRE_ROLES set."""
        catchall_names = [role["name"] for role in CADRE_ROLES]
        assert "bonfire-powered" not in catchall_names
        assert CATCHALL_ROLE["name"] == "bonfire-powered"

    def test_all_publishable_includes_catchall(self) -> None:
        """ALL_PUBLISHABLE_ROLES = CADRE_ROLES + CATCHALL_ROLE; install_agents ships all seven."""
        assert len(ALL_PUBLISHABLE_ROLES) == 7
        assert ALL_PUBLISHABLE_ROLES[-1] == CATCHALL_ROLE

    @pytest.mark.parametrize("role", ALL_PUBLISHABLE_ROLES)
    def test_each_role_has_required_fields(self, role: dict) -> None:
        for field in ("name", "description", "tools", "model"):
            assert field in role
            assert role[field], f"role {role.get('name')} missing {field}"

    def test_namespace_safe_names(self) -> None:
        """Plugin namespace requires lowercase letters and hyphens only."""
        import re

        pattern = re.compile(r"^[a-z][a-z0-9-]*$")
        for role in ALL_PUBLISHABLE_ROLES:
            assert pattern.match(role["name"]), f"bad name: {role['name']!r}"

    def test_knight_has_no_bash(self) -> None:
        """Knight ships without Bash: writes RED tests, Warrior runs the cycle."""
        knight = next(r for r in CADRE_ROLES if r["name"] == "knight")
        assert "Bash" not in knight["tools"]

    def test_warrior_has_bash(self) -> None:
        """Warrior drives the RED→GREEN cycle and needs Bash."""
        warrior = next(r for r in CADRE_ROLES if r["name"] == "warrior")
        assert "Bash" in warrior["tools"]

    def test_scout_innovative_is_read_only(self) -> None:
        scout = next(r for r in CADRE_ROLES if r["name"] == "scout-innovative")
        assert "Write" not in scout["tools"]
        assert "Edit" not in scout["tools"]
        assert "Bash" not in scout["tools"]


class TestBuildAgentsGenerator:
    def _write_canonical(self, tmp_path: Path) -> Path:
        """Write all generated files to a fresh dir using the CLI."""
        target = tmp_path / "agents"
        result = runner.invoke(app, ["build-agents", "--output-dir", str(target)])
        assert result.exit_code == 0, result.stdout
        return target

    def test_emits_one_file_per_publishable_role(self, tmp_path: Path) -> None:
        target = self._write_canonical(tmp_path)
        for role in ALL_PUBLISHABLE_ROLES:
            assert (target / f"{role['name']}.md").exists()

    def test_emitted_files_have_frontmatter_block(self, tmp_path: Path) -> None:
        target = self._write_canonical(tmp_path)
        content = (target / "scout-innovative.md").read_text(encoding="utf-8")
        assert content.startswith("---\n")
        # Frontmatter closes with the second `---` line.
        assert "\n---\n" in content

    def test_emitted_files_carry_cadre_contract_stamp(self, tmp_path: Path) -> None:
        target = self._write_canonical(tmp_path)
        for role in ALL_PUBLISHABLE_ROLES:
            content = (target / f"{role['name']}.md").read_text(encoding="utf-8")
            assert f'cadre_contract: "{CADRE_CONTRACT_VERSION}"' in content

    def test_emitted_files_contain_role_body(self, tmp_path: Path) -> None:
        target = self._write_canonical(tmp_path)
        content = (target / "warrior.md").read_text(encoding="utf-8")
        # Body identity: a recognizable line from prompts/warrior.md
        assert "Iron Discipline" in content


class TestBuildAgentsCheck:
    def test_check_passes_against_committed_agents_dir(self) -> None:
        """The committed `agents/` directory matches the canonical sources."""
        result = runner.invoke(app, ["build-agents", "--check"])
        assert result.exit_code == 0, result.stdout
        assert "OK" in result.stdout

    def test_check_fails_when_drift(self, tmp_path: Path) -> None:
        """If a generated file drifts, --check exits non-zero."""
        target = tmp_path / "agents"
        # Seed with one valid file …
        runner.invoke(app, ["build-agents", "--output-dir", str(target)])
        # … then corrupt one.
        (target / "warrior.md").write_text("---\ndrifted\n---\n", encoding="utf-8")
        result = runner.invoke(app, ["build-agents", "--output-dir", str(target), "--check"])
        assert result.exit_code == 1
        assert "FAILED" in result.stdout or "FAILED" in result.stderr

    def test_check_fails_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "agents-empty"
        target.mkdir()
        result = runner.invoke(app, ["build-agents", "--output-dir", str(target), "--check"])
        assert result.exit_code == 1
