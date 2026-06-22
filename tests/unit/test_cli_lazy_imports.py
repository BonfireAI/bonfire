"""RED contract for CLI cold-start lazy imports.

Subject: ``bonfire.cli.app`` currently eager-imports every command module
(``cost``, ``handoff``, ``init``, ``persona``, ``resume``, ``scan``,
``status``). The transitive import graph pulls in ``websockets`` (via
``bonfire.onboard.server``), ``bonfire.onboard.server``, and
``bonfire.cost.analyzer`` even on the trivial ``bonfire --version`` path.

This file pins down the contract that:

  * ``import bonfire.cli.app`` and ``bonfire --version`` MUST NOT
    transitively import ``websockets``, ``websockets.asyncio.server``,
    ``bonfire.onboard.server``, or ``bonfire.cost.analyzer``.
  * ``bonfire scan --help`` MAY import ``bonfire.onboard.server`` — that
    command's dep tree is allowed to load on first scan invocation.
  * ``bonfire --help`` still lists every command name so the discovery
    surface is unchanged.

The Warrior will refactor ``app.py`` to lazy-register commands (deferred
imports inside Typer callbacks or factory functions). The PRESENT
behavior is RED on every clean-import assertion.

The clean-import assertions run in a subprocess because pytest's own
import graph already pollutes ``sys.modules`` for the host interpreter.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from typer.testing import CliRunner

# Modules that MUST NOT appear in ``sys.modules`` after importing
# ``bonfire.cli.app`` or running ``bonfire --version``.
_FORBIDDEN_COLD_START_MODULES = (
    "websockets",
    "websockets.asyncio.server",
    "bonfire.onboard.server",
    "bonfire.cost.analyzer",
)

# Commands the ``bonfire --help`` discovery surface MUST still list.
_EXPECTED_COMMAND_NAMES = (
    "init",
    "scan",
    "status",
    "resume",
    "handoff",
    "persona",
    "cost",
)


def _run_subprocess_assert_clean_imports(snippet: str) -> tuple[set[str], str]:
    """Run *snippet* in a fresh Python subprocess; return loaded bonfire modules + stderr.

    The snippet is expected to print a newline-separated list of
    forbidden modules that ARE present in ``sys.modules`` after the
    snippet's import work. An empty stdout means "all forbidden modules
    are absent" (the GREEN state).
    """
    forbidden_csv = ",".join(_FORBIDDEN_COLD_START_MODULES)
    program = (
        "import sys\n"
        f"{snippet}\n"
        f"_forbidden = {forbidden_csv!r}.split(',')\n"
        "_present = [m for m in _forbidden if m in sys.modules]\n"
        "for m in _present:\n"
        "    print(m)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    present = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return present, result.stderr


class TestImportAppIsLazy:
    """Importing ``bonfire.cli.app`` alone must not drag heavyweight deps."""

    @pytest.mark.parametrize("forbidden_module", _FORBIDDEN_COLD_START_MODULES)
    def test_module_import_does_not_load_forbidden_module(self, forbidden_module: str) -> None:
        """``import bonfire.cli.app`` must not transitively load *forbidden_module*."""
        snippet = "import bonfire.cli.app  # noqa: F401"
        present, stderr = _run_subprocess_assert_clean_imports(snippet)

        assert forbidden_module not in present, (
            f"`import bonfire.cli.app` transitively loaded {forbidden_module!r}; "
            f"all forbidden modules present: {sorted(present)!r}; "
            f"stderr={stderr!r}"
        )


class TestVersionFlagIsLazy:
    """``bonfire --version`` must not drag heavyweight deps."""

    @pytest.mark.parametrize("forbidden_module", _FORBIDDEN_COLD_START_MODULES)
    def test_version_flag_does_not_load_forbidden_module(self, forbidden_module: str) -> None:
        """``bonfire --version`` (via CliRunner) must not load *forbidden_module*."""
        snippet = (
            "from typer.testing import CliRunner\n"
            "from bonfire.cli.app import app\n"
            "runner = CliRunner()\n"
            "result = runner.invoke(app, ['--version'])\n"
            "assert result.exit_code == 0, result.output\n"
        )
        present, stderr = _run_subprocess_assert_clean_imports(snippet)

        assert forbidden_module not in present, (
            f"`bonfire --version` transitively loaded {forbidden_module!r}; "
            f"all forbidden modules present: {sorted(present)!r}; "
            f"stderr={stderr!r}"
        )


class TestScanHelpMayLoadOnboardServer:
    """``bonfire scan --help`` is allowed to import the scan command's deps.

    This positive-allowance test exists so a future over-eager
    lazy-registration refactor doesn't regress the scan command itself.
    It's GREEN today (scan imports onboard.server eagerly through the
    module-level ``from bonfire.onboard.server import FrontDoorServer``)
    and must remain GREEN after the lazy-refactor: the scan command,
    when actually invoked, is allowed to load its deps.
    """

    def test_scan_help_allows_bonfire_onboard_server_import(self) -> None:
        """After ``bonfire scan --help``, ``bonfire.onboard.server`` MAY be loaded."""
        snippet = (
            "from typer.testing import CliRunner\n"
            "from bonfire.cli.app import app\n"
            "runner = CliRunner()\n"
            "result = runner.invoke(app, ['scan', '--help'])\n"
            "assert result.exit_code == 0, result.output\n"
            "import sys\n"
            "assert 'bonfire.onboard.server' in sys.modules, "
            "    'scan --help should be allowed to import onboard.server'\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", snippet],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, (
            f"scan --help failed in subprocess; stdout={completed.stdout!r}; "
            f"stderr={completed.stderr!r}"
        )


class TestHelpStillListsAllCommands:
    """``bonfire --help`` discovery surface must include every command name."""

    @pytest.mark.parametrize("command_name", _EXPECTED_COMMAND_NAMES)
    def test_help_lists_command(self, command_name: str) -> None:
        """``bonfire --help`` output must mention *command_name*."""
        from bonfire.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0, result.output
        assert command_name in result.output, (
            f"Command {command_name!r} missing from `bonfire --help` output. "
            f"Output: {result.output!r}"
        )
