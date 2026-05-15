# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Front Door WebSocket + HTTP server.

Serves ``ui.html`` on GET ``/`` and accepts WebSocket connections on ``/ws``
for streaming scan events and conversation messages.

Uses ``websockets`` >= 13.0 with the asyncio API.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
from collections.abc import Callable, Coroutine
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlsplit

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
        # The gate token is generated lazily inside start() so each launch
        # mints a fresh value (mirroring the lazy-event-binding pattern):
        # even if a single FrontDoorServer is reused across asyncio.run blocks,
        # a previous-launch URL cannot drive a current-launch session.
        self._token: str | None = None

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
        # Mint a fresh per-launch URL-safe gate token. 16 bytes of entropy
        # (~22 chars of urlsafe-base64) defeats brute-force from same-host
        # processes during the short scan lifetime. Regenerated on every
        # start() so re-using a server instance does NOT re-open the
        # previous launch's CSWSH window.
        self._token = secrets.token_urlsafe(16)
        self._html = _load_html()
        # Origin enforcement happens in ``_process_request`` (rather than via
        # the ``serve(origins=...)`` kwarg) because the allow-list must
        # include the bound port, which isn't known until ``serve`` returns
        # for the random-port case (``port=0``). ``_process_request`` runs
        # AFTER bind and BEFORE the WS upgrade, so it can enforce both the
        # Origin allow-list and the token gate in one place for both HTTP
        # and WS paths.
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

    async def wait_for_client_connect(self, timeout: float | None = 120.0) -> None:
        """Wait for the first WebSocket client. Raises asyncio.TimeoutError on timeout.

        If timeout is None, waits indefinitely.
        """
        event = self.client_connected  # raises if before start()
        if timeout is None:
            await event.wait()
            return
        await asyncio.wait_for(event.wait(), timeout=timeout)

    @property
    def token(self) -> str | None:
        """Per-launch gate token. ``None`` before ``start()``.

        Regenerated on every ``start()`` so a re-used ``FrontDoorServer``
        instance does NOT re-open the previous launch's CSWSH window.
        """
        return self._token

    @property
    def url(self) -> str:
        """HTTP URL for the served page, including the gate token.

        Embeds ``?token=<value>`` so the operator can just click the printed
        link and the gate transparently lets them in. ``self._token`` is
        ``None`` before ``start()`` — the URL is returned with the literal
        ``None`` only in that pre-start window; callers should not rely on
        the value of ``url`` before ``start()``.
        """
        if self._token is None:
            return f"http://{self._host}:{self._port}"
        return f"http://{self._host}:{self._port}/?token={self._token}"

    @property
    def ws_url(self) -> str:
        """WebSocket URL for client connections, including the gate token.

        The HTML page reads this URL via its embedded JS and opens a WS
        with the embedded token — that is how the browser path completes
        the gated handshake without manual token typing.
        """
        if self._token is None:
            return f"ws://{self._host}:{self._port}/ws"
        return f"ws://{self._host}:{self._port}/ws?token={self._token}"

    @property
    def origin(self) -> str:
        """Same-origin allow-list value (host:port only — no token, no path).

        Mirrors the ``Origin`` header a browser stamps onto a request from
        the served ``ui.html``: scheme + host + port. The allow-list lives
        inside ``_process_request``; this property is exposed for callers
        and tests that want to construct same-origin requests explicitly.
        """
        return f"http://{self._host}:{self._port}"

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
        """Front Door gate + dispatch (W5.A).

        Order of checks for both ``/`` (HTTP) and ``/ws`` (WS upgrade):

        1. ``Origin`` allow-list — same-origin (or no Origin header at all,
           which signals a non-browser local process) is allowed; anything
           else returns 403. Browsers do NOT enforce CORS on WebSocket
           handshakes, so this check is the only thing standing between a
           cross-origin page during ``bonfire scan`` and the conversation
           engine.

        2. Token gate — ``?token=<value>`` query parameter must match the
           per-launch token minted in ``start()``. Both ``/`` and ``/ws``
           require it; missing or wrong → 403. ``hmac.compare_digest`` is
           used for the compare to avoid leaking timing information on the
           token value (even though same-host timing leaks are barely
           exploitable, the defense-in-depth cost is one function call).

        On success: serve ``ui.html`` for ``/`` and return ``None`` for
        ``/ws`` so the library completes the WS upgrade.
        """
        # 1. Origin allow-list. ``None`` (no Origin header, e.g. Python
        # ``websockets`` client) is allowed because it cannot originate
        # from a CSWSH page — only same-host local processes can send a
        # no-Origin request. Browser pages always send an Origin.
        origin_header = request.headers.get("Origin")
        if origin_header is not None and origin_header != self.origin:
            logger.warning(
                "Front Door rejected request from disallowed Origin %r (allow=%r)",
                origin_header,
                self.origin,
            )
            return Response(
                403,
                "Forbidden",
                Headers({"Content-Type": "text/plain; charset=utf-8"}),
                b"403 Forbidden: origin not allowed",
            )

        # 2. Path routing + token gate. Token check runs for both ``/``
        # and ``/ws``; any other path is a flat 404.
        if request.path.startswith("/ws") or request.path == "/" or request.path.startswith("/?"):
            if not self._token_matches(request.path):
                logger.warning(
                    "Front Door rejected request without matching token (path=%r)",
                    request.path,
                )
                return Response(
                    403,
                    "Forbidden",
                    Headers({"Content-Type": "text/plain; charset=utf-8"}),
                    b"403 Forbidden: missing or invalid token",
                )
            # Gate passed. Serve HTML for / or hand off to the WS handler.
            if request.path.startswith("/ws"):
                return None
            return Response(
                200,
                "OK",
                Headers({"Content-Type": "text/html; charset=utf-8"}),
                self._html,
            )
        return Response(404, "Not Found", Headers({}), b"Not Found")

    def _token_matches(self, raw_path: str) -> bool:
        """Constant-time check that ``?token=`` in ``raw_path`` matches ``self._token``.

        ``raw_path`` is the value from ``Request.path`` — already URL-encoded
        path + query, e.g. ``"/?token=abc123"`` or ``"/ws?token=abc123"``.
        Returns ``False`` if the token is missing, mismatched, or if the
        server has no token yet (``start()`` not called — defensive; should
        not happen because ``_process_request`` only runs after ``serve``).
        """
        if self._token is None:
            return False
        query = urlsplit(raw_path).query
        # parse_qs returns ``{"token": ["abc123"]}`` for the happy case and
        # ``{}`` if the parameter is absent.
        params = parse_qs(query, keep_blank_values=True)
        candidate = params.get("token", [""])[0]
        return hmac.compare_digest(candidate, self._token)

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
