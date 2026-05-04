# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Bonfire -- AI Build Pipelines for Real Code.

Define agents. Wire stages. Ship quality.

Bonfire is an opinionated AI agent orchestration framework. It runs
pipelines of specialized agents -- researchers, testers, implementers,
reviewers -- each with its own identity, tools, and quality gates.
TDD built in. Code review built in. Your repo, your rules.

Apache-2.0. https://github.com/BonfireAI/bonfire

Extension Surface
-----------------

Bonfire's pluggable architecture exposes four protocols and two
supporting value types. Code never imports them from this root --
the canonical module is ``bonfire.protocols``.

The four protocols:

* ``AgentBackend`` -- dispatch backend (SDK, Pydantic-AI, custom).
* ``VaultBackend`` -- knowledge vault storage.
* ``QualityGate`` -- pass/fail evaluation between stages.
* ``StageHandler`` -- custom stage logic.

The two supporting value types:

* ``DispatchOptions`` -- options envelope passed to AgentBackend.execute.
* ``VaultEntry`` -- record type for VaultBackend store/query.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("bonfire-ai")
except PackageNotFoundError:
    # Editable / unbuilt fallback — keep in lockstep with pyproject.toml
    __version__ = "0.1.0a1"
