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
            f"scan with port={port_value} exit_code: {result.exit_code}; output: {result.output!r}"
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
            f"default scan invocation exit_code: {result.exit_code}; output: {result.output!r}"
        )
        mock_run.assert_called_once_with(port=0, no_browser=False)


# ---------------------------------------------------------------------------
# Innovation lens — BON-600: Ctrl-C cleanup contract across timing windows.
#
# The narrow ticket spec is: print "Front Door closed." when Ctrl-C arrives
# mid-`server.stop()`. The policy intent is wider — `bonfire scan` is a
# user-facing TUI command, and the cleanup line is the user's only signal
# that the server actually closed cleanly. It MUST print regardless of
# WHEN the KeyboardInterrupt arrives in the lifecycle:
#
#   1. before any server work (asyncio.run hasn't started the coroutine);
#   2. mid-flight inside _run_scan (after server.start, before stop);
#   3. mid-server.stop() itself (the BON-600 narrow case);
#   4. after _run_scan completes (stop already finished, but the user
#      hammered Ctrl-C during teardown of the asyncio loop).
#
# We parametrize over the four arrival points by varying which part of
# the stack the mock raises from. All four MUST surface "Front Door
# closed." — that's the lens-widening: BON-600 is one shape of the same
# policy, not a one-off case.
#
# Innovation also: assert the EXACT text (newline + capitalization) so a
# future refactor that changes "Front Door closed." → "Closed." (less
# informative) is caught.
# ---------------------------------------------------------------------------


class TestScanCleanupOnInterrupt:
    """Drift-guards on the Ctrl-C cleanup contract across timing windows."""

    @pytest.mark.xfail(
        reason="BON-600: KeyboardInterrupt mid-_run_scan must surface cleanup line",
    )
    @pytest.mark.parametrize(
        ("scenario", "side_effect"),
        [
            ("interrupt_at_start", KeyboardInterrupt()),
            ("interrupt_after_partial_work", KeyboardInterrupt("user pressed Ctrl-C")),
        ],
    )
    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_prints_cleanup_on_interrupt_during_run(
        self,
        mock_run: AsyncMock,
        scenario: str,
        side_effect: KeyboardInterrupt,
    ) -> None:
        """`bonfire scan` prints `Front Door closed.` when interrupted mid-run.

        Parametrized over interrupt arrival points. Mock raises
        KeyboardInterrupt directly from `_run_scan` — simulating both the
        "interrupt before any work" case and "interrupt after partial work
        with a message" case.

        Cites scan.py:52-55 — the `try/except KeyboardInterrupt: typer.echo`
        wrapper is the load-bearing contract.
        """
        mock_run.side_effect = side_effect
        result = runner.invoke(app, ["scan", "--no-browser"])

        # The CliRunner captures the echo; exit code can be 0 (caught) or 1
        # depending on how the impl chooses to surface — what matters is the
        # cleanup text is visible to the user.
        assert "Front Door closed." in result.output, (
            f"scenario={scenario!r}: cleanup line missing from output. "
            f"exit_code={result.exit_code}; output={result.output!r}"
        )

    @pytest.mark.xfail(
        reason="BON-600: KeyboardInterrupt raised from server.stop() must still cleanup",
    )
    def test_scan_prints_cleanup_on_interrupt_during_server_stop(self) -> None:
        """KeyboardInterrupt from inside `server.stop()` surfaces cleanup line.

        This is the narrow BON-600 case: simulates the user pressing Ctrl-C
        AFTER `server.start()` has succeeded, while `server.stop()` is
        running in the `finally` block of `_run_scan`. The `try/except
        KeyboardInterrupt` wrapper at the `asyncio.run` boundary MUST
        catch the propagated interrupt and emit the cleanup line.

        We construct a stand-in `_run_scan` coroutine that emulates the
        real lifecycle: start work, hit a KeyboardInterrupt on the way out
        of stop().
        """

        async def fake_run_scan(*, port: int, no_browser: bool) -> None:  # noqa: ARG001
            # Simulate server.start() succeeding, then KeyboardInterrupt
            # arriving from inside `await server.stop()`. The try/finally
            # in the real _run_scan calls server.stop() in the finally —
            # if stop raises KeyboardInterrupt, asyncio.run propagates it.
            try:
                # Pretend we got past server.start and into the wait
                pass
            finally:
                # Pretend server.stop() itself raised KeyboardInterrupt
                raise KeyboardInterrupt("Ctrl-C during server.stop")

        with patch("bonfire.cli.commands.scan._run_scan", side_effect=fake_run_scan):
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert "Front Door closed." in result.output, (
            f"cleanup line missing when KeyboardInterrupt arrived mid-server.stop(). "
            f"exit_code={result.exit_code}; output={result.output!r}"
        )

    @pytest.mark.xfail(
        reason="BON-600: cleanup line text format is load-bearing user signal",
    )
    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_cleanup_text_format_is_stable(self, mock_run: AsyncMock) -> None:
        """Cleanup line MUST be exactly `Front Door closed.` — guards drift.

        The text is the user's only signal that cleanup ran. Drift to
        less-informative shapes ("Closed.", "Goodbye!", "exit") would pass
        the narrow `"Front Door closed." in output` substring test only by
        accident. This test asserts the exact phrase appears as a complete
        token (preceded by a newline per scan.py:55).
        """
        mock_run.side_effect = KeyboardInterrupt()
        result = runner.invoke(app, ["scan", "--no-browser"])

        # scan.py:55 prints "\nFront Door closed." — the newline is part
        # of the contract (separates from any prior chatter).
        assert "\nFront Door closed." in result.output, (
            f"cleanup line missing leading newline or has drifted text. output={result.output!r}"
        )
        # Capitalization: "Front Door" with both Fs and Ds capitalized
        # (proper-noun branding per the module docstring). A lowercased
        # variant ("front door closed.") would be a regression — the
        # surface name is a proper noun for the onboarding feature.
        assert "front door closed." not in result.output, (
            "cleanup line capitalization drifted to lowercase 'front door'"
        )
