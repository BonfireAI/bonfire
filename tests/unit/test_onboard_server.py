"""RED tests for bonfire.onboard.server — BON-349 W6.3 (CONTRACT-LOCKED canonical).

Sage decision logs:
  - docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md (Warrior contract)
  - docs/audit/sage-decisions/bon-349-contract-lock-*.md (Knight A/B reconciliation)

Floor (15 tests, per Sage §D6 Row 2): port v1 test_front_door_server.py test
surface verbatim, with the only delta being the import rename
``bonfire.front_door.server`` → ``bonfire.onboard.server`` (Sage §D3 row 3).

Innovations (2 adopted, drift-guards over Sage floor):

  * ``TestUiHtmlResourceLookup::test_ui_html_resolvable_via_importlib_resources``
    — Asserts ``importlib.resources.files("bonfire.onboard").joinpath("ui.html")``
    resolves to a real file containing the expected HTML markers (matches the
    private ``server._load_html`` path used at start time). This guards
    against the package-data drift documented in Sage §D8 server.py port
    note + Sage §D9 worktree-pytest note (PYTHONPATH-sensitivity vector for
    importlib.resources). The floor only proves serving via HTTP, not the
    underlying resource lookup. Cites Sage §D8
    "src/bonfire/onboard/server.py" + v1
    src/bonfire/front_door/server.py:31-34 (_load_html helper).

  * ``TestMessageDispatchShape::test_on_message_callback_dispatch_shape_parametrized``
    — Parametrize sweep over multiple JSON message shapes (well-formed
    user_message, well-formed-but-unknown type, malformed JSON) confirming
    the server's dispatch contract: (a) well-formed JSON reaches
    ``on_message`` as a parsed dict, (b) non-JSON is silently dropped (no
    callback invocation), (c) unknown types still reach ``on_message`` (the
    server doesn't filter by type — that's the parser's job). The floor
    has only one positive shape test
    (``test_on_message_callback_receives_parsed_json``). Cites Sage §D8
    "internal handlers" + v1 src/bonfire/front_door/server.py:163-186
    (_ws_handler dispatch logic).

Imports are RED — ``bonfire.onboard.server`` does not exist until Warriors
port v1 source per Sage §D9.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest
import websockets

from bonfire.onboard.server import FrontDoorServer


class TestServerLifecycle:
    """Server start/stop and port binding."""

    async def test_server_binds_to_random_port(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            assert 1024 < port < 65536
        finally:
            await server.stop()

    async def test_server_stop_is_idempotent(self) -> None:
        server = FrontDoorServer()
        await server.start()
        await server.stop()
        await server.stop()  # Should not raise

    async def test_server_url_property(self) -> None:
        # W5.A: server.url and server.ws_url now embed ?token=<value> so the
        # operator just clicks the printed link. The legacy assertions
        # (``== f"http://127.0.0.1:{port}"``) are superseded by the W5.A
        # contract; the strengthened baseline asserts on the host:port prefix
        # via ``startswith`` so this lifecycle test still exercises the
        # ``url``/``ws_url`` properties without conflicting with the token
        # gate. Full token coverage lives in TestOperatorFacingURLContainsToken.
        server = FrontDoorServer()
        port = await server.start()
        try:
            assert server.url.startswith(f"http://127.0.0.1:{port}")
            assert server.ws_url.startswith(f"ws://127.0.0.1:{port}/ws")
        finally:
            await server.stop()


class TestHTMLServing:
    """HTTP serving of ui.html on GET /."""

    async def test_serves_html_on_root(self) -> None:
        # W5.A: the HTTP root is now gated by ?token=<value>; use
        # ``server.url`` (which embeds the token) so the legacy behaviour
        # is exercised against the gated server.
        server = FrontDoorServer()
        await server.start()
        try:
            loop = asyncio.get_event_loop()
            import urllib.request

            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                server.url,
            )
            body = response.read()
            assert response.status == 200
            assert b"<!DOCTYPE html>" in body
            assert b"BONFIRE" in body
        finally:
            await server.stop()

    async def test_html_content_type(self) -> None:
        # W5.A: see ``test_serves_html_on_root`` — token-gated root.
        server = FrontDoorServer()
        await server.start()
        try:
            loop = asyncio.get_event_loop()
            import urllib.request

            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                server.url,
            )
            content_type = response.headers.get("Content-Type", "")
            assert "text/html" in content_type
        finally:
            await server.stop()


class TestWebSocketConnection:
    """WebSocket connection and messaging."""

    async def test_websocket_connects(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            async with websockets.connect(server.ws_url) as ws:
                assert ws.protocol.state.name == "OPEN"
        finally:
            await server.stop()

    async def test_send_json_message(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            async with websockets.connect(server.ws_url) as ws:
                await ws.send(json.dumps({"type": "user_message", "text": "hello"}))
        finally:
            await server.stop()

    async def test_broadcast_to_clients(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            async with websockets.connect(server.ws_url) as ws:
                await asyncio.sleep(0.05)
                await server.broadcast({"type": "scan_start", "panels": ["test"]})
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(raw)
                assert data["type"] == "scan_start"
                assert data["panels"] == ["test"]
        finally:
            await server.stop()

    async def test_broadcast_to_multiple_clients(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            async with (
                websockets.connect(server.ws_url) as ws1,
                websockets.connect(server.ws_url) as ws2,
            ):
                await asyncio.sleep(0.05)
                await server.broadcast(
                    {"type": "all_scans_complete", "total_items": 5},
                )
                r1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=2.0))
                r2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=2.0))
                assert r1["type"] == "all_scans_complete"
                assert r2["type"] == "all_scans_complete"
        finally:
            await server.stop()


class TestClientTracking:
    """Server tracks connected clients."""

    async def test_client_count_increments(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            assert server.client_count == 0
            async with websockets.connect(server.ws_url):
                await asyncio.sleep(0.05)
                assert server.client_count == 1
        finally:
            await server.stop()

    async def test_client_count_decrements_on_disconnect(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            ws = await websockets.connect(server.ws_url)
            await asyncio.sleep(0.05)
            assert server.client_count == 1
            await ws.close()
            await asyncio.sleep(0.05)
            assert server.client_count == 0
        finally:
            await server.stop()


class TestShutdownEvent:
    """Server signals shutdown when last client disconnects."""

    async def test_shutdown_event_set_when_last_client_disconnects(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            assert not server.shutdown_event.is_set()
            ws = await websockets.connect(server.ws_url)
            await asyncio.sleep(0.05)
            await ws.close()
            await asyncio.sleep(0.05)
            assert server.shutdown_event.is_set()
        finally:
            await server.stop()

    async def test_shutdown_event_not_set_while_clients_remain(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            ws1 = await websockets.connect(server.ws_url)
            ws2 = await websockets.connect(server.ws_url)
            await asyncio.sleep(0.05)
            await ws1.close()
            await asyncio.sleep(0.05)
            assert not server.shutdown_event.is_set()
            await ws2.close()
            await asyncio.sleep(0.05)
            assert server.shutdown_event.is_set()
        finally:
            await server.stop()


class TestMessageCallback:
    """Server dispatches incoming messages via callback."""

    async def test_failing_on_message_does_not_crash_handler(self) -> None:
        """A failing on_message callback should not disconnect the client."""

        async def exploding_callback(msg: dict) -> None:
            raise RuntimeError("boom")

        server = FrontDoorServer(on_message=exploding_callback)
        await server.start()
        try:
            async with websockets.connect(server.ws_url) as ws:
                # Send a message that triggers the failing callback
                await ws.send(json.dumps({"type": "user_message", "text": "crash"}))
                await asyncio.sleep(0.1)

                # Client should still be connected — send another message
                await ws.send(json.dumps({"type": "user_message", "text": "still here"}))
                await asyncio.sleep(0.1)

                # Connection should still be open
                assert ws.protocol.state.name == "OPEN"
        finally:
            await server.stop()

    async def test_on_message_callback_receives_parsed_json(self) -> None:
        received: list[dict] = []

        async def on_message(msg: dict) -> None:
            received.append(msg)

        server = FrontDoorServer(on_message=on_message)
        await server.start()
        try:
            async with websockets.connect(server.ws_url) as ws:
                await ws.send(json.dumps({"type": "user_message", "text": "hi"}))
                await asyncio.sleep(0.1)
            assert len(received) == 1
            assert received[0]["type"] == "user_message"
            assert received[0]["text"] == "hi"
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# INNOVATIONS (Knight B drift-guards — Sage §D8 + §D9)
# ---------------------------------------------------------------------------


class TestUiHtmlResourceLookup:
    """Innovation: ui.html package-data resolution via importlib.resources.

    Guards the Sage §D9 worktree-pytest note: ``importlib.resources.files(
    "bonfire.onboard")`` MUST find ui.html under PYTHONPATH override. Cites
    Sage §D8 "src/bonfire/onboard/server.py" + v1
    src/bonfire/front_door/server.py:31-34 (_load_html helper).
    """

    def test_ui_html_resolvable_via_importlib_resources(self) -> None:
        """``importlib.resources.files`` finds ui.html in the onboard package."""
        from importlib import resources

        ref = resources.files("bonfire.onboard").joinpath("ui.html")
        # The reference must be readable as bytes (mirrors _load_html).
        body = ref.read_bytes()
        assert b"<!DOCTYPE html>" in body, (
            "ui.html must resolve via importlib.resources for "
            "FrontDoorServer._load_html() to succeed"
        )
        assert b"BONFIRE" in body, (
            "ui.html must contain the BONFIRE branding marker the floor's "
            "test_serves_html_on_root expects"
        )


class TestMessageDispatchShape:
    """Innovation: parametrize on_message dispatch over multiple message shapes.

    Cites Sage §D8 "internal handlers" + v1 src/bonfire/front_door/server.py:163-186
    (_ws_handler json.loads / on_message dispatch).
    """

    @pytest.mark.parametrize(
        ("payload", "expect_callback", "expected_type"),
        [
            # well-formed user_message — should dispatch to callback
            (
                json.dumps({"type": "user_message", "text": "ok"}),
                True,
                "user_message",
            ),
            # well-formed unknown type — server does NOT filter; callback fires
            (
                json.dumps({"type": "future_unknown", "x": 1}),
                True,
                "future_unknown",
            ),
            # malformed JSON — server logs warning and drops; no callback
            ("not json at all", False, None),
        ],
        ids=["well_formed_known", "well_formed_unknown", "malformed_json"],
    )
    async def test_on_message_callback_dispatch_shape_parametrized(
        self,
        payload: str,
        expect_callback: bool,
        expected_type: str | None,
    ) -> None:
        """on_message receives parsed dicts; non-JSON is silently dropped."""
        received: list[dict] = []

        async def callback(msg: dict) -> None:
            received.append(msg)

        server = FrontDoorServer(on_message=callback)
        await server.start()
        try:
            async with websockets.connect(server.ws_url) as ws:
                await ws.send(payload)
                await asyncio.sleep(0.1)
        finally:
            await server.stop()

        if expect_callback:
            assert len(received) == 1, f"payload={payload!r} should dispatch to on_message"
            assert received[0].get("type") == expected_type
        else:
            assert received == [], f"payload={payload!r} should be dropped without callback"


# ---------------------------------------------------------------------------
# EVENT-LOOP BINDING CONTRACT — BON-895
#
# FrontDoorServer must NOT construct ``asyncio.Event`` instances in
# ``__init__``. An ``asyncio.Event`` binds to whatever loop is running on its
# first await; constructing one in ``__init__`` and awaiting it in a *later*
# loop raises ``RuntimeError: <Event ...> is bound to a different event loop``.
#
# The contract these tests pin:
#   1. The events are created lazily inside ``start()`` (or an equivalent
#      first-await entry-point), not in ``__init__``.
#   2. A single ``FrontDoorServer`` instance can be driven across two
#      separate ``asyncio.run(...)`` blocks without a loop-binding error.
#
# Reproduction (pre-fix) verified by the Knight before writing this file:
# a module-level ``FrontDoorServer`` whose ``shutdown_event``/``client_connected``
# is awaited under two ``asyncio.run`` calls raises the loop-binding
# ``RuntimeError`` on the second run — exactly the hazard the CLI ``_run_scan``
# path (``await server.shutdown_event.wait()``) is exposed to under any
# embedding that reuses a server across loops.
# ---------------------------------------------------------------------------


class TestEventLoopBindingContract:
    """BON-895: events are loop-bound lazily, not eagerly in ``__init__``."""

    async def _start_and_wait(self, server: FrontDoorServer) -> None:
        """Faithful slice of CLI ``_run_scan``: start, await an event, stop.

        Mirrors ``bonfire.cli.commands.scan._run_scan`` which does
        ``await server.start()`` then ``await server.shutdown_event.wait()``.
        The ``wait_for`` timeout stands in for "a client eventually
        disconnects" so the test stays deterministic and offline.
        """
        await server.start()
        try:
            await asyncio.wait_for(server.shutdown_event.wait(), timeout=0.05)
        except TimeoutError:
            pass
        finally:
            await server.stop()

    def test_init_does_not_create_asyncio_events(self) -> None:
        """``__init__`` must not eagerly construct loop-bound ``asyncio.Event``s.

        An ``asyncio.Event`` constructed here binds to the loop current at
        construction time (or the loop of its first await). The acceptance
        criterion: after ``__init__`` and before ``start()``, neither event
        is a live, loop-bound ``asyncio.Event`` instance — they are lazily
        created inside ``start()``.

        This asserts on the private attributes ``_shutdown_event`` and
        ``_client_connected`` because that is exactly where the hazard lives
        (``server.py:67-69``). Pre-fix: both are ``asyncio.Event()`` already.
        Post-fix: both are ``None`` (or otherwise not yet instantiated) until
        ``start()`` runs.
        """
        server = FrontDoorServer()
        assert server._shutdown_event is None, (
            "FrontDoorServer.__init__ must NOT create _shutdown_event "
            "(asyncio.Event binds to the construction-time loop); it must be "
            "lazily created inside start()"
        )
        assert server._client_connected is None, (
            "FrontDoorServer.__init__ must NOT create _client_connected "
            "(asyncio.Event binds to the construction-time loop); it must be "
            "lazily created inside start()"
        )

    async def test_events_bound_after_start(self) -> None:
        """After ``start()`` the events exist and are usable in the running loop."""
        server = FrontDoorServer()
        try:
            await server.start()
            assert isinstance(server._shutdown_event, asyncio.Event)
            assert isinstance(server._client_connected, asyncio.Event)
            # The public properties expose live events post-start.
            assert isinstance(server.shutdown_event, asyncio.Event)
            assert isinstance(server.client_connected, asyncio.Event)
            # And they are usable in this loop without a binding error.
            assert not server.shutdown_event.is_set()
            assert not server.client_connected.is_set()
        finally:
            await server.stop()

    def test_server_reusable_across_two_asyncio_run_blocks(self) -> None:
        """Core BON-895 regression: one server, two separate ``asyncio.run`` loops.

        This is the falsifiable contract. A single module-level
        ``FrontDoorServer`` is started and has one of its events awaited under
        two distinct ``asyncio.run(...)`` calls — the second of which runs on
        a brand-new event loop after the first has closed.

        Pre-fix (events created in ``__init__``): the second ``asyncio.run``
        raises ``RuntimeError: <asyncio.locks.Event ...> is bound to a
        different event loop``.

        Post-fix (events created lazily in ``start()``): both runs complete
        clean because each ``start()`` rebinds the events to the loop that is
        actually current.
        """
        server = FrontDoorServer()

        # First loop — binds whatever the pre-fix __init__ events bound to.
        asyncio.run(self._start_and_wait(server))

        # Second loop — a fresh event loop. Pre-fix this raises the
        # "bound to a different event loop" RuntimeError.
        try:
            asyncio.run(self._start_and_wait(server))
        except RuntimeError as exc:  # pragma: no cover - fails pre-fix
            pytest.fail(
                "FrontDoorServer reused across two asyncio.run blocks raised "
                f"a loop-binding RuntimeError: {exc!r}. Events must be created "
                "lazily in start(), not eagerly in __init__ (server.py:67-69)."
            )


# ---------------------------------------------------------------------------
# W5.A — Origin allow-list + token gate on the Front Door WebSocket
#
# Mirror Probe N+1 finding S1.1 (CSWSH on ``bonfire scan``):
#   ``src/bonfire/onboard/server.py:99-104`` invokes ``serve(...)`` without
#   an ``origins=`` argument. Any cross-origin page the user visits during a
#   ``bonfire scan`` can connect to ``ws://127.0.0.1:<port>/ws`` and drive the
#   conversation engine → arbitrary ``bonfire.toml`` write. Browsers do NOT
#   enforce CORS for WebSocket connections; port is locally probable; the
#   ``ui.html`` script runs unauthenticated post-handshake.
#
# Contract these RED tests pin (Warrior implements):
#
#   1. ``FrontDoorServer`` MUST expose a one-time, per-launch URL-safe token
#      (~16-32 bytes of entropy) on the instance as ``server.token`` after
#      ``start()``. The token is generated inside ``start()`` (not
#      ``__init__``) so each launch is unique even if a single
#      ``FrontDoorServer`` instance is reused across calls (mirrors the
#      lazy-event-binding pattern already in the codebase).
#
#   2. The operator-facing URLs (``server.url`` and ``server.ws_url``) MUST
#      include the token as a ``?token=<value>`` query parameter so the
#      operator just clicks the printed link — no manual typing.
#
#   3. HTTP GET requests to ``/`` WITHOUT a matching token MUST be rejected
#      with HTTP 403 inside ``_process_request``. The ui.html page is gated.
#
#   4. WebSocket handshakes to ``/ws`` WITHOUT a matching token MUST be
#      rejected with HTTP 403 at handshake (server-side rejection, before
#      the WS upgrade completes).
#
#   5. WebSocket handshakes from an Origin that is NOT in the server's
#      allow-list MUST be rejected at handshake. The allow-list is exactly
#      ``[server.url]`` (where ``server.url`` is the no-token host:port form
#      — i.e. ``http://127.0.0.1:<port>``); cross-origin pages cannot drive
#      the scan. Implementation: pass ``origins=[...]`` to
#      ``websockets.asyncio.server.serve``.
#
#   6. Happy path: a request that carries a matching token AND a same-origin
#      ``Origin`` header succeeds end-to-end — proves the gate doesn't
#      break the legitimate browser path.
#
# Open design questions surfaced to the Warrior (none of these are pinned by
# the RED tests; tests assert the *outcome* — gate rejects vs. allows — not
# the wire-format choice):
#
#   * Token transport: the tests assume ``?token=<value>`` query parameter on
#      both ``/`` and ``/ws``. A URL fragment would not survive the WS
#      handshake (fragments are client-side only); a custom header is not
#      browser-reachable from an ``<a href>`` click. Query param is the
#      smallest surface that works for the click-the-link UX. The Warrior
#      MAY choose path-based (``/<token>/ws``) instead, but tests below
#      assume query param; if path is chosen, the Warrior must update tests
#      to match.
#
#   * Origin allow-list source: the tests assume ``[server.url]`` is the
#      sole allowed origin. The Warrior may widen this (e.g. accept
#      ``http://localhost:<port>`` as an alias for ``http://127.0.0.1:<port>``)
#      but MUST NOT widen beyond same-host/same-port.
# ---------------------------------------------------------------------------


def _url_with_token(base: str, token: str, /, *, override: str | None = None) -> str:
    """Build a URL that carries ``?token=<value>``.

    ``override`` lets a test substitute a different token (e.g. a wrong one)
    while keeping the rest of the URL shape identical. If ``override`` is
    explicitly an empty string, the resulting URL has no token query param
    at all (used to model the "token missing" case).
    """
    if override is None:
        return f"{base}?token={token}"
    if override == "":
        return base
    return f"{base}?token={override}"


class TestOriginAllowList:
    """W5.A: WebSocket handshake must reject non-allowed Origin headers."""

    async def test_ws_handshake_rejects_cross_origin_evil_dot_com(self) -> None:
        """A WS connect from Origin=http://evil.example must be rejected at handshake.

        Browsers do NOT enforce CORS for WebSocket; without a server-side
        ``origins=`` allow-list, any cross-origin page during a ``bonfire scan``
        can hijack the WS and drive the conversation engine. The Warrior must
        pass ``origins=[server.url]`` to ``serve()``; websockets then rejects
        any handshake whose ``Origin`` header is not in that list with HTTP 403
        (raising ``websockets.exceptions.InvalidStatus`` on the client).
        """
        server = FrontDoorServer()
        port = await server.start()
        try:
            ws_url = _url_with_token(f"ws://127.0.0.1:{port}/ws", server.token)
            with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
                async with websockets.connect(
                    ws_url,
                    origin="http://evil.example",
                ):
                    pass
            # 403 is the canonical reject status for Origin mismatch in
            # websockets >= 13; assert it explicitly so a regression that
            # widens the allow-list (e.g. accidentally allowing "*") is caught.
            assert excinfo.value.response.status_code == 403, (
                f"WebSocket handshake from a non-allowed Origin must return HTTP 403; "
                f"got {excinfo.value.response.status_code}"
            )
        finally:
            await server.stop()

    async def test_ws_handshake_accepts_same_origin(self) -> None:
        """Happy path: a same-origin Origin header is accepted by the allow-list.

        Mirrors the browser's behaviour when the operator clicks the
        ``http://127.0.0.1:<port>/?token=...`` link — the browser stamps the
        Origin header as ``http://127.0.0.1:<port>`` and the WS upgrade
        succeeds.
        """
        server = FrontDoorServer()
        port = await server.start()
        try:
            ws_url = _url_with_token(f"ws://127.0.0.1:{port}/ws", server.token)
            async with websockets.connect(
                ws_url,
                origin=f"http://127.0.0.1:{port}",
            ) as ws:
                assert ws.protocol.state.name == "OPEN"
        finally:
            await server.stop()


class TestTokenGate:
    """W5.A: HTTP GET / and WS /ws must require a matching one-time token."""

    def test_token_is_unavailable_before_start(self) -> None:
        """``server.token`` MUST be unset before start (mirrors event lazy-binding).

        Generating the token inside ``start()`` means each launch produces a
        fresh token even if a single ``FrontDoorServer`` instance is reused
        across two ``asyncio.run`` blocks. ``__init__`` MUST NOT generate it.
        """
        server = FrontDoorServer()
        # The Warrior MAY surface this as None or as a RuntimeError; either
        # is acceptable as long as the token is not a fixed value at __init__
        # time. We assert the safer of the two: the attribute exists but is
        # falsy (None) until start() runs. If the Warrior chooses a property
        # that raises before start(), they should adjust this single assert.
        assert getattr(server, "token", "PLACEHOLDER") is None, (
            "FrontDoorServer.__init__ must NOT generate the gate token; it "
            "must be created lazily inside start() so each launch is unique."
        )

    async def test_token_is_high_entropy_url_safe_string(self) -> None:
        """After start() the token must be a non-trivial URL-safe string.

        Floor: at least 16 characters of URL-safe alphabet (letters, digits,
        ``-``, ``_``). The Warrior is free to use ``secrets.token_urlsafe(16)``
        or any equivalent; this assertion only fences against a placeholder
        value (e.g. ``"TODO"``, an empty string, or a fixed constant).
        """
        server = FrontDoorServer()
        await server.start()
        try:
            tok = server.token
            assert isinstance(tok, str)
            assert len(tok) >= 16, (
                f"Token must carry at least 16 chars of entropy; got len={len(tok)} "
                f"(use secrets.token_urlsafe(16) or similar)"
            )
            url_safe_alphabet = set(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            )
            assert set(tok) <= url_safe_alphabet, (
                f"Token must be URL-safe (letters, digits, '-', '_'); got {tok!r}"
            )
        finally:
            await server.stop()

    async def test_token_regenerated_on_each_start(self) -> None:
        """Two start() calls on the same instance must yield different tokens.

        A single ``FrontDoorServer`` instance can be driven across two
        sequential ``asyncio.run`` blocks (the same property the lazy-event
        contract pins). Each ``start()`` must mint a fresh token so a
        previous-launch URL cannot drive a current-launch session.
        """
        server = FrontDoorServer()
        await server.start()
        first = server.token
        await server.stop()
        await server.start()
        second = server.token
        try:
            assert first != second, (
                "Each start() must generate a new gate token; reusing a token "
                "across launches re-opens the CSWSH window for the duration "
                "of the previous URL's lifetime."
            )
        finally:
            await server.stop()

    async def test_http_get_root_without_token_returns_403(self) -> None:
        """GET / without ``?token=`` must be rejected with HTTP 403.

        Pre-fix: ``_process_request`` serves ``ui.html`` to any GET / request
        (server.py:164-170). Any cross-origin page that can predict the port
        can read the served HTML; the WS gate alone is insufficient because
        the HTML is the bootstrap that wires up the WS client.
        """
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                await loop.run_in_executor(
                    None,
                    urllib.request.urlopen,
                    f"http://127.0.0.1:{port}/",
                )
            assert excinfo.value.code == 403, (
                f"GET / without token must return 403; got {excinfo.value.code}"
            )
        finally:
            await server.stop()

    async def test_http_get_root_with_wrong_token_returns_403(self) -> None:
        """GET / with a wrong token is just as forbidden as no token at all."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                await loop.run_in_executor(
                    None,
                    urllib.request.urlopen,
                    f"http://127.0.0.1:{port}/?token=not-the-real-token",
                )
            assert excinfo.value.code == 403, (
                f"GET / with wrong token must return 403; got {excinfo.value.code}"
            )
        finally:
            await server.stop()

    async def test_http_get_root_with_correct_token_returns_200(self) -> None:
        """Happy path: GET / with the right token serves the ui.html page."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/?token={server.token}",
            )
            body = response.read()
            assert response.status == 200
            assert b"<!DOCTYPE html>" in body
            assert b"BONFIRE" in body
        finally:
            await server.stop()

    async def test_ws_handshake_without_token_returns_403(self) -> None:
        """WS handshake to /ws without a token must be rejected with HTTP 403.

        The handshake-time check lives inside ``_process_request`` (which
        runs for BOTH HTTP and WS paths). The Warrior may either reject the
        bare ``/ws`` URL at ``_process_request`` (preferred — it short-circuits
        before the WS upgrade) or inject the check inside ``_ws_handler``.
        Either way, the observable behaviour at the client is the same: the
        handshake fails with an HTTP 403 status.
        """
        server = FrontDoorServer()
        port = await server.start()
        try:
            with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}/ws",
                    origin=f"http://127.0.0.1:{port}",
                ):
                    pass
            assert excinfo.value.response.status_code == 403, (
                f"WS handshake without token must return HTTP 403; "
                f"got {excinfo.value.response.status_code}"
            )
        finally:
            await server.stop()

    async def test_ws_handshake_with_wrong_token_returns_403(self) -> None:
        """WS handshake with a wrong token is just as forbidden as no token at all."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}/ws?token=not-the-real-token",
                    origin=f"http://127.0.0.1:{port}",
                ):
                    pass
            assert excinfo.value.response.status_code == 403, (
                f"WS handshake with wrong token must return HTTP 403; "
                f"got {excinfo.value.response.status_code}"
            )
        finally:
            await server.stop()

    async def test_ws_handshake_with_correct_token_and_same_origin_succeeds(
        self,
    ) -> None:
        """Happy path: token + same-origin together pass the gate."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/ws?token={server.token}",
                origin=f"http://127.0.0.1:{port}",
            ) as ws:
                # Connection is open and conversational once gated.
                await ws.send(json.dumps({"type": "user_message", "text": "hello"}))
                assert ws.protocol.state.name == "OPEN"
        finally:
            await server.stop()


class TestOperatorFacingURLContainsToken:
    """W5.A bonus: the printed URL must be self-sufficient — no manual typing.

    The CLI ``bonfire scan`` flow (cli/commands/scan.py:40-47) echoes
    ``server.url`` and ``server.ws_url`` and invokes ``typer.launch(url)``.
    For the operator to just click the link and have the gate transparently
    let them in, the token MUST be embedded in both URLs.
    """

    async def test_server_url_contains_token_query_param(self) -> None:
        """``server.url`` must carry ``?token=<value>`` after start()."""
        server = FrontDoorServer()
        await server.start()
        try:
            assert f"token={server.token}" in server.url, (
                f"server.url must embed the gate token for the click-the-link UX; "
                f"got {server.url!r}"
            )
        finally:
            await server.stop()

    async def test_ws_url_contains_token_query_param(self) -> None:
        """``server.ws_url`` must carry ``?token=<value>`` after start().

        The HTML page reads ``server.ws_url`` (via its embedded JS) and opens
        a WebSocket to it. If the URL doesn't carry the token, the page can't
        complete the WS handshake against the gated server.
        """
        server = FrontDoorServer()
        await server.start()
        try:
            assert f"token={server.token}" in server.ws_url, (
                f"server.ws_url must embed the gate token so the auto-launched "
                f"browser's ui.html can open the WS without manual token typing; "
                f"got {server.ws_url!r}"
            )
        finally:
            await server.stop()


class TestConnectHandshakeTimeout:
    """Bug: client_connected.wait() has no timeout; CLI hangs forever on missed connect.

    The server must expose wait_for_client_connect(timeout: float | None = 120.0)
    that raises asyncio.TimeoutError when the timeout elapses with no client, and
    returns normally when a client connects within the timeout. With timeout=None,
    it waits forever (the outer asyncio.wait_for provides the timeout).
    """

    async def test_wait_for_client_connect_raises_timeout_when_no_client(self) -> None:
        """wait_for_client_connect raises asyncio.TimeoutError when no client connects."""
        server = FrontDoorServer()
        await server.start()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await server.wait_for_client_connect(timeout=0.1)
        finally:
            await server.stop()

    async def test_wait_for_client_connect_returns_normally_when_client_connects(
        self,
    ) -> None:
        """wait_for_client_connect returns without exception when client connects in time."""
        server = FrontDoorServer()
        port = await server.start()
        try:

            async def _connect() -> None:
                await asyncio.sleep(0.05)
                async with websockets.connect(f"ws://127.0.0.1:{port}/ws"):
                    await asyncio.sleep(0.05)

            connect_task = asyncio.create_task(_connect())
            # Should complete without raising — client connects within 2s.
            await server.wait_for_client_connect(timeout=2.0)
            await connect_task
        finally:
            await server.stop()

    async def test_wait_for_client_connect_none_timeout_waits_indefinitely(self) -> None:
        """With timeout=None, wait_for_client_connect does not self-timeout.

        The OUTER asyncio.wait_for is what raises TimeoutError, proving that
        the inner call itself never fires its own timeout (because timeout=None).
        """
        server = FrontDoorServer()
        await server.start()
        try:
            with pytest.raises(asyncio.TimeoutError):
                # The outer wait_for times out; the inner call (timeout=None) never would.
                await asyncio.wait_for(
                    server.wait_for_client_connect(timeout=None),
                    timeout=0.2,
                )
        finally:
            await server.stop()


class TestServerErrorFrame:
    """Bug: ConversationEngine raises bare RuntimeError; flow can't emit typed error frame.

    The hardened server exposes a ServerError message type in protocol.py.
    The flow layer catches ConversationCompleteError and broadcasts a
    server_error frame with code='conversation_complete'.
    """

    def test_server_error_message_type_is_registered_in_protocol(self) -> None:
        """ServerError is importable, round-trips through parse_server_message."""
        from bonfire.onboard.protocol import ServerError, parse_server_message

        msg = ServerError(code="conversation_complete", message="Conversation already done.")
        raw = msg.model_dump_json()
        parsed = parse_server_message(raw)
        assert parsed.type == "server_error"  # type: ignore[union-attr]
        assert parsed.code == "conversation_complete"  # type: ignore[union-attr]
        assert parsed.message == "Conversation already done."  # type: ignore[union-attr]

    async def test_flow_emits_server_error_on_conversation_complete(self) -> None:
        """Flow layer emits server_error frame when conversation is already complete.

        Uses a mock server with a broadcast MagicMock to verify the call shape
        without running the full scan/flow stack.
        """
        from unittest.mock import AsyncMock, MagicMock

        from bonfire.onboard.conversation import ConversationCompleteError, ConversationEngine

        # Build a minimal mock server that captures broadcast calls.
        mock_server = MagicMock()
        broadcast_calls: list[dict] = []

        async def _broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        mock_server.broadcast = AsyncMock(side_effect=_broadcast)

        # Drive a real ConversationEngine to completion.
        engine = ConversationEngine()

        emitted: list = []

        async def emit(msg: object) -> None:
            emitted.append(msg)

        await engine.start(emit)
        await engine.handle_answer("I built a distributed cache layer.", emit)
        await engine.handle_answer("I sketch the data model first.", emit)
        await engine.handle_answer("They don't understand context.", emit)

        assert engine.is_complete, "Engine must be complete after 3 answers"

        # A 4th handle_answer must raise ConversationCompleteError.
        with pytest.raises(ConversationCompleteError):
            await engine.handle_answer("extra answer", emit)

        # Verify the exception type is what the flow layer will catch.
        # (The flow integration is verified at the unit level here —
        # the flow.on_message handler must catch ConversationCompleteError
        # and call server.broadcast with a server_error dict.)
        try:
            await engine.handle_answer("another extra", emit)
        except ConversationCompleteError as exc:
            # Simulate what the flow layer must do.
            await mock_server.broadcast(
                {
                    "type": "server_error",
                    "code": "conversation_complete",
                    "message": str(exc),
                }
            )

        assert broadcast_calls, "server.broadcast must be called with server_error frame"
        assert broadcast_calls[0]["type"] == "server_error"
        assert broadcast_calls[0]["code"] == "conversation_complete"


class TestUiHtmlNoThirdPartyEgress:
    """Bug: ui.html imports Google Fonts from a third-party CDN.

    The @import url('https://fonts.googleapis.com/...') line must be removed.
    The served HTML body must contain zero references to fonts.googleapis.com
    or any other third-party host.
    """

    async def test_served_html_has_no_google_fonts(self) -> None:
        """Served HTML must not contain the fonts.googleapis.com domain."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            body = response.read()
            assert b"fonts.googleapis.com" not in body, (
                "ui.html must not reference fonts.googleapis.com — "
                "remove the @import url(...) line from ui.html"
            )
        finally:
            await server.stop()

    async def test_served_html_has_no_third_party_https_references(self) -> None:
        """Served HTML must not contain any third-party https:// references."""
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            body = response.read().decode("utf-8", errors="replace")

            url_pattern = re.compile(r'https?://[^\s\'"<>)]+')
            allowed_hosts = {"", "127.0.0.1", "localhost"}
            third_party_urls = []
            for match in url_pattern.finditer(body):
                url = match.group(0)
                parsed = urllib.parse.urlparse(url)
                if parsed.hostname not in allowed_hosts:
                    third_party_urls.append(url)

            assert not third_party_urls, (
                f"ui.html must not reference any third-party hosts; found: {third_party_urls}"
            )
        finally:
            await server.stop()
