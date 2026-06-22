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

import asyncio
import contextlib
import io
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

# RED import — bonfire.cli.app module does not exist yet (cli.py is a single-file stub)
from bonfire.cli.app import app

runner = CliRunner()

# Strip ANSI style codes so substring assertions on Typer/Rich help output
# don't split on style boundaries when CI runners emit colored output.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _extract_option_help(plain_output: str, option: str) -> str:
    """Pull the help-text body for ``option`` out of Typer's Rich panel.

    Returns just the named option's line plus its wrapped continuation lines,
    not the whole options panel. Continuation lines are panel rows that don't
    introduce a new ``--<flag>``; the capture stops at the next option row or
    the panel border.
    """
    collected: list[str] = []
    capturing = False
    for raw in plain_output.splitlines():
        line = raw.strip()
        if not (line.startswith("│") and line.endswith("│")):
            continue
        inner = line[1:-1].strip()
        if not inner:
            continue
        is_new_option = inner.startswith("--")
        if is_new_option:
            if capturing:
                break
            rest = inner[len(option) :]
            if inner.startswith(option) and (not rest or rest[0] in " \t"):
                capturing = True
                collected.append(inner)
        elif capturing:
            collected.append(inner)
    return " ".join(collected)


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
        plain = _ANSI_RE.sub("", result.output)
        assert "--no-browser" in plain
        assert "--port" in plain

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

    @patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock)
    def test_scan_prints_closed_on_keyboard_interrupt(self, mock_run: AsyncMock) -> None:
        """`Front Door closed.` must print when KeyboardInterrupt propagates from _run_scan.

        The scan command's `try/except KeyboardInterrupt` at the asyncio.run
        boundary is the load-bearing surface. Any KeyboardInterrupt that
        propagates out of `_run_scan` — whether raised at the start of the
        flow, mid-flow, or from inside the finally block during
        `server.stop()` — bubbles to the outer catch and the closed-message
        must print.

        This test simulates the propagation by having the mocked `_run_scan`
        raise KeyboardInterrupt directly. A test of the exact mid-stop path
        would require a partially-running async coroutine fixture; the
        asyncio.run boundary catch is sufficient coverage for the
        user-visible contract.
        """
        mock_run.side_effect = KeyboardInterrupt()

        result = runner.invoke(app, ["scan", "--no-browser"])

        assert "Front Door closed." in result.output, (
            f"`Front Door closed.` missing from output when "
            f"KeyboardInterrupt propagates; got output={result.output!r}"
        )


# ---------------------------------------------------------------------------
# --no-browser semantics — clarify headless / agent-driven flow
# ---------------------------------------------------------------------------


