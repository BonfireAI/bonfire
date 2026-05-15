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
        server = FrontDoorServer()
        port = await server.start()
        try:
            assert server.url == f"http://127.0.0.1:{port}"
            assert server.ws_url == f"ws://127.0.0.1:{port}/ws"
        finally:
            await server.stop()


class TestHTMLServing:
    """HTTP serving of ui.html on GET /."""

    async def test_serves_html_on_root(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            import urllib.request

            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            body = response.read()
            assert response.status == 200
            assert b"<!DOCTYPE html>" in body
            assert b"BONFIRE" in body
        finally:
            await server.stop()

    async def test_html_content_type(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            loop = asyncio.get_event_loop()
            import urllib.request

            response = await loop.run_in_executor(
                None,
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/",
            )
            content_type = response.headers.get("Content-Type", "")
            assert "text/html" in content_type
        finally:
            await server.stop()


class TestWebSocketConnection:
    """WebSocket connection and messaging."""

    async def test_websocket_connects(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                assert ws.protocol.state.name == "OPEN"
        finally:
            await server.stop()

    async def test_send_json_message(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                await ws.send(json.dumps({"type": "user_message", "text": "hello"}))
        finally:
            await server.stop()

    async def test_broadcast_to_clients(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
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
        port = await server.start()
        try:
            async with (
                websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws1,
                websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws2,
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
        port = await server.start()
        try:
            assert server.client_count == 0
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws"):
                await asyncio.sleep(0.05)
                assert server.client_count == 1
        finally:
            await server.stop()

    async def test_client_count_decrements_on_disconnect(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws")
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
        port = await server.start()
        try:
            assert not server.shutdown_event.is_set()
            ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws")
            await asyncio.sleep(0.05)
            await ws.close()
            await asyncio.sleep(0.05)
            assert server.shutdown_event.is_set()
        finally:
            await server.stop()

    async def test_shutdown_event_not_set_while_clients_remain(self) -> None:
        server = FrontDoorServer()
        port = await server.start()
        try:
            ws1 = await websockets.connect(f"ws://127.0.0.1:{port}/ws")
            ws2 = await websockets.connect(f"ws://127.0.0.1:{port}/ws")
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
        port = await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
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
        port = await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
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
        port = await server.start()
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
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
