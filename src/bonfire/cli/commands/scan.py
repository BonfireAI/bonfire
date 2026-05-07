# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Scan command — launch The Front Door onboarding.

Starts the WebSocket server, optionally launches a browser, runs the full
Front Door flow (scan → conversation → config), and blocks until the last
client disconnects or Ctrl-C. Foreground mode only.

The flow is driven by any WebSocket client connecting to ``/ws`` — the
auto-launched browser is one such client, but a scripted WS driver
(``websocat``, an external orchestrator, or another agent) works the same
way. ``--no-browser`` only suppresses the browser auto-launch; the WS
server still binds and waits for a client.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from bonfire.onboard.server import FrontDoorServer


async def _run_scan(port: int, no_browser: bool) -> None:
    """Start the Front Door server, run the flow, block until shutdown.

    The flow is driven by any WebSocket client connecting to ``/ws``. With
    ``no_browser=False`` the default browser is auto-launched; with
    ``no_browser=True`` the operator (or a scripted driver) is expected to
    connect a client to ``server.ws_url`` manually. Either way, the server
    blocks on ``server.client_connected.wait()`` until the first client
    arrives.
    """
    server = FrontDoorServer(port=port)
    await server.start()

    url = server.url
    typer.echo(f"Front Door listening at {url}")

    if not no_browser:
        typer.launch(url)
        typer.echo("Waiting for browser connection...")
    else:
        typer.echo(f"Waiting for client connection at {server.ws_url}")
    await server.client_connected.wait()

    try:
        from bonfire.onboard.flow import run_front_door

        config_path = await run_front_door(server, Path.cwd())
        typer.echo(f"Config written to {config_path}")
        # Block until last client disconnects or Ctrl-C
        await server.shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


def scan(
    port: int = typer.Option(0, "--port", "-p", help="Port to bind (0 = random)."),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help=(
            "Suppress browser auto-launch only. The WebSocket server still "
            "binds and waits for any client (browser, websocat, or scripted "
            "WS driver) to connect to /ws."
        ),
    ),
) -> None:
    """Launch The Front Door — WS-driven onboarding scan."""
    try:
        asyncio.run(_run_scan(port=port, no_browser=no_browser))
    except KeyboardInterrupt:
        typer.echo("\nFront Door closed.")
