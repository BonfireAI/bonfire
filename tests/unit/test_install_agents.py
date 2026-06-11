# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for `bonfire install-agents` / `uninstall-agents` / `list-agents`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bonfire.agent.role_metadata import ALL_PUBLISHABLE_ROLES
from bonfire.cli.app import app
from bonfire.cli.commands.install_agents import _MANIFEST_NAME, _flat_name, _scope_dir

runner = CliRunner()


@pytest.fixture
def user_home(tmp_path: Path):
    """Redirect Path.home() to a temp dir for safe user-scope tests."""
    with patch.object(Path, "home", return_value=tmp_path):
        yield tmp_path


@pytest.fixture
def project_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect Path.cwd() to a temp dir for safe project-scope tests."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path


class TestScopeResolution:
    def test_user_scope_under_home(self, user_home: Path) -> None:
        assert _scope_dir("user") == user_home / ".claude" / "agents" / "bonfire"

    def test_project_scope_under_cwd(self, project_cwd: Path) -> None:
        assert _scope_dir("project") == project_cwd / ".claude" / "agents" / "bonfire"

    def test_unknown_scope_rejected(self, user_home: Path) -> None:
        result = runner.invoke(app, ["install-agents", "--scope", "system"])
        assert result.exit_code != 0


class TestInstallDryRun:
    def test_dry_run_writes_nothing(self, user_home: Path) -> None:
        target = user_home / ".claude" / "agents" / "bonfire"
        assert not target.exists()
        result = runner.invoke(app, ["install-agents", "--dry-run"])
        assert result.exit_code == 0, result.stdout
        assert not target.exists()
        # Output lists every file that WOULD be installed.
        for role in ALL_PUBLISHABLE_ROLES:
            assert f"{_flat_name(role['name'])}.md" in result.stdout


class TestInstall:
    def test_install_writes_seven_files_plus_manifest(self, user_home: Path) -> None:
        result = runner.invoke(app, ["install-agents"])
        assert result.exit_code == 0, result.stdout
        target = user_home / ".claude" / "agents" / "bonfire"
        assert target.is_dir()
        for role in ALL_PUBLISHABLE_ROLES:
            assert (target / f"{_flat_name(role['name'])}.md").exists()
        assert (target / _MANIFEST_NAME).exists()

    def test_install_manifest_contains_versions(self, user_home: Path) -> None:
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        manifest = json.loads((target / _MANIFEST_NAME).read_text(encoding="utf-8"))
        assert "bonfire_ai_version" in manifest
        assert "cadre_contract_version" in manifest
        assert "installed_at" in manifest
        assert len(manifest["files"]) == len(ALL_PUBLISHABLE_ROLES)

    def test_install_is_idempotent(self, user_home: Path) -> None:
        first = runner.invoke(app, ["install-agents"])
        second = runner.invoke(app, ["install-agents"])
        assert first.exit_code == 0
        assert second.exit_code == 0
        # Second run reports all unchanged.
        assert "unchanged" in second.stdout

    def test_install_writes_flat_prefixed_names_for_cadre(self, user_home: Path) -> None:
        """CLI-installed cadre files surface as `bonfire-<role>` subagent types.

        The brand prefix is baked into both the filename AND the `name:`
        frontmatter field so the raw-files surface registers the cadre
        as `bonfire-scout-innovative`, `bonfire-knight`, etc. — flat
        sister to the plugin's `bonfire:<role>` colon-namespaced form.
        """
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        for role_name in ("scout-innovative", "knight", "warrior", "sage", "wizard"):
            path = target / f"bonfire-{role_name}.md"
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert f"name: bonfire-{role_name}\n" in content

    def test_install_does_not_double_prefix_catchall(self, user_home: Path) -> None:
        """The catch-all is `bonfire-powered` — must not become `bonfire-bonfire-powered`."""
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        # Correct filename (single prefix)
        assert (target / "bonfire-powered.md").exists()
        # Incorrect double-prefixed filename
        assert not (target / "bonfire-bonfire-powered.md").exists()
        # `name:` field also single-prefixed
        content = (target / "bonfire-powered.md").read_text(encoding="utf-8")
        assert "name: bonfire-powered\n" in content
        assert "name: bonfire-bonfire-powered\n" not in content

    def test_install_user_does_not_overwrite_modified_without_force(self, user_home: Path) -> None:
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        modified = target / "bonfire-warrior.md"
        modified.write_text("user-customized\n", encoding="utf-8")

        result = runner.invoke(app, ["install-agents"])
        assert result.exit_code == 0
        assert modified.read_text(encoding="utf-8") == "user-customized\n"
        assert "skipped" in result.stdout

    def test_install_force_overwrites_modified(self, user_home: Path) -> None:
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        modified = target / "bonfire-warrior.md"
        modified.write_text("user-customized\n", encoding="utf-8")

        result = runner.invoke(app, ["install-agents", "--force"])
        assert result.exit_code == 0
        assert "user-customized" not in modified.read_text(encoding="utf-8")


class TestUninstall:
    def test_uninstall_removes_only_manifest_files(self, user_home: Path) -> None:
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        # Drop a stranger file in the same directory; uninstall must NOT touch it.
        stranger = target / "user-custom-stranger.md"
        stranger.write_text("kept\n", encoding="utf-8")

        result = runner.invoke(app, ["uninstall-agents"])
        assert result.exit_code == 0, result.stdout
        for role in ALL_PUBLISHABLE_ROLES:
            assert not (target / f"{_flat_name(role['name'])}.md").exists()
        assert not (target / _MANIFEST_NAME).exists()
        # Stranger preserved, directory retained.
        assert stranger.exists()
        assert stranger.read_text(encoding="utf-8") == "kept\n"

    def test_uninstall_dry_run_writes_nothing(self, user_home: Path) -> None:
        runner.invoke(app, ["install-agents"])
        target = user_home / ".claude" / "agents" / "bonfire"
        before = sorted(p.name for p in target.iterdir())

        result = runner.invoke(app, ["uninstall-agents", "--dry-run"])
        assert result.exit_code == 0
        after = sorted(p.name for p in target.iterdir())
        assert before == after

    def test_uninstall_without_manifest_refuses(self, user_home: Path) -> None:
        target = user_home / ".claude" / "agents" / "bonfire"
        target.mkdir(parents=True)
        (target / "rogue.md").write_text("rogue\n", encoding="utf-8")

        result = runner.invoke(app, ["uninstall-agents"])
        assert result.exit_code != 0
        # File preserved on refusal.
        assert (target / "rogue.md").exists()

    def test_uninstall_clean_when_target_absent(self, user_home: Path) -> None:
        result = runner.invoke(app, ["uninstall-agents"])
        assert result.exit_code == 0
        assert "nothing to uninstall" in result.stdout


class TestListAgents:
    def test_list_reports_not_installed_when_absent(self, user_home: Path) -> None:
        result = runner.invoke(app, ["list-agents"])
        assert result.exit_code == 0
        assert "not installed" in result.stdout

    def test_list_reports_manifest_after_install(self, user_home: Path) -> None:
        runner.invoke(app, ["install-agents"])
        result = runner.invoke(app, ["list-agents"])
        assert result.exit_code == 0
        for role in ALL_PUBLISHABLE_ROLES:
            assert f"{_flat_name(role['name'])}.md" in result.stdout
