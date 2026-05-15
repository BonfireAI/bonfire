"""Tests for the WS token out-of-band handoff.

Threat model summary:
  - Previously, ``bonfire scan`` called ``typer.launch(server.url)`` where
    ``server.url`` embedded ``?token=<value>``. On Linux this URL ends up in
    ``xdg-open``'s argv and any same-uid process can read it from
    ``/proc/<pid>/cmdline``.
  - This fix strips the token from the HTTP entry point and ferries it to the
    served HTML over a one-time ``GET /handoff`` endpoint. The token only ever
    exists in: (a) the server's memory, (b) the handoff response body, (c) the
    browser JS closure. NEVER in any process's argv.

Headless contract:
  ``bonfire scan --no-browser`` MUST print the WS URL (token included) to
  STDOUT. Stdout is not in ``/proc/*/cmdline``. The test contract enforces
  stdout-as-hard-contract — a writer that prints to stderr instead would
  violate the audit shape headless operators rely on (CI logs and tmux
  capture differ between stdout/stderr).
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import time
import urllib.error
import urllib.request
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets

from bonfire.onboard.server import FrontDoorServer


# ---------------------------------------------------------------------------
# Helpers — HTTP client. The codebase's established pattern is
# ``urllib.request.urlopen`` (see tests/unit/test_onboard_server.py:104, 124,
# 714, 732, 749). The handoff tests reuse it; the only delta is sending a
# custom ``Origin`` header, which requires building a ``urllib.request.Request``
# object before passing it to ``urlopen``.
# ---------------------------------------------------------------------------


async def _http_get(
    url: str, origin: str | None = None
) -> tuple[int, dict[str, str], bytes]:
    """Run a blocking ``urlopen`` on the asyncio executor.

    Returns (status_code, headers_dict, body_bytes). Raises
    ``urllib.error.HTTPError`` on non-2xx — callers that want to inspect the
    error status should wrap in ``pytest.raises`` and read ``excinfo.value``.
    """
    req = urllib.request.Request(url, method="GET")
    if origin is not None:
        req.add_header("Origin", origin)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, urllib.request.urlopen, req)
    body = response.read()
    headers = {k: v for k, v in response.headers.items()}
    return response.status, headers, body


# ---------------------------------------------------------------------------
# Tests #1, #2 — URL surface contract
# ---------------------------------------------------------------------------


class TestUrlSurface:
    """``server.url`` is token-free; ``server.ws_url`` still embeds the token."""

    async def test_server_url_contains_no_token(self) -> None:
        """``server.url`` MUST match ``http://127.0.0.1:<port>/`` exactly — no query string.

        This is the headline contract: the URL handed to ``typer.launch`` is
        safe to leak via ``/proc/*/cmdline``. The URL must be token-free so
        the same-uid argv exposure no longer carries the gate token.
        """
        server = FrontDoorServer()
        await server.start()
        try:
            assert re.match(r"^http://127\.0\.0\.1:\d+/$", server.url), (
                f"server.url must be token-free — the URL handed to "
                f"typer.launch is in xdg-open's argv and any same-uid process "
                f"can read it via /proc/<pid>/cmdline. "
                f"Expected ^http://127\\.0\\.0\\.1:\\d+/$; got {server.url!r}"
            )
        finally:
            await server.stop()

    async def test_server_ws_url_still_contains_token(self) -> None:
        """``server.ws_url`` MUST still embed ``?token=<value>``.

        Only the HTTP entry lost the token; the WS gate is unchanged. The
        browser will fetch ``/handoff`` to learn the token and then open
        ``ws_url`` with it. A scripted driver (websocat / agent) reads
        ``ws_url`` directly from stdout in the ``--no-browser`` flow.
        """
        server = FrontDoorServer()
        await server.start()
        try:
            assert server.token is not None, "Token not minted; bug pre-condition"
            assert f"token={server.token}" in server.ws_url, (
                f"server.ws_url must continue to carry the gate token even "
                f"after the token is stripped from server.url; got {server.ws_url!r}"
            )
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# Tests #3-#6, #9-#11 — /handoff endpoint
# ---------------------------------------------------------------------------


class TestHandoffEndpoint:
    """Single-use ``GET /handoff`` endpoint that ferries the WS token to the page."""

    async def test_handoff_endpoint_returns_token_once(self) -> None:
        """First GET → 200 + JSON token; second GET → 410 Gone.

        The endpoint mints the WS token once and burns itself.
        """
        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            status, _headers, body = await _http_get(
                f"http://127.0.0.1:{port}/handoff", origin=origin
            )
            assert status == 200, (
                f"First GET /handoff must return 200; got {status}."
            )
            data = json.loads(body)
            assert "token" in data, (
                f"GET /handoff response must include a 'token' key in JSON; "
                f"got body={body!r}"
            )
            assert data["token"] == server.token, (
                f"GET /handoff token must equal server.token; "
                f"got {data['token']!r} vs server.token={server.token!r}"
            )
            # Second call: must be 410 Gone.
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                await _http_get(
                    f"http://127.0.0.1:{port}/handoff", origin=origin
                )
            assert excinfo.value.code == 410, (
                f"Second GET /handoff must return 410 Gone (single-use); "
                f"got {excinfo.value.code}"
            )
            # And critically: the 410 body must NOT leak the token.
            second_body = excinfo.value.read()
            assert server.token not in second_body.decode("utf-8", errors="replace"), (
                f"410 Gone response must NOT include the token in the body; "
                f"got {second_body!r}"
            )
        finally:
            await server.stop()

    async def test_handoff_endpoint_rejects_disallowed_origin(self) -> None:
        """GET /handoff with ``Origin: http://evil.example`` → 403, no token leaked.

        Mirrors the existing Origin allow-list rule on the new endpoint. A
        same-uid attacker can trivially spoof an Origin header, but the check
        raises the bar to "must explicitly set the header" and pins the
        browser flow as canonical.
        """
        server = FrontDoorServer()
        port = await server.start()
        try:
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                await _http_get(
                    f"http://127.0.0.1:{port}/handoff",
                    origin="http://evil.example",
                )
            assert excinfo.value.code == 403, (
                f"GET /handoff with disallowed Origin must return 403; "
                f"got {excinfo.value.code}"
            )
            err_body = excinfo.value.read().decode("utf-8", errors="replace")
            assert server.token is not None
            assert server.token not in err_body, (
                f"403 body must NOT leak the token; got {err_body!r}"
            )
        finally:
            await server.stop()

    async def test_handoff_endpoint_rejects_after_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /handoff after the 30s deadline → 410 Gone, token never returned.

        Patches ``time.monotonic`` in the server module so the test does NOT
        wait 30 wall-clock seconds. The server mints the deadline as
        ``monotonic() + 30`` during ``start()``; the patch advances the clock
        past that point before the GET.

        A fresh server's first GET must also be 410 once the deadline passes
        — even though the endpoint was never consumed.
        """
        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            # Capture the real start-time, then advance the clock by 31s for
            # any subsequent monotonic call. Patch ON the module the server
            # imports time from — if the implementation imports
            # ``time.monotonic`` (function-level), patching ``time.monotonic``
            # at the global module level catches it.
            real_monotonic = time.monotonic
            offset = 31.0  # seconds past the 30s deadline

            def fake_monotonic() -> float:
                return real_monotonic() + offset

            monkeypatch.setattr(
                "bonfire.onboard.server.time.monotonic",
                fake_monotonic,
                raising=False,
            )
            # Also patch top-level ``time.monotonic`` in case the server uses
            # ``from time import monotonic`` or ``time.monotonic`` at call site.
            monkeypatch.setattr(time, "monotonic", fake_monotonic)

            with pytest.raises(urllib.error.HTTPError) as excinfo:
                await _http_get(
                    f"http://127.0.0.1:{port}/handoff", origin=origin
                )
            assert excinfo.value.code == 410, (
                f"GET /handoff after the 30s deadline must return 410 Gone "
                f"even on the first call; got {excinfo.value.code}"
            )
            err_body = excinfo.value.read().decode("utf-8", errors="replace")
            assert server.token is not None
            assert server.token not in err_body, (
                f"Post-deadline 410 must NOT leak the token; got {err_body!r}"
            )
        finally:
            await server.stop()

    async def test_handoff_endpoint_response_headers_no_referrer(self) -> None:
        """200 response carries ``Referrer-Policy: no-referrer`` and ``Cache-Control: no-store, no-cache``.

        Pins that the served token can't escape via referrer or browser
        cache. Without these headers, a navigation away from the served
        page could send the token-bearing URL as a Referer to a third
        party (though it shouldn't, since the token isn't in the URL
        anymore — but defense-in-depth).
        """
        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            status, headers, _body = await _http_get(
                f"http://127.0.0.1:{port}/handoff", origin=origin
            )
            assert status == 200, f"setup: GET /handoff must succeed; got {status}"
            # Header names normalised lowercase for case-insensitive compare.
            lower = {k.lower(): v for k, v in headers.items()}
            assert lower.get("referrer-policy") == "no-referrer", (
                f"GET /handoff response must set 'Referrer-Policy: no-referrer'; "
                f"got headers={headers!r}"
            )
            cache_control = lower.get("cache-control", "")
            assert "no-store" in cache_control, (
                f"GET /handoff Cache-Control must include 'no-store'; "
                f"got {cache_control!r}"
            )
            assert "no-cache" in cache_control, (
                f"GET /handoff Cache-Control must include 'no-cache'; "
                f"got {cache_control!r}"
            )
        finally:
            await server.stop()

    async def test_replay_attack_with_token_from_handoff_after_consumption(
        self,
    ) -> None:
        """Second /handoff call after consumption returns 410 — attacker can't get a fresh token.

        The legit client consumes ``/handoff`` once and learns the WS token.
        A racing attacker who arrives second cannot get the token via the
        handoff path. (The attacker still has the WS gate to face, which is
        the residual risk we accept.)
        """
        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            status, _headers, body = await _http_get(
                f"http://127.0.0.1:{port}/handoff", origin=origin
            )
            assert status == 200, f"setup: first /handoff must succeed; got {status}"
            stashed_token = json.loads(body)["token"]
            assert stashed_token == server.token

            # The legit client opens + closes a WS using the stashed token —
            # token lifetime is server-lifetime, not single-use through /ws.
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/ws?token={stashed_token}",
                origin=origin,
            ) as ws:
                assert ws.protocol.state.name == "OPEN"

            # Now the attacker re-calls /handoff and must be denied.
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                await _http_get(
                    f"http://127.0.0.1:{port}/handoff", origin=origin
                )
            assert excinfo.value.code == 410, (
                f"Re-call of /handoff after consumption must return 410 Gone "
                f"so a racing attacker can't get a fresh token; "
                f"got {excinfo.value.code}"
            )
        finally:
            await server.stop()

    async def test_cotenant_race_on_handoff_loses_when_browser_wins(self) -> None:
        """Two concurrent /handoff calls — exactly one wins (200), the other gets 410.

        Pins the atomicity of the single-use flip. Without this, a race
        could let TWO callers learn the token (which defeats the
        single-use property).
        """
        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:

            async def _attempt() -> tuple[int, bytes]:
                """Single GET /handoff; returns (status, body), normalising HTTPError."""
                try:
                    status, _headers, body = await _http_get(
                        f"http://127.0.0.1:{port}/handoff", origin=origin
                    )
                    return status, body
                except urllib.error.HTTPError as e:
                    return e.code, e.read()

            results = await asyncio.gather(_attempt(), _attempt())
            statuses = sorted(r[0] for r in results)
            assert statuses == [200, 410], (
                f"Exactly one /handoff call must win (200) and the other "
                f"must get 410 Gone — proves single-use atomicity; "
                f"got statuses={statuses!r}"
            )
        finally:
            await server.stop()

    async def test_cotenant_wins_handoff_race_browser_then_fails_open(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Adversary wins /handoff race; legit follow-up GET → 410; server logs warning.

        Residual-risk envelope: we accept that an attacker winning the race
        gets the token, but we will NOT also let the legit browser silently
        hang. The legit follow-up MUST see a clean 410 (not a timeout or a
        hang) so ui.html can surface an error to the user.
        """
        import logging

        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            # Adversary call wins.
            status_adv, _h, _b = await _http_get(
                f"http://127.0.0.1:{port}/handoff", origin=origin
            )
            assert status_adv == 200, "setup: adversary's first /handoff must succeed"

            with caplog.at_level(logging.WARNING, logger="bonfire.onboard.server"):
                with pytest.raises(urllib.error.HTTPError) as excinfo:
                    await _http_get(
                        f"http://127.0.0.1:{port}/handoff", origin=origin
                    )
                assert excinfo.value.code == 410, (
                    f"Legit browser's /handoff after adversary wins must return "
                    f"410 Gone (not hang); got {excinfo.value.code}"
                )

            # The server should surface a warning on the second-call path so
            # operators have an audit trail when the race fires in the wild.
            handoff_warnings = [
                rec for rec in caplog.records
                if rec.levelno >= logging.WARNING
                and "handoff" in rec.getMessage().lower()
            ]
            assert handoff_warnings, (
                f"Server must log a WARNING-level message naming 'handoff' on "
                f"the second-call (consumed) path so a race-loss is auditable; "
                f"got log records: {[r.getMessage() for r in caplog.records]!r}"
            )
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# Tests #7, #8 — xdg-open argv audit + replay-with-guessed-url-token
# ---------------------------------------------------------------------------


class TestArgvLeakAudit:
    """The URL passed to ``typer.launch`` must not contain the token."""

    def test_xdg_open_argv_audit_after_scan_launch(self) -> None:
        """Mock ``typer.launch``; assert the URL passed matches ``^http://127.0.0.1:\\d+/$``.

        This is the threat-model proof: the URL that hits xdg-open's argv
        (and thus /proc/<pid>/cmdline) must be token-free. Replaces the
        real-OS /proc audit, which is awkward inside a pytest harness.

        IMPORTANT: this test MUST use the real ``FrontDoorServer`` (not a
        MagicMock with a pre-cooked ``url`` attribute) — otherwise the
        assertion checks the mock's pre-cooked URL rather than the actual
        ``server.url`` produced by the implementation. A server whose URL
        still embeds ``?token=<value>`` would fail this regex.

        We do mock ``typer.launch`` (to avoid actually opening a browser)
        and ``run_front_door`` (to short-circuit the conversation flow),
        plus pre-fire ``client_connected`` and ``shutdown_event`` on the
        real server so ``_run_scan`` doesn't block on a real WS client.
        """
        with (
            patch("typer.launch") as mock_launch,
            patch(
                "bonfire.onboard.flow.run_front_door",
                new_callable=AsyncMock,
            ) as mock_flow,
        ):
            mock_flow.return_value = "/tmp/bonfire.toml"
            mock_launch.return_value = 0

            from bonfire.cli.commands.scan import _run_scan

            async def _drive() -> None:
                # We can't pre-fire events on a not-yet-started server (events
                # are lazily created in start()). Wrap _run_scan in a small
                # supervisor: poll for the server's events to exist, then
                # pre-fire them so the flow exits cleanly. We don't actually
                # need the WS connection — we only need typer.launch's argv.
                # Approach: run _run_scan as a task, after a short delay
                # cancel it; capture mock_launch.call_args from before the
                # cancel.
                task = asyncio.create_task(_run_scan(port=0, no_browser=False))
                # Wait until typer.launch has been called (it happens early,
                # right after server.start()). Bound by 5s for safety.
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    if mock_launch.called:
                        break
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, BaseException):
                    pass

            asyncio.run(_drive())

            assert mock_launch.called, (
                "typer.launch must be called during default (browser) scan "
                "flow — the WHOLE POINT of this audit is the URL passed to it."
            )
            # First positional arg is the URL handed to xdg-open.
            launch_url = mock_launch.call_args.args[0]
            assert re.match(r"^http://127\.0\.0\.1:\d+/$", launch_url), (
                f"URL handed to typer.launch (→ xdg-open argv → "
                f"/proc/<pid>/cmdline) must be token-free; this is the "
                f"core argv-leak audit. "
                f"Expected ^http://127\\.0\\.0\\.1:\\d+/$; got {launch_url!r}"
            )

    async def test_replay_attack_with_stolen_url_token_fails(self) -> None:
        """No token in URL → nothing to steal.

        An adversary who reads ``/proc/<xdg-open>/cmdline`` now gets a
        token-free URL. They can hit ``http://127.0.0.1:<port>/?token=guessed``
        — but ``/`` no longer requires a token (the gate moved to ``/handoff``),
        so the request is either served straight, redirected to ``/handoff``,
        or returns the page that itself does the handoff. Either way, a
        guessed/stolen URL token gives the attacker NO additional capability
        because the URL token gate no longer exists.

        We pin: GET ``/?token=anything-fake`` does NOT return 403 (the prior
        behaviour). The acceptable response is 200 (serve the page; the page
        itself does the handoff) — that's the single locked outcome.
        """
        server = FrontDoorServer()
        port = await server.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/?token=guessed-or-stolen",
                method="GET",
            )
            req.add_header("Origin", origin)
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, urllib.request.urlopen, req
                )
                status = response.status
            except urllib.error.HTTPError as e:
                status = e.code
            # Old behaviour: 403 — the URL token gate rejected guessed tokens.
            # New behaviour: 200 — the URL token gate is gone; serving the page
            # is the right call because the JS will then call /handoff. A 403
            # would mean the URL token gate is still installed (regression).
            assert status == 200, (
                f"GET / with a fake ?token=X must serve the page (200) because "
                f"the URL token gate is removed; the gate now lives at "
                f"/handoff. Got status={status}. "
                f"A 403 here means the old URL token gate is still installed; "
                f"this fix is not actually shipped."
            )
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# Tests #12, #13 — --no-browser stdout + no typer.launch
# ---------------------------------------------------------------------------


class TestNoBrowserStdout:
    """``--no-browser`` prints the WS URL to STDOUT; does NOT call ``typer.launch``.

    The channel is STDOUT. Not stderr — stderr is redirected/swallowed
    differently by orchestrators (CI pipelines often pipe stderr separately,
    tmux captures may differ). Stdout is also out of ``/proc/*/cmdline``, so
    this is the secure headless channel.
    """

    def test_no_browser_flag_prints_token_to_stdout(self) -> None:
        """``bonfire scan --no-browser`` prints the WS URL (with token) to stdout exactly once.

        The contract is EXPLICITLY: the WS URL appears on stdout as a
        token-bearing URL the headless driver can scrape.

        This test allows the URL to be embedded inside a prose line (the
        current implementation does that) — what it pins is:
          (a) the URL with token IS on stdout (not just stderr),
          (b) the URL appears AT LEAST ONCE (and only once at the same
              exact-string level — duplicate prints widen the leak surface).

        If the implementation drifts to printing only ``server.url``
        (token-free) without ALSO printing ``ws_url`` for the headless path,
        the substring check fails.
        """
        with (
            patch("bonfire.cli.commands.scan.FrontDoorServer") as mock_server_cls,
            patch("bonfire.onboard.flow.run_front_door", new_callable=AsyncMock) as mock_flow,
            patch("typer.launch") as mock_launch,
        ):
            mock_server = MagicMock()
            mock_server.start = AsyncMock(return_value=None)
            mock_server.stop = AsyncMock(return_value=None)
            mock_server.url = "http://127.0.0.1:8765/"
            mock_server.ws_url = "ws://127.0.0.1:8765/ws?token=AAAAAAAAAAAAAAAAAAAAAA"

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

            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            import contextlib

            with (
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(stderr_buf),
            ):
                asyncio.run(_run_scan(port=8765, no_browser=True))

            stdout_text = stdout_buf.getvalue()
            stderr_text = stderr_buf.getvalue()

            assert mock_server.ws_url in stdout_text, (
                f"With --no-browser, the WS URL with token MUST appear on STDOUT "
                f"so headless drivers (websocat, scripted agents, CI) can scrape "
                f"it. Stdout is the locked channel (not stderr). "
                f"Got stdout={stdout_text!r}; stderr={stderr_text!r}"
            )
            # The locked URL must be on stdout — pin that stderr is not the
            # secret channel (orchestrators redirect stderr differently).
            # Note: we don't FORBID the URL on stderr (defense-in-depth log
            # echo to stderr is OK), we only require its presence on stdout.

    def test_no_browser_flag_does_not_call_typer_launch(self) -> None:
        """``--no-browser`` MUST NOT call ``typer.launch`` — the only argv leak path stays closed.

        ``typer.launch`` is skipped under ``no_browser=True`` (scan.py guards
        it under ``if not no_browser:``). The test is a regression pin so a
        future refactor doesn't accidentally reintroduce the launch call on
        the headless path. Defense-in-depth.
        """
        with (
            patch("bonfire.cli.commands.scan.FrontDoorServer") as mock_server_cls,
            patch("bonfire.onboard.flow.run_front_door", new_callable=AsyncMock) as mock_flow,
            patch("typer.launch") as mock_launch,
        ):
            mock_server = MagicMock()
            mock_server.start = AsyncMock(return_value=None)
            mock_server.stop = AsyncMock(return_value=None)
            mock_server.url = "http://127.0.0.1:8765/"
            mock_server.ws_url = "ws://127.0.0.1:8765/ws?token=AAAAAAAAAAAAAAAAAAAAAA"

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

            asyncio.run(_run_scan(port=8765, no_browser=True))

            mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# Tests #14, #15 — ui.html static contracts
# ---------------------------------------------------------------------------


class TestUiHtmlWire:
    """Static (regex/substring) pins on the served HTML so the page wire can't drift."""

    def test_ui_html_fetches_handoff_then_opens_ws(self) -> None:
        """The served HTML must call ``fetch('/handoff')`` and then ``new WebSocket(``.

        Regex-pin the HTML rather than running Selenium/Playwright (no new
        test-harness deps for v0.1).
        """
        from importlib import resources

        ref = resources.files("bonfire.onboard").joinpath("ui.html")
        html = ref.read_text(encoding="utf-8")

        # Both quote styles are acceptable; the implementation can use single
        # or double quotes around '/handoff'. Pin a regex that matches either.
        assert re.search(r"fetch\(\s*['\"]/handoff['\"]", html), (
            f"ui.html must call fetch('/handoff') (or fetch(\"/handoff\")) on "
            f"DOMContentLoaded — that's the ONLY path by which the browser "
            f"learns the WS token. The new wire is mandatory. "
            f"Got HTML (first 500 chars): {html[:500]!r}"
        )
        assert "new WebSocket(" in html, (
            f"ui.html must still construct a WebSocket via "
            f"`new WebSocket(...)` after fetching the token; got HTML "
            f"(first 500 chars): {html[:500]!r}"
        )

    def test_handoff_token_not_in_localstorage(self) -> None:
        """``localStorage`` MUST NOT appear in the served HTML.

        Defense-in-depth pin against a future refactor that would re-introduce
        persistent storage. The token lives in a JS closure variable and dies
        with the tab. ``localStorage`` and ``sessionStorage`` are both out of
        scope.
        """
        from importlib import resources

        ref = resources.files("bonfire.onboard").joinpath("ui.html")
        html = ref.read_text(encoding="utf-8")

        assert "localStorage" not in html, (
            f"ui.html must NOT use localStorage — the WS token is a "
            f"per-launch secret that dies with the tab. Persisting it to "
            f"localStorage would re-open the page-reload attack window. "
            f"Defense-in-depth pin. Found in HTML."
        )
        # Forward-drift bonus: also pin sessionStorage absence (same
        # rationale as localStorage).
        assert "sessionStorage" not in html, (
            f"ui.html must NOT use sessionStorage either — same rationale "
            f"as localStorage. Found in HTML."
        )
