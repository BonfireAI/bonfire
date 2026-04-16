"""bonfire-ai command-line interface.

Pre-release stub for 0.0.0a1. This version exists to reserve the PyPI
name and does not yet implement any functionality. Real commands arrive
at v0.1.0.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="bonfire",
    help="bonfire-ai — pre-release name reservation.",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Print the pre-release notice."""
    if ctx.invoked_subcommand is not None:
        return

    typer.echo(
        "bonfire-ai 0.0.0a1 — pre-release name reservation.\n"
        "\n"
        "This version has no functionality. It exists to reserve the PyPI\n"
        "name ahead of the v0.1.0 release.\n"
        "\n"
        "Track progress:  https://github.com/BonfireAI/bonfire"
    )


if __name__ == "__main__":
    app()
