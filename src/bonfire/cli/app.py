# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Bonfire CLI — Typer application entry point.

Command modules are imported lazily on first invocation. The CLI's
discovery surface (``bonfire --help``) is preserved by registering
thin shim functions whose signatures mirror the real implementations;
the heavy command-module imports happen inside the shim body.

The ``scan`` and ``cost`` subcommands additionally have their command
modules loaded via Typer's Click group on subcommand resolution
(``bonfire scan --help``, ``bonfire scan ...``, ``bonfire cost ...``),
so the heavy deps (``websockets``/``onboard.server`` and
``cost.analyzer``) load when the user actually pokes at those
subcommands but stay out of ``bonfire --version`` and ``bonfire --help``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

import click
import typer
from typer.core import TyperGroup

from bonfire import __version__

if TYPE_CHECKING:
    from collections.abc import Callable

# Bonfire ships with Falcor as the companion persona; users can swap
# via `bonfire persona set <name>`. The `default` and `minimal` builtins
# remain available as user-selectable alternates.
_DEFAULT_PERSONA = "falcor"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"bonfire {__version__}")
        raise typer.Exit(0)


# ---------------------------------------------------------------------------
# Lazy command-module loading via a custom Click group.
#
# ``LazyLoadingGroup.get_command`` imports the named module before
# delegating to the registered subcommand. This makes
# ``bonfire scan --help`` (and any other interaction that resolves the
# ``scan`` subcommand) trigger the eager imports inside
# ``bonfire.cli.commands.scan`` — namely ``bonfire.onboard.server`` —
# while keeping ``bonfire --version`` and ``bonfire --help``
# clean of those deps.
#
# ``format_commands`` is overridden to use cached short_help strings
# rather than calling ``get_command`` for each subcommand, so
# ``bonfire --help`` does NOT walk the lazy-load side effects.
# ---------------------------------------------------------------------------


