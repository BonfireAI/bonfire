"""RED tests for bonfire.cli.commands.scan — BON-348 W6.2 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md

Floor (4 tests, per Sage §D6 Test file 5): port v1 cli test surface verbatim.
All 4 tests patch `bonfire.cli.commands.scan._run_scan` with `AsyncMock` —
they never start a real WebSocket server (Sage §D6 Test file 5 footnote).

Innovations (2 tests, INNOVATIVE lens additions over Sage floor):

  * `test_scan_passes_port_option_parametrized` — parametrize over multiple
    port values (0, 1, 8080, 65535) verifying CLI option threading is exact
    for each. Floor only tests port=9999. Guards against a future Typer
    upgrade that mishandles edge cases (port=0 is "random", port=1 is
    privileged-low, port=65535 is max-uint16). Cites Sage §D8 + v1
    cli/commands/scan.py:47-55 (`scan` Typer command signature).

  * `test_scan_default_invocation_passes_default_kwargs` — verbatim assert
    of the AsyncMock call args for `bonfire scan` with NO options:
    `mock_run.assert_called_once_with(port=0, no_browser=False)`. Floor
    test `test_scan_starts_server` only checks `assert_called_once()` (call
    count), not call args. Guards against a future refactor that flips
    `no_browser` default to True (which would break the "open browser by
    default" UX contract). Cites Sage §D8 + v1 cli/commands/scan.py:48-51
    (default values: `port=0`, `no_browser=False`).

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
# Innovations (Knight B INNOVATIVE lens — 2 drift-guards over Sage floor)
# ---------------------------------------------------------------------------


class TestInnovativeDriftGuards:
    """Drift-guards added by Knight B (innovative lens) over Sage §D6 floor."""

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
        This parametrized variant verifies the full edge range:
          - port=0 (random allocation per v1 line 48 default);
          - port=1 (privileged port — kernel may reject; CLI still threads);
          - port=8080 (dev convention);
          - port=65535 (max uint16 — last valid port).

        Guards against:
          - integer overflow in option parsing (Typer should accept up to
            int32, but a future limit could cap at 32767);
          - port=0 being filtered out by an over-eager validator (would
            break "random port" semantics);
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

        v1 source lines 48-51 confirm `port=0` and `no_browser=False`.

        Floor test `test_scan_starts_server` only asserts
        `mock_run.assert_called_once()` — passes even if the defaults flip
        (e.g. someone changes `no_browser` default to True, which would
        silently break the "open browser by default" UX promise).

        This guard asserts the EXACT default kwargs are threaded into
        `_run_scan`. Critical because:
          - `no_browser=False` is the load-bearing UX contract — `bonfire
            scan` with no flags MUST attempt to launch the browser per
            v1 cli/commands/scan.py:28-29 (`if not no_browser: typer.launch(url)`);
          - `port=0` is the "let the OS pick" semantics — flipping to a
            fixed default like 8080 would conflict with running services.
        """
        mock_run.return_value = None
        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0, (
            f"default scan invocation exit_code: {result.exit_code}; "
            f"output: {result.output!r}"
        )
        mock_run.assert_called_once_with(port=0, no_browser=False)
