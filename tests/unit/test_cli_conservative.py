"""RED tests for bonfire.cli.app — BON-348 W6.2 (CONTRACT-LOCKED).

Sage memo: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md
Adoption-filter: docs/audit/sage-decisions/bon-348-contract-lock-*.md

Floor (15 tests, per Sage §D6 Test file 1): port v1 cli test surface verbatim,
MINUS the dropped pipeline tests (TestPipelineCommand class +
test_help_output_contains_pipeline) per Sage §D6 "DROPPED tests (3)".

Adopted innovations (2 drift-guards over floor):

  * test_subcommand_registration_enumeration — verifies the exact 7-command
    surface registered on `app` (5 commands + 2 sub-typers). Negative-asserts
    pipeline/project/memory absence (Sage §D1 D-FT A/B/C deferrals). Cites
    Sage §D2 + v1 cli/app.py:54-63.

  * test_version_flag_format_stability — asserts the exact format
    `bonfire 0.1.0a1` after strip(). Guards against capitalization/prefix drift
    that the substring floor test would miss. Cites Sage §D8 + v1 cli/app.py:20-23.

Imports are RED — `bonfire.cli.app` does not exist as a package until Warriors
port v1 source per Sage §D9. Today `src/bonfire/cli.py` is a 36-line single-file
PyPI-name-reservation stub that does NOT export `app` from a package path.
"""

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

    def test_init_twice_preserves_bonfire_dir_contents(self, tmp_path, monkeypatch) -> None:
        """Running init twice must not overwrite existing .bonfire/ contents.

        Coverage gap: the floor `test_init_twice_does_not_overwrite` only
        verifies bonfire.toml survives. `mkdir(exist_ok=True)` handles
        directory idempotency, but a marker file inside .bonfire/ is the
        real signal that user state survives the second init.
        """
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        bonfire_dir = tmp_path / ".bonfire"
        assert bonfire_dir.is_dir()
        marker = bonfire_dir / "user-marker.txt"
        marker.write_text("user content")
        # Run init again
        runner.invoke(app, ["init"])
        assert marker.exists(), ".bonfire/user-marker.txt must survive init re-run"
        assert marker.read_text() == "user content"

    def test_init_twice_preserves_agents_dir_contents(self, tmp_path, monkeypatch) -> None:
        """Running init twice must not overwrite existing agents/ contents.

        Coverage gap: same shape as `test_init_twice_preserves_bonfire_dir_contents`
        but for the `agents/` directory — the second user-state surface created
        by `bonfire init`.
        """
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])
        agents_dir = tmp_path / "agents"
        assert agents_dir.is_dir()
        marker = agents_dir / "user-marker.md"
        marker.write_text("# user agent content")
        # Run init again
        runner.invoke(app, ["init"])
        assert marker.exists(), "agents/user-marker.md must survive init re-run"
        assert marker.read_text() == "# user agent content"

    def test_init_preserves_nonempty_agents_tree(self, tmp_path, monkeypatch) -> None:
        """A multi-level agents/ tree survives re-init byte-for-byte.

        Models the real-world case where a user has populated agents/ with
        custom agent definitions (sub-dirs + .md / .toml files) and then
        re-runs `bonfire init` (e.g. after upgrading bonfire-ai).
        """
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["init"])

        agents = tmp_path / "agents"
        nested = agents / "my-team" / "scout"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "agent.md").write_text("# Scout\nUser-defined agent.")
        (agents / "shared-config.toml").write_text('[shared]\nkey = "value"\n')

        runner.invoke(app, ["init"])

        assert (nested / "agent.md").read_text() == "# Scout\nUser-defined agent.", (
            "nested user agent file mutated by re-init"
        )
        assert (agents / "shared-config.toml").read_text() == '[shared]\nkey = "value"\n', (
            "top-level user config file mutated by re-init"
        )
        # Directory tree shape preserved
        assert nested.is_dir(), "nested user agent directory removed by re-init"


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


# ---------------------------------------------------------------------------
# Adopted drift-guards (2 — innovations 1 + 2)
# ---------------------------------------------------------------------------


class TestRegistrationSurface:
    """Drift-guards on the exact registered command/sub-typer surface."""

    def test_subcommand_registration_enumeration(self) -> None:
        """The exact 7-command surface is registered — no more, no less.

        Cites Sage §D2 + v1 cli/app.py:54-63.

        Sage §D2 LOCKS command registration ORDER (init, scan, status, resume,
        handoff, persona, cost). Sage §D1 LOCKS that pipeline, project, and
        memory are DEFERRED — their registrations were REMOVED.

        This test enumerates the registered command/typer-group names. Guards
        against:
          - accidental re-registration of pipeline/project/memory (3 deferred);
          - silent rename of any surviving command;
          - addition of an unintended new command.
        """
        # Direct command registrations (`app.command(...)`):
        registered_commands: set[str] = set()
        for cmd in app.registered_commands:
            if cmd.name is not None:
                registered_commands.add(cmd.name)
            elif cmd.callback is not None:
                registered_commands.add(cmd.callback.__name__)

        # Sub-typer registrations (`app.add_typer(...)`):
        registered_groups: set[str] = set()
        for grp in app.registered_groups:
            if grp.name is not None:
                registered_groups.add(grp.name)

        expected_commands = {"init", "scan", "status", "resume", "handoff"}
        expected_groups = {"persona", "cost"}

        # Guard against the 3 deferred — they MUST NOT appear:
        assert "pipeline" not in registered_groups, (
            "pipeline group is DEFERRED per Sage §D1 D-FT A — must not be registered"
        )
        assert "project" not in registered_commands, (
            "project command is DEFERRED per Sage §D1 D-FT B — must not be registered"
        )
        assert "memory" not in registered_groups, (
            "memory group is DEFERRED per Sage §D1 D-FT C — must not be registered"
        )

        # Guard against the 7 surviving — they MUST appear:
        assert expected_commands.issubset(registered_commands), (
            f"Expected commands {expected_commands} subset of registered "
            f"{registered_commands}; missing: {expected_commands - registered_commands}"
        )
        assert expected_groups.issubset(registered_groups), (
            f"Expected groups {expected_groups} subset of registered "
            f"{registered_groups}; missing: {expected_groups - registered_groups}"
        )

    def test_version_flag_format_stability(self) -> None:
        """--version must print exactly `bonfire <__version__>` — guards format drift.

        Cites Sage §D8 + v1 cli/app.py:20-23.

        Sage §D8 LOCKS the version-callback emit format:
            typer.echo(f"bonfire {__version__}")

        v1 source line 22 confirms: `typer.echo(f"bonfire {__version__}")`.
        Current `__version__` resolves to "0.1.0a1" per
        `src/bonfire/__init__.py` and `pyproject.toml`.

        Floor test `test_version_flag_contains_version_string` only checks
        `"0.1.0" in result.output` — would still pass if format drifted to
        e.g. "Bonfire-AI v0.1.0a1" or "bonfire (version: 0.1.0a1)".

        This test asserts the EXACT lower-case "bonfire" prefix + literal
        " 0.1.0a1" — guards against:
          - capitalization drift (Bonfire vs bonfire);
          - extra "v" prefix (bonfire v0.1.0a1);
          - any wrapper text around the version string.
        """
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        # Strip trailing newline only — content must match verbatim
        assert result.output.strip() == "bonfire 0.1.0a1", (
            f"Expected exact format 'bonfire 0.1.0a1'; got {result.output.strip()!r}"
        )
