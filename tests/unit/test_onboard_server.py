"""RED tests for bonfire.onboard.server — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 15 tests per Sage §D6 Row 2. Verbatim v1 port. No innovations (conservative lens).
"""

from __future__ import annotations

import asyncio
import json

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
