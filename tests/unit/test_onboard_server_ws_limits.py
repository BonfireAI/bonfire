"""Tests for Front Door WS server hard limits (W8.L).

Scout 1 M2 finding: the WS server didn't pin ``max_size``, so a 1 MiB JSON
frame could OOM the asyncio loop. ``max_queue`` was also unbounded relative
to onboard chat needs. This module pins both with named constants so a
future bump is greppable.

The limits are intentionally tight for the onboard chat surface
(8 KiB per message, 8-frame per-connection queue). The constants are
exported on ``bonfire.onboard.server`` so the values are testable + the
ceiling change is loud.
"""

from __future__ import annotations

import json

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from bonfire.onboard.server import (
    _WS_MAX_FRAME_BYTES,
    _WS_MAX_QUEUE_DEPTH,
    FrontDoorServer,
)


class TestWSLimitConstants:
    """The hard-limit constants are pinned at the documented values."""

    def test_max_frame_bytes_is_8kib(self) -> None:
        # 8192 = 8 KiB — well above protocol JSON sizes for onboard chat,
        # far below the asyncio-OOM-risk threshold (1 MiB default).
        assert _WS_MAX_FRAME_BYTES == 8192

    def test_max_queue_depth_is_8(self) -> None:
        # 8-frame per-connection backpressure queue depth.
        assert _WS_MAX_QUEUE_DEPTH == 8


class TestWSFrameSizeEnforced:
    """A client sending a frame > _WS_MAX_FRAME_BYTES gets hard-closed."""

    async def test_oversized_frame_closes_connection(self) -> None:
        server = FrontDoorServer()
        await server.start()
        try:
            # Build a JSON message whose serialized form exceeds the cap.
            # 16 KiB of payload text guarantees the wire frame is > 8 KiB.
            oversized = json.dumps({"type": "user_message", "text": "x" * (16 * 1024)})
            assert len(oversized.encode("utf-8")) > _WS_MAX_FRAME_BYTES

            async with websockets.connect(server.ws_url) as ws:
                # The server must close the connection on the oversized frame.
                # Depending on timing, ``send`` may raise (peer closed during
                # send) or a subsequent ``recv`` will raise ``ConnectionClosed``.
                with pytest.raises(ConnectionClosed):
                    await ws.send(oversized)
                    # If send didn't raise, recv definitely will.
                    await ws.recv()
        finally:
            await server.stop()

    async def test_undersized_frame_accepted(self) -> None:
        # Sanity guard: a normal onboard-chat-shaped message stays under
        # the cap and the connection stays open.
        server = FrontDoorServer()
        await server.start()
        try:
            normal = json.dumps({"type": "user_message", "text": "hello"})
            assert len(normal.encode("utf-8")) < _WS_MAX_FRAME_BYTES

            async with websockets.connect(server.ws_url) as ws:
                await ws.send(normal)
                assert ws.protocol.state.name == "OPEN"
        finally:
            await server.stop()