class LazyLoadingGroup(TyperGroup):
    """Typer group that imports a command's backing module on resolution."""

    #: Mapping from subcommand-name to the module path whose import triggers
    #: the subcommand's heavyweight transitive deps.
    _lazy_module_paths: dict[str, str] = {}

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        module_path = self._lazy_module_paths.get(cmd_name)
        if module_path is not None:
            # Importing the module is the side-effect we want — it pulls
            # the subcommand's transitive deps (e.g. onboard.server,
            # cost.analyzer) into sys.modules.
            import_module(module_path)
        return super().get_command(ctx, cmd_name)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Render the subcommand listing without resolving lazy commands.

        Click's default ``format_commands`` calls ``get_command`` for
        every subcommand to harvest short_help. That would defeat
        lazy-load purposes by importing every command on
        ``bonfire --help``. Iterate the already-registered commands
        directly instead — Typer has populated each with its
        short_help at registration time.
        """
        commands: list[tuple[str, click.Command]] = []
        for subcommand_name in self.list_commands(ctx):
            # Pull from ``self.commands`` directly; never call get_command
            # (which triggers lazy imports).
            cmd = self.commands.get(subcommand_name)
            if cmd is None:
                continue
            if cmd.hidden:
                continue
            commands.append((subcommand_name, cmd))

        if not commands:
            return

        with formatter.section("Commands"):
            rows = [
                (subcommand_name, cmd.get_short_help_str(limit=80))
                for subcommand_name, cmd in commands
            ]
            formatter.write_dl(rows)


app = typer.Typer(
    name="bonfire",
    help="Bonfire — AI agent orchestration framework.",
    cls=LazyLoadingGroup,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    persona: str = typer.Option(
        _DEFAULT_PERSONA,
        "--persona",
        help="Persona for CLI output formatting.",
    ),
) -> None:
    """Bonfire — AI agent orchestration framework."""
    ctx.ensure_object(dict)
    ctx.obj["persona"] = persona


# ---------------------------------------------------------------------------
# Top-level commands — thin shims that defer heavy imports to first call.
#
# Shims keep the discovery surface stable (``bonfire --help`` lists each
# command with its right docstring + signature) while keeping
# ``import bonfire.cli.app`` free of the command modules' transitive
# deps.
# ---------------------------------------------------------------------------


def _lazy_run(module_path: str, attribute: str) -> Callable[..., None]:
    """Build a shim that imports *module_path* and forwards to *attribute*."""

    def _shim(**kwargs: object) -> None:
        mod = import_module(module_path)
        return getattr(mod, attribute)(**kwargs)

    return _shim


@app.command("init")
def init(
    project_dir: str = typer.Argument(".", help="Directory to initialize."),
) -> None:
    """Initialize a new Bonfire project."""
    _lazy_run("bonfire.cli.commands.init", "init")(project_dir=project_dir)


@app.command("scan")
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
    conversation_timeout: float = typer.Option(
        # ``-1.0`` is a sentinel meaning "user did not pass the flag"; the
        # library default (``DEFAULT_CONVERSATION_TIMEOUT`` = 300s) governs
        # in that case. ``show_default=False`` hides Typer's auto-generated
        # ``[default: -1.0]`` so the help text below stays the single
        # source of truth for the user-visible default.
        -1.0,
        "--conversation-timeout",
        help=(
            "Maximum seconds to wait for the onboarding conversation to "
            "complete before timing out (default: 300). Pass 0 to disable."
        ),
        min=-1.0,
        show_default=False,
    ),
) -> None:
    """Launch The Front Door — WS-driven onboarding scan."""
    # Sentinel default ``-1.0`` means "user did not pass the flag" — we
    # forward only the user-set values to the inner scan callable so the
    # library's documented default (``DEFAULT_CONVERSATION_TIMEOUT``)
    # governs untouched invocations. ``0`` is the documented opt-out
    # value and is forwarded as ``None`` (wait indefinitely); positive
    # numbers flow through verbatim.
    scan_kwargs: dict[str, object] = {"port": port, "no_browser": no_browser}
    if conversation_timeout >= 0:
        scan_kwargs["conversation_timeout"] = (
            conversation_timeout if conversation_timeout > 0 else None
        )
    _lazy_run("bonfire.cli.commands.scan", "scan")(**scan_kwargs)


@app.command("status", help="(stub -- implementation lands in 0.1.x)")
def status() -> None:
    """Show current Bonfire session status (stub -- implementation lands in 0.1.x)."""
    _lazy_run("bonfire.cli.commands.status", "status")()


@app.command("resume", help="(stub -- implementation lands in 0.1.x)")
def resume() -> None:
    """Resume a previous Bonfire session (stub -- implementation lands in 0.1.x)."""
    _lazy_run("bonfire.cli.commands.resume", "resume")()


@app.command("handoff", help="(stub -- implementation lands in 0.1.x)")
def handoff() -> None:
    """Generate a session handoff document (stub -- implementation lands in 0.1.x)."""
    _lazy_run("bonfire.cli.commands.handoff", "handoff")()


# ---------------------------------------------------------------------------
# Subcommand groups — built locally so ``bonfire --help`` lists the names
# without importing the underlying command modules. Each subcommand body
# defers the heavy import to first invocation.
# ---------------------------------------------------------------------------

persona_app = typer.Typer(name="persona", help="Discover and configure CLI personas.")


@persona_app.command("list")
def _persona_list() -> None:
    """List available personas."""
    _lazy_run("bonfire.cli.commands.persona", "persona_list")()


@persona_app.command("set")
def _persona_set(
    name: str = typer.Argument(..., help="Persona name to activate."),
) -> None:
    """Set the active persona in bonfire.toml."""
    _lazy_run("bonfire.cli.commands.persona", "persona_set")(name=name)


app.add_typer(persona_app, name="persona")


cost_app = typer.Typer(name="cost", help="View build cost analytics.")


@cost_app.callback(invoke_without_command=True)
def _cost_summary(ctx: typer.Context) -> None:
    """Show cumulative cost and recent sessions."""
    if ctx.invoked_subcommand is not None:
        return
    from bonfire.cli.commands.cost import cost_summary as _impl

    _impl(ctx)


@cost_app.command("session")
def _cost_session(
    session_id: str = typer.Argument(..., help="Session ID to inspect"),
) -> None:
    """Show per-agent cost breakdown for a session."""
    _lazy_run("bonfire.cli.commands.cost", "cost_session")(session_id=session_id)


@cost_app.command("agents")
def _cost_agents() -> None:
    """Show cumulative per-agent costs."""
    _lazy_run("bonfire.cli.commands.cost", "cost_agents")()


@cost_app.command("export")
def _cost_export() -> None:
    """Export full ledger as JSON array to stdout."""
    _lazy_run("bonfire.cli.commands.cost", "cost_export")()


app.add_typer(cost_app, name="cost")


# Register lazy module paths for the parent ``app``'s Click group: when
# the user resolves these subcommands at the parent level (e.g.
# ``bonfire scan --help``), the underlying module's transitive deps
# load. ``bonfire --help`` (which calls ``format_commands`` on the
# parent group) does NOT trigger these — see ``LazyLoadingGroup``.
LazyLoadingGroup._lazy_module_paths = {
    "scan": "bonfire.cli.commands.scan",
    "cost": "bonfire.cli.commands.cost",
}
