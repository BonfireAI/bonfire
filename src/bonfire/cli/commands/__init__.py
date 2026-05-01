# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Per-command Typer modules wired onto :mod:`bonfire.cli.app`.

Each module here owns one top-level ``bonfire`` subcommand. The seven
commands shipping in v0.1 are: ``init``, ``scan``, ``status``,
``resume``, ``handoff``, ``persona``, and ``cost``.

Three additional command modules (``pipeline``, ``project``, ``memory``)
are intentionally deferred per the public-port plan §D-FT A/B/C and
will land in a follow-up wave.
"""
