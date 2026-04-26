"""RED tests for bonfire.cli.commands.scan — BON-348 W6.2 (Knight A, CONSERVATIVE lens). Floor: 4 tests per Sage §D6 Row 5. Verbatim v1 port. No innovations."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

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