class TestScanNoBrowserSemantics:
    """`--no-browser` accurately describes the headless WS-driven flow.

    The flag only suppresses `typer.launch(url)`; the WS server still binds
    and blocks on `await server.client_connected.wait()` until any client
    connects. Operators driving scan via websocat / scripted WS clients need
    the help text and runtime echo to reflect that reality.
    """

    def test_scan_no_browser_help_clarifies_client_semantics(self) -> None:
        """`--no-browser` help text mentions WS-client semantics, not just the browser.

        The marker check runs against the `--no-browser` line specifically — not
        the whole options panel — so the assertion can't be satisfied by marker
        words bleeding in from a sibling option's help.
        """
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        plain = _ANSI_RE.sub("", result.output)
        assert "--no-browser" in plain
        no_browser_help = _extract_option_help(plain, "--no-browser")
        assert no_browser_help, (
            f"could not isolate the --no-browser option's help line in panel; "
            f"got plain output: {plain!r}"
        )
        markers = ("client", "websocket", "ws://", "manual")
        no_browser_help_lower = no_browser_help.lower()
        assert any(m in no_browser_help_lower for m in markers), (
            f"--no-browser help line should mention one of {markers!r} so the "
            f"reader sees the WS server still binds and waits for any client; "
            f"got --no-browser help: {no_browser_help!r}"
        )

    def test_run_scan_no_browser_echoes_client_not_browser(self) -> None:
        """Runtime echo with `no_browser=True` mentions client + ws_url, not browser."""
        with (
            patch("bonfire.cli.commands.scan.FrontDoorServer") as mock_server_cls,
            patch("bonfire.onboard.flow.run_front_door", new_callable=AsyncMock) as mock_flow,
        ):
            mock_server = MagicMock()
            mock_server.start = AsyncMock(return_value=None)
            mock_server.stop = AsyncMock(return_value=None)
            mock_server.url = "http://127.0.0.1:8765"
            mock_server.ws_url = "ws://127.0.0.1:8765/ws"

            client_event = asyncio.Event()
            client_event.set()
            shutdown_event = asyncio.Event()
            shutdown_event.set()
            mock_server.client_connected = client_event
            mock_server.shutdown_event = shutdown_event

            mock_server_cls.return_value = mock_server
            mock_flow.return_value = "/tmp/bonfire.toml"

            from bonfire.cli.commands.scan import _run_scan

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                asyncio.run(_run_scan(port=8765, no_browser=True))
            captured = buf.getvalue()

            assert "Waiting for browser connection" not in captured, (
                f"With --no-browser, the runtime echo should not say "
                f"`Waiting for browser connection...`; got: {captured!r}"
            )
            assert ("client" in captured.lower()) or ("ws://" in captured), (
                f"With --no-browser, the runtime echo should mention `client` "
                f"or include the ws:// URL so headless operators see what to "
                f"connect; got: {captured!r}"
            )

    def test_run_scan_browser_default_echoes_browser_wait(self) -> None:
        """Runtime echo with `no_browser=False` keeps the original browser-wait line.

        Symmetric sibling to ``test_run_scan_no_browser_echoes_client_not_browser``.
        Together they pin the branch: ``no_browser=False`` MUST emit the original
        ``Waiting for browser connection`` line (after ``typer.launch``), and
        ``no_browser=True`` MUST emit the client-wait line instead. Locking both
        sides prevents the headless echo from quietly leaking into the default
        path (or vice versa) on a future refactor.
        """
        with (
            patch("bonfire.cli.commands.scan.FrontDoorServer") as mock_server_cls,
            patch("bonfire.onboard.flow.run_front_door", new_callable=AsyncMock) as mock_flow,
            patch("typer.launch") as mock_launch,
        ):
            mock_server = MagicMock()
            mock_server.start = AsyncMock(return_value=None)
            mock_server.stop = AsyncMock(return_value=None)
            mock_server.url = "http://127.0.0.1:8765"
            mock_server.ws_url = "ws://127.0.0.1:8765/ws"

            client_event = asyncio.Event()
            client_event.set()
            shutdown_event = asyncio.Event()
            shutdown_event.set()
            mock_server.client_connected = client_event
            mock_server.shutdown_event = shutdown_event

            mock_server_cls.return_value = mock_server
            mock_flow.return_value = "/tmp/bonfire.toml"
            mock_launch.return_value = 0

            from bonfire.cli.commands.scan import _run_scan

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                asyncio.run(_run_scan(port=8765, no_browser=False))
            captured = buf.getvalue()

            assert "Waiting for browser connection" in captured, (
                f"With no_browser=False, the runtime echo MUST keep the original "
                f"`Waiting for browser connection...` line (after typer.launch) — "
                f"this PR's no-op claim on the default path depends on it; "
                f"got: {captured!r}"
            )
            mock_launch.assert_called_once_with("http://127.0.0.1:8765")


# ---------------------------------------------------------------------------
# Connect-handshake timeout — regression coverage for the hang-forever bug
# ---------------------------------------------------------------------------


class TestScanConnectTimeout:
    """Bug: _run_scan calls client_connected.wait() with no timeout.

    When the browser tab closes before the WS handshake completes, the CLI
    hangs forever. The hardened _run_scan must call
    server.wait_for_client_connect(timeout=120.0) instead, and handle
    asyncio.TimeoutError with a clear stderr message and a non-zero exit code.
    """

    def test_scan_exits_nonzero_on_connect_timeout(self) -> None:
        """CLI exits non-zero and prints a timeout message when connect times out.

        Patches FrontDoorServer directly so wait_for_client_connect raises
        asyncio.TimeoutError, simulating a browser that never arrives.
        """
        with patch("bonfire.cli.commands.scan.FrontDoorServer") as mock_server_cls:
            mock_server = MagicMock()
            mock_server.start = AsyncMock(return_value=None)
            mock_server.stop = AsyncMock(return_value=None)
            mock_server.url = "http://127.0.0.1:9998"
            mock_server.ws_url = "ws://127.0.0.1:9998/ws"
            mock_server.wait_for_client_connect = AsyncMock(side_effect=TimeoutError())
            mock_server_cls.return_value = mock_server

            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must exit with non-zero code when wait_for_client_connect "
            f"raises asyncio.TimeoutError; got exit_code={result.exit_code}"
        )
        output_lower = result.output.lower()
        # Output must name the timeout context so headless operators know why
        # the command stopped. Either "client connected", "timeout", or "120" is
        # sufficient to satisfy the user-visible contract.
        timeout_mentioned = any(
            marker in output_lower for marker in ("client connected", "timeout", "120", "no client")
        )
        assert timeout_mentioned, (
            f"scan timeout output must mention the timeout context "
            f"(e.g. 'No client connected within 120s' or '--no-browser'); "
            f"got: {result.output!r}"
        )
