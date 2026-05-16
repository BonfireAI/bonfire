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
import time
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

# WS server hard limits (W8.L). Pinning ``max_size`` defends the asyncio loop
# from large-frame OOM; the ``websockets`` default of 1 MiB is far above
# anything the onboard chat protocol sends. ``max_queue`` caps per-connection
# backpressure depth so a slow handler can't accumulate frames unbounded.
# Named so a future bump is greppable + the values are testable.
_WS_MAX_FRAME_BYTES = 8192  # 8 KiB per message — onboard JSON is <1 KiB
_WS_MAX_QUEUE_DEPTH = 8  # per-connection inbound backpressure queue depth


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
        # Out-of-band token handoff state. ``GET /handoff`` is single-use and
        # has a 30s deadline. Both fields are minted in ``start()`` so each
        # launch gets a fresh window.
        self._handoff_consumed: bool = False
        self._handoff_deadline: float = 0.0

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
        # Reset single-use flag and mint a fresh 30s deadline for the
        # handoff endpoint. Both are per-launch.
        self._handoff_consumed = False
        self._handoff_deadline = time.monotonic() + 30.0
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
            max_size=_WS_MAX_FRAME_BYTES,
            max_queue=_WS_MAX_QUEUE_DEPTH,
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
        """HTTP URL for the served page — token-FREE.

        The URL passed to ``typer.launch`` (and thus into ``xdg-open``'s argv
        on Linux) MUST NOT carry the token. Same-uid processes can read argv
        from ``/proc/<pid>/cmdline``; a token in argv defeats the whole gate.
        The browser fetches the token via ``GET /handoff`` on page load.
        """
        return f"http://{self._host}:{self._port}/"

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
        """Front Door gate + dispatch.

        Order of checks:

        1. ``Origin`` allow-list — same-origin (or no Origin header at all,
           which signals a non-browser local process) is allowed; anything
           else returns 403. Browsers do NOT enforce CORS on WebSocket
           handshakes, so this check is the only thing standing between a
           cross-origin page during ``bonfire scan`` and the conversation
           engine.

        2. Path routing:
           - ``/`` (and any ``/?...`` query) — serve ``ui.html`` (no token
             gate on the HTTP entry; the gate lives at ``/handoff`` + ``/ws``).
           - ``/handoff`` — single-use token issuance. Origin required;
             30s deadline; flip to 410 after first success.
           - ``/ws`` — token-gated WS upgrade.
           - anything else — 404.

        On success: serve ``ui.html`` for ``/``, return JSON for
        ``/handoff``, and return ``None`` for ``/ws`` so the library
        completes the WS upgrade.
        """
        # 1. Origin allow-list. ``None`` (no Origin header, e.g. Python
        # ``websockets`` client / scripted ``urllib`` driver) is allowed
        # because it cannot originate from a CSWSH page — only same-host
        # local processes can send a no-Origin request. Browser pages
        # always send an Origin. The same rule applies to ``/handoff`` — a
        # same-uid Python attacker can spoof the header trivially, so this
        # is bar-raising, not a strong defense.
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

        # 2. Path routing.
        # 2a. /handoff — single-use, deadline-bounded token issuance.
        if request.path == "/handoff" or request.path.startswith("/handoff?"):
            return self._handle_handoff()

        # 2b. /ws — token-gated WS upgrade.
        if request.path.startswith("/ws"):
            if not self._token_matches(request.path):
                logger.warning(
                    "Front Door rejected WS request without matching token (path=%r)",
                    request.path,
                )
                return Response(
                    403,
                    "Forbidden",
                    Headers({"Content-Type": "text/plain; charset=utf-8"}),
                    b"403 Forbidden: missing or invalid token",
                )
            return None

        # 2c. / and /?... — serve ui.html (token-free).
        if request.path == "/" or request.path.startswith("/?"):
            # Defense-in-depth headers so the served page can't leak the
            # WS token via referrer or be cached by any intermediary.
            return Response(
                200,
                "OK",
                Headers(
                    {
                        "Content-Type": "text/html; charset=utf-8",
                        "Referrer-Policy": "no-referrer",
                        "Cache-Control": "no-store, no-cache",
                    }
                ),
                self._html,
            )

        return Response(404, "Not Found", Headers({}), b"Not Found")

    def _handle_handoff(self) -> Response:
        """``GET /handoff`` — issue the WS token exactly once.

        Guards:

        - **Deadline** — ``time.monotonic() > _handoff_deadline`` → 410 Gone
          even on the first call. Closes long-running-race windows.
        - **Single-use** — after one success, subsequent calls return 410 Gone
          and log a WARNING containing ``"handoff"`` so a race-loss is
          auditable.
        - **Origin** — checked in the caller (``_process_request``) before
          dispatch; mirrors the ``/ws`` rule.

        Success response: 200 + JSON ``{"token": "<value>"}`` with
        ``Referrer-Policy: no-referrer`` and ``Cache-Control: no-store, no-cache``
        so the token can't leak via referrer header or browser/proxy cache.
        """
        # Deadline first — even an unconsumed endpoint past the window is 410.
        if time.monotonic() > self._handoff_deadline:
            logger.warning("Front Door /handoff request after deadline — returning 410 Gone")
            return Response(
                410,
                "Gone",
                Headers({"Content-Type": "text/plain; charset=utf-8"}),
                b"410 Gone: handoff window closed",
            )

        # Single-use atomicity: flip-then-respond. _process_request runs on
        # the asyncio loop thread; the flip is single-threaded.
        if self._handoff_consumed:
            logger.warning(
                "Front Door /handoff already consumed — returning 410 Gone "
                "(possible race; legit browser will fail open)"
            )
            return Response(
                410,
                "Gone",
                Headers({"Content-Type": "text/plain; charset=utf-8"}),
                b"410 Gone: handoff already consumed",
            )

        self._handoff_consumed = True
        # ``self._token`` is guaranteed non-None here because start() mints
        # it before serve() begins accepting requests.
        body = json.dumps({"token": self._token}).encode("utf-8")
        return Response(
            200,
            "OK",
            Headers(
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Referrer-Policy": "no-referrer",
                    "Cache-Control": "no-store, no-cache",
                }
            ),
            body,
        )

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
