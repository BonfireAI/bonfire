"""RED tests for bonfire.cli.commands.persona — BON-348 W6.2 (Knight A, CONSERVATIVE lens). Floor: 8 tests per Sage §D6 Row 4. Verbatim v1 port. No innovations."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest  # noqa: TC002
from typer.testing import CliRunner

from bonfire.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

cli_runner = CliRunner()


class TestPersonaList:
    def test_list_shows_passelewe(self) -> None:
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        assert "passelewe" in result.output

    def test_list_shows_minimal(self) -> None:
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        assert "minimal" in result.output

    def test_list_marks_active(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Active persona is visually indicated."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        lines = result.output.splitlines()
        active_lines = [line for line in lines if "passelewe" in line]
        assert len(active_lines) >= 1
        assert any("active" in line.lower() or "▸" in line for line in active_lines)


class TestPersonaSet:
    def test_set_writes_toml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """persona set writes the choice to bonfire.toml."""
        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text("[bonfire]\n")

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0
        assert "minimal" in result.output

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"

    def test_set_creates_toml_if_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persona set creates bonfire.toml if it doesn't exist."""
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        toml_path = tmp_path / "bonfire.toml"
        assert toml_path.exists()
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"

    def test_set_invalid_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """persona set with non-existent persona fails."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["persona", "set", "nonexistent"])
        assert result.exit_code != 0

    def test_set_preserves_existing_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persona set preserves other keys in bonfire.toml."""
        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\nmodel = "claude-opus-4"\npersona = "passelewe"\n')

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"
        assert data["bonfire"]["model"] == "claude-opus-4"

    def test_set_only_replaces_bonfire_section(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persona set must not replace persona keys in other TOML sections."""
        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text(
            '[other]\npersona = "should-not-change"\n\n[bonfire]\npersona = "passelewe"\n'
        )

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"
        assert data["other"]["persona"] == "should-not-change"
