"""RED tests for bonfire.cli.commands.scan — BON-348 W6.2 (CONTRACT-LOCKED).

Sage memo: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md
Adoption-filter: docs/audit/sage-decisions/bon-348-contract-lock-*.md

Floor (4 tests, per Sage §D6 Test file 5): port v1 cli test surface verbatim.
All 4 tests patch `bonfire.cli.commands.scan._run_scan` with `AsyncMock` —
they never start a real WebSocket server.

Adopted innovations (2 drift-guards over floor):

  * test_scan_passes_port_option_parametrized — parametrize over 0/1/8080/65535.
    Floor only tests port=9999. Mocks `_run_scan` with AsyncMock so privileged
    ports (1) and random (0) never bind. Cites Sage §D8 + v1 scan.py:47-55.

  * test_scan_default_invocation_passes_default_kwargs — verbatim assert of
    `_run_scan` call args for `bonfire scan` with no options:
    `port=0, no_browser=False`. Floor's `test_scan_starts_server` only checks
    `assert_called_once()`. Cites Sage §D8 + v1 scan.py:48-51.

Imports are RED — `bonfire.cli.app` does not exist as a package until Warriors
port v1 source per Sage §D9.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

# RED import — bonfire.cli.app module does not exist yet (cli.py is a single-file stub)
from bonfire.cli.app import app

runner = CliRunner()


class TestScanCommand:
    """bonfire scan CLI command."""

    def test_scan_command_exists(self) -> None:
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "scan" in result.output.lower()

    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_starts_server(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = None
        result = runner.invoke(app, ["scan", "--no-browser"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_scan_help_shows_options(self) -> None:
        result = runner.invoke(app, ["scan", "--help"])
        assert "--no-browser" in result.output
        assert "--port" in result.output

    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_passes_port_option(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = None
        result = runner.invoke(app, ["scan", "--port", "9999", "--no-browser"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(port=9999, no_browser=True)


# ---------------------------------------------------------------------------
# Adopted drift-guards (2 — innovations 9 + 10)
# ---------------------------------------------------------------------------


class TestScanCliThreading:
    """Drift-guards on Typer option threading + locked defaults."""

    @pytest.mark.parametrize(
        "port_value",
        [
            0,  # "random" — the v1 default per scan.py:48
            1,  # privileged-low edge
            8080,  # common dev port
            65535,  # max uint16 — upper edge of valid range
        ],
    )
    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_passes_port_option_parametrized(
        self, mock_run: AsyncMock, port_value: int
    ) -> None:
        """`bonfire scan --port N --no-browser` threads N verbatim into _run_scan.

        Cites Sage §D8 + v1 cli/commands/scan.py:47-55.

        Sage §D8 LOCKS the scan signature:
            port: int = typer.Option(0, "--port", "-p", help="Port to bind (0 = random).")
            no_browser: bool = typer.Option(False, "--no-browser", ...)

        AND the body:
            asyncio.run(_run_scan(port=port, no_browser=no_browser))

        Floor test `test_scan_passes_port_option` only verifies port=9999.
        This parametrized variant verifies the full edge range. Privileged
        port=1 and random port=0 never bind because `_run_scan` is mocked.

        Guards against:
          - integer overflow in option parsing;
          - port=0 being filtered out by an over-eager validator;
          - implicit string coercion (Typer should convert "8080" to int).
        """
        mock_run.return_value = None
        result = runner.invoke(app, ["scan", "--port", str(port_value), "--no-browser"])
        assert result.exit_code == 0, (
            f"scan with port={port_value} exit_code: {result.exit_code}; "
            f"output: {result.output!r}"
        )
        mock_run.assert_called_once_with(port=port_value, no_browser=True)

    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_default_invocation_passes_default_kwargs(self, mock_run: AsyncMock) -> None:
        """`bonfire scan` with no options threads the locked Typer defaults.

        Cites Sage §D8 + v1 cli/commands/scan.py:48-51.

        Sage §D8 LOCKS Typer defaults for scan:
            port: int = typer.Option(0, "--port", "-p", ...)
            no_browser: bool = typer.Option(False, "--no-browser", ...)

        Floor test `test_scan_starts_server` only asserts
        `mock_run.assert_called_once()` — passes even if defaults flip.
        This guard asserts EXACT default kwargs are threaded into `_run_scan`.

        Critical because:
          - `no_browser=False` is the load-bearing UX contract — `bonfire scan`
            with no flags MUST attempt to launch the browser per
            v1 cli/commands/scan.py:28-29 (`if not no_browser: typer.launch(url)`);
          - `port=0` is the "let the OS pick" semantics — flipping to a fixed
            default like 8080 would conflict with running services.
        """
        mock_run.return_value = None
        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0, (
            f"default scan invocation exit_code: {result.exit_code}; "
            f"output: {result.output!r}"
        )
        mock_run.assert_called_once_with(port=0, no_browser=False)
