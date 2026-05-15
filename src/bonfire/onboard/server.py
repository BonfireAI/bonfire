# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Front Door WebSocket + HTTP server.

Serves ``ui.html`` on GET ``/`` and accepts WebSocket connections on ``/ws``
for streaming scan events and conversation messages.

Uses ``websockets`` >= 13.0 with the asyncio API.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from importlib import resources
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

__all__ = ["FrontDoorServer"]

logger = logging.getLogger(__name__)

MessageCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


def _load_html() -> bytes:
    """Load ui.html from package data."""
    ref = resources.files("bonfire.onboard").joinpath("ui.html")
    return ref.read_bytes()


class FrontDoorServer:
    """Async WebSocket server for The Front Door.

    Serves ``ui.html`` on HTTP GET ``/`` and accepts WebSocket connections
    on ``/ws``. Tracks connected clients and supports broadcasting JSON
    messages to all of them.

    Parameters
    ----------
    host:
        Bind address. Defaults to ``127.0.0.1`` (local only).
    port:
        Bind port. ``0`` means pick a random available port.
    on_message:
        Async callback invoked for each incoming WebSocket JSON message.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        on_message: MessageCallback | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._on_message = on_message
        self._server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._html: bytes = b""
        # Created lazily in start() — an asyncio.Event binds to the loop
        # current at construction time, so eager creation in __init__ would
        # break reuse of a server instance across separate event loops.
        self._shutdown_event: asyncio.Event | None = None
        self._client_connected: asyncio.Event | None = None
        self._had_clients: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def shutdown_event(self) -> asyncio.Event:
        """Set when the last WebSocket client disconnects (after at least one connected)."""
        if self._shutdown_event is None:
            raise RuntimeError("shutdown_event is unavailable before start()")
        return self._shutdown_event

    @property
    def client_connected(self) -> asyncio.Event:
        """Set when the first WebSocket client connects."""
        if self._client_connected is None:
            raise RuntimeError("client_connected is unavailable before start()")
        return self._client_connected

    async def start(self) -> int:
        """Start the server and return the bound port."""
        # Create the events here so they bind to the loop running start() —
        # this also rebinds them when a server instance is reused across loops.
        self._shutdown_event = asyncio.Event()
        self._client_connected = asyncio.Event()
        self._html = _load_html()
        self._server = await serve(
            self._ws_handler,
            self._host,
            self._port,
            process_request=self._process_request,
        )
        sock = next(iter(self._server.sockets))
        self._port = sock.getsockname()[1]
        logger.info("Front Door listening on %s:%d", self._host, self._port)
        return self._port

    async def stop(self) -> None:
        """Gracefully shut down the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._clients.clear()

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to all connected WebSocket clients."""
        if not self._clients:
            return
        raw = json.dumps(message)
        # Snapshot to avoid RuntimeError if _clients is modified during send
        clients = set(self._clients)
        await asyncio.gather(
            *(client.send(raw) for client in clients),
            return_exceptions=True,
        )

    @property
    def url(self) -> str:
        """HTTP URL for the served page."""
        return f"http://{self._host}:{self._port}"

    @property
    def ws_url(self) -> str:
        """WebSocket URL for client connections."""
        return f"ws://{self._host}:{self._port}/ws"

    @property
    def on_message(self) -> MessageCallback | None:
        """Current message callback, or None."""
        return self._on_message

    @on_message.setter
    def on_message(self, callback: MessageCallback | None) -> None:
        self._on_message = callback

    @property
    def client_count(self) -> int:
        """Number of currently connected WebSocket clients."""
        return len(self._clients)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _process_request(
        self,
        connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        """Serve HTML on GET /, pass /ws through to WebSocket handler."""
        if request.path == "/":
            return Response(
                200,
                "OK",
                Headers({"Content-Type": "text/html; charset=utf-8"}),
                self._html,
            )
        if request.path != "/ws":
            return Response(404, "Not Found", Headers({}), b"Not Found")
        return None

    async def _ws_handler(self, websocket: ServerConnection) -> None:
        """Handle a single WebSocket connection lifecycle."""
        # _ws_handler only runs after start(), so the events are set.
        assert self._client_connected is not None
        assert self._shutdown_event is not None
        self._clients.add(websocket)
        self._had_clients = True
        self._client_connected.set()
        self._shutdown_event.clear()
        try:
            async for raw in websocket:
                if not isinstance(raw, str):
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON WebSocket message, ignoring")
                    continue
                if self._on_message is not None:
                    try:
                        await self._on_message(data)
                    except Exception:
                        logger.exception("on_message callback failed")
        finally:
            self._clients.discard(websocket)
            if self._had_clients and not self._clients:
                self._shutdown_event.set()
