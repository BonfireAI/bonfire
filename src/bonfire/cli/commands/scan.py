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

from bonfire.onboard.config_generator import _is_init_stub
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
    try:
        await server.wait_for_client_connect(timeout=120.0)
    except TimeoutError:
        typer.echo(
            "No client connected within 120s; aborting. For headless contexts, "
            "use --no-browser and run a WebSocket driver (e.g. websocat) against "
            f"{server.ws_url}",
            err=True,
        )
        await server.stop()
        raise typer.Exit(code=1)
    except TypeError:
        # wait_for_client_connect is not awaitable (legacy mock or test double).
        # Fall back to a direct event wait when the method is not a coroutine.
        await server.client_connected.wait()

    try:
        from bonfire.onboard.flow import run_front_door

        config_path = await run_front_door(server, Path.cwd())
        typer.echo(f"Config written to {config_path}")
        # Block until last client disconnects or Ctrl-C
        await server.shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    except FileExistsError as exc:
        # TOCTOU: a concurrent process created ``bonfire.toml`` between
        # the CLI's pre-flow ``Path.exists()`` check and ``write_config``
        # inside ``run_front_door``. Surface the same actionable message
        # the pre-flow guard prints, exit non-zero cleanly. Without this
        # the user would see a raw Python traceback. ``server.stop`` is
        # idempotent and runs in the ``finally`` below.
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
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
    # Fail fast — before starting the Front Door server / browser dance —
    # if bonfire.toml already exists AND is not the exact init stub. A
    # user with a hand-tuned config must not silently lose it; tell them
    # how to recover. Mirrors the existing guard in ``bonfire init``.
    # ``write_config`` also consults ``_is_init_stub`` as a
    # defense-in-depth check; this early exit spares the user the
    # conversation flow when the outcome is doomed.
    #
    # The byte-for-byte stub from ``bonfire init`` is treated as
    # "absent" — that lets the README quickstart ``init && scan`` compose
    # without forcing the user to delete the stub by hand. The shared
    # ``_is_init_stub`` predicate is the single source of truth so this
    # check and ``write_config`` cannot drift.
    toml_path = Path.cwd() / "bonfire.toml"
    # is_symlink() MUST be checked before exists(). Path.exists() follows
    # symlinks, so a dangling symlink to an attacker-controlled target
    # (e.g. ``bonfire.toml -> ~/.ssh/authorized_keys``) would satisfy
    # ``exists() == False`` and let the write path open the symlink target
    # in write+truncate mode — an arbitrary-write primitive. Refuse any
    # symlink (dangling, live, or looping) with a message that names the
    # symlink case explicitly so the user can distinguish it from a normal
    # collision in logs.
    if toml_path.is_symlink():
        typer.echo(
            f"bonfire.toml at {toml_path} is a symlink. Refusing to follow "
            "or overwrite a symlinked config. Remove the symlink and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)
    # The byte-for-byte stub from ``bonfire init`` is treated as "absent" so
    # the README quickstart ``init && scan`` composes; ``_is_init_stub`` is
    # the shared predicate that both this guard and ``write_config`` consult.
    if toml_path.exists() and not _is_init_stub(toml_path):
        typer.echo(
            f"bonfire.toml already exists at {toml_path}. Refusing to "
            "overwrite. Remove or move the existing file and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        asyncio.run(_run_scan(port=port, no_browser=no_browser))
    except KeyboardInterrupt:
        typer.echo("\nFront Door closed.")
