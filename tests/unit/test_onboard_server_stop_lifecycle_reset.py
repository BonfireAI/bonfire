"""RED tests for ``FrontDoorServer.stop()`` lifecycle-reset symmetry (issue #74).

``start()`` mints fresh per-launch lifecycle state (``_shutdown_event``,
``_client_connected``, ``_had_clients``, the token, the handoff window, the
oversize flag). ``stop()`` historically tore down only the network half — it
cleared ``_server`` and ``_clients`` but left the *latching* lifecycle fields
behind. A ``FrontDoorServer`` that was started, saw a client, and stopped
therefore carried stale latch state forward: a fresh property read after
``stop()`` could observe a set ``shutdown_event``/``client_connected`` and a
``True`` ``_had_clients`` from the *previous* launch.

The contract these tests lock: after ``stop()`` a server behaves like one that
was never started — the lifecycle latches are gone (the event properties raise
the same "unavailable before start()" ``RuntimeError`` they raise on a fresh
instance) and ``_had_clients`` is back to ``False``. A ``start() -> stop() ->
start()`` cycle then yields clean, un-latched state on the second launch.
"""

from __future__ import annotations

import asyncio

import pytest
import websockets

from bonfire.onboard.server import FrontDoorServer


class TestStopResetsLifecycleState:
    """``stop()`` must restore never-started lifecycle state (issue #74)."""

    async def test_stop_clears_shutdown_event_handle(self) -> None:
        """After ``stop()`` the ``shutdown_event`` property raises as on a fresh server."""
        fresh = FrontDoorServer()
        with pytest.raises(RuntimeError):
            _ = fresh.shutdown_event

        server = FrontDoorServer()
        await server.start()
        # Touch the event so it exists and is bound to this loop.
        assert not server.shutdown_event.is_set()
        await server.stop()

        with pytest.raises(RuntimeError):
            _ = server.shutdown_event

    async def test_stop_clears_client_connected_handle(self) -> None:
        """After ``stop()`` the ``client_connected`` property raises as on a fresh server."""
        fresh = FrontDoorServer()
        with pytest.raises(RuntimeError):
            _ = fresh.client_connected

        server = FrontDoorServer()
        await server.start()
        assert not server.client_connected.is_set()
        await server.stop()

        with pytest.raises(RuntimeError):
            _ = server.client_connected

    async def test_stop_resets_had_clients_flag(self) -> None:
        """A connect that latched ``_had_clients`` must not survive ``stop()``."""
        server = FrontDoorServer()
        await server.start()
        async with websockets.connect(server.ws_url):
            pass  # connect + disconnect latches _had_clients and shutdown_event
        # The handler observed at least one client.
        assert server._had_clients is True
        await server.stop()

        assert server._had_clients is False

    async def test_restart_after_client_yields_clean_unlatched_state(self) -> None:
        """``start() -> client -> stop() -> start()`` gives a fresh, un-latched launch."""
        server = FrontDoorServer()
        await server.start()
        async with websockets.connect(server.ws_url):
            pass
        # First launch latched shutdown_event (last client left) and _had_clients.
        await asyncio.sleep(0)  # let the handler's finally run
        assert server._had_clients is True
        await server.stop()

        # Second launch must start clean: no carried-over latch.
        await server.start()
        try:
            assert server._had_clients is False
            assert not server.shutdown_event.is_set()
            assert not server.client_connected.is_set()
        finally:
            await server.stop()

    async def test_stop_before_any_start_is_safe(self) -> None:
        """``stop()`` on a never-started server must not raise and must stay clean."""
        server = FrontDoorServer()
        await server.stop()  # must be a no-op, not an AttributeError

        assert server._had_clients is False
        with pytest.raises(RuntimeError):
            _ = server.shutdown_event
        with pytest.raises(RuntimeError):
            _ = server.client_connected
