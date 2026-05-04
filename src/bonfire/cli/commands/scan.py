# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Scan command — launch The Front Door browser onboarding.

Starts the WebSocket server, opens the browser, runs the full
Front Door flow (scan → conversation → config), and blocks until
the last client disconnects or Ctrl-C. Foreground mode only.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from bonfire.onboard.server import FrontDoorServer


async def _run_scan(port: int, no_browser: bool) -> None:
    """Start the Front Door server, run the flow, block until shutdown."""
    server = FrontDoorServer(port=port)
    await server.start()

    url = server.url
    typer.echo(f"Front Door listening at {url}")

    if not no_browser:
        typer.launch(url)

    typer.echo("Waiting for browser connection...")
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
        False, "--no-browser", help="Don't open the browser automatically."
    ),
) -> None:
    """Launch The Front Door — browser-based onboarding scan."""
    try:
        asyncio.run(_run_scan(port=port, no_browser=no_browser))
    except KeyboardInterrupt:
        typer.echo("\nFront Door closed.")
