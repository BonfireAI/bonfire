"""CLI composition root for the public ``bonfire`` command.

This package is the Typer entry point: the ``[project.scripts]`` mapping
in ``pyproject.toml`` resolves the ``bonfire`` console script through
``bonfire.cli.app:app``, so this ``__init__`` re-exports that single
``app`` symbol for callers and tests.

Individual command implementations live under
:mod:`bonfire.cli.commands` and are wired onto ``app`` from
:mod:`bonfire.cli.app`.
"""

from bonfire.cli.app import app

__all__ = ["app"]
