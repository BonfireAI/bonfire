"""Bonfire -- AI Build Pipelines for Real Code.

Define agents. Wire stages. Ship quality.

Bonfire is an opinionated AI agent orchestration framework. It runs
pipelines of specialized agents -- researchers, testers, implementers,
reviewers -- each with its own identity, tools, and quality gates.
TDD built in. Code review built in. Your repo, your rules.

Apache-2.0. https://github.com/BonfireAI/bonfire
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("bonfire-ai")
except PackageNotFoundError:
    # Editable / unbuilt fallback — keep in lockstep with pyproject.toml
    __version__ = "0.1.0"
