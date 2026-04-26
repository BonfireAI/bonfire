"""RED tests for bonfire.cli.app — BON-348 W6.2 (Knight A, CONSERVATIVE lens). Floor: 15 tests per Sage §D6 Row 1. Verbatim v1 port. No innovations."""

from __future__ import annotations

import typer
from typer.testing import CliRunner

# RED import — cli/app.py does not exist yet (cli.py is a single-file stub)
from bonfire.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# app.py contract
# ---------------------------------------------------------------------------


class TestAppEntry:
    """Verify the Typer app object and top-level options."""

    def test_app_is_typer_instance(self) -> None:
        """app must be a typer.Typer instance."""
        assert isinstance(app, typer.Typer)

    def test_version_flag_exits_zero(self) -> None:
        """--version must exit with code 0."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0

    def test_version_flag_contains_version_string(self) -> None:
        """--version output must contain the package version."""
        result = runner.invoke(app, ["--version"])
        assert "0.1.0" in result.output

    def test_help_flag_exits_zero(self) -> None:
        """--help must exit with code 0."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_output_contains_init(self) -> None:
        """--help must list the init command."""
        result = runner.invoke(app, ["--help"])
        assert "init" in result.output


# ---------------------------------------------------------------------------
# init command contract
# ---------------------------------------------------------------------------


class TestInitCommand:
    """Verify init scaffolding behavior."""

    def test_init_command_registered(self) -> None:
        """init must be a registered command on the app."""
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0

    def test_init_creates_bonfire_toml(self, tmp_path, monkeypatch) -> None:
        """init must create bonfire.toml in the working directory."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / "bonfire.toml").exists()

    def test_init_creates_bonfire_directory(self, tmp_path, monkeypatch) -> None:
        """init must create .bonfire/ directory."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / ".bonfire").is_dir()

    def test_init_creates_agents_directory(self, tmp_path, monkeypatch) -> None:
        """init must create agents/ directory."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / "agents").is_dir()

    def test_bonfire_toml_contains_bonfire_section(self, tmp_path, monkeypatch) -> None:
        """bonfire.toml must contain a [bonfire] section."""
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        content = (tmp_path / "bonfire.toml").read_text()
        assert "[bonfire]" in content

    def test_init_twice_does_not_overwrite(self, tmp_path, monkeypatch) -> None:
        """Running init twice must not overwrite existing bonfire.toml."""
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        # Write a marker into the file
        toml_path = tmp_path / "bonfire.toml"
        original_content = toml_path.read_text()
        toml_path.write_text(original_content + "\n# user-marker\n")
        # Run init again
        runner.invoke(app, ["init"])
        assert "# user-marker" in toml_path.read_text()


# ---------------------------------------------------------------------------
# status command contract
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Verify status command registration and baseline behavior."""

    def test_status_command_registered(self) -> None:
        """status must be a registered command on the app."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_status_exits_zero_with_no_sessions(self, tmp_path, monkeypatch) -> None:
        """status must exit 0 even when no sessions exist."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# resume command contract
# ---------------------------------------------------------------------------


class TestResumeCommand:
    """Verify resume command registration."""

    def test_resume_command_registered(self) -> None:
        """resume must be a registered command on the app."""
        result = runner.invoke(app, ["resume", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# handoff command contract
# ---------------------------------------------------------------------------


class TestHandoffCommand:
    """Verify handoff command registration."""

    def test_handoff_command_registered(self) -> None:
        """handoff must be a registered command on the app."""
        result = runner.invoke(app, ["handoff", "--help"])
        assert result.exit_code == 0
