# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The one Bonfire failure vocabulary — base error + taxonomy (ADR-002).

This module is import-cycle-free: it imports nothing from ``bonfire.*`` so
every other module is free to import *it*. The base ``BonfireError`` pins two
cross-cutting contracts the runner depends on:

- ``is_terminal`` (ClassVar) — whether a failure is non-recoverable. The
  derived ``retryable`` property is simply ``not is_terminal``.
- ``code`` (ClassVar) — a stable wire-string used to source the terminal set.
"""

from __future__ import annotations

from typing import ClassVar


class BonfireError(Exception):
    """Base for every operational/expected failure in Bonfire (the one vocabulary)."""

    is_terminal: ClassVar[bool] = False
    code: ClassVar[str] = "bonfire_error"

    def __init__(self, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, object] = context or {}

    @property
    def retryable(self) -> bool:
        return not self.is_terminal


# ---------------------------------------------------------------------------
# Terminal failures — non-recoverable (is_terminal = True)
# ---------------------------------------------------------------------------


class ConfigError(BonfireError):
    """Configuration is invalid or missing; the run cannot proceed."""

    is_terminal = True
    code = "config"


class AgentError(BonfireError):
    """An agent reported a non-recoverable error."""

    is_terminal = True
    code = "AgentError"


class RateLimitError(BonfireError):
    """The API rejected a request for exceeding a rate limit."""

    is_terminal = True
    code = "RateLimitError"


class CLINotFoundError(BonfireError):
    """The required CLI binary could not be located."""

    is_terminal = True
    code = "CLINotFoundError"


class ExecutorError(BonfireError):
    """The execution backend failed in a non-recoverable way."""

    is_terminal = True
    code = "executor"


# ---------------------------------------------------------------------------
# Operational failures — recoverable / retryable (is_terminal = False)
# ---------------------------------------------------------------------------


class RetrievalError(BonfireError):
    """A knowledge/retrieval lookup failed transiently."""

    is_terminal = False
    code = "retrieval"


class SubprocessError(BonfireError):
    """A spawned subprocess failed."""

    is_terminal = False
    code = "subprocess"


class TimeoutError_(BonfireError):
    """An operation exceeded its time budget."""

    is_terminal = False
    code = "timeout"


class NetworkError(BonfireError):
    """A network operation failed transiently."""

    is_terminal = False
    code = "network"


# ---------------------------------------------------------------------------
# Data / boundary failures
# ---------------------------------------------------------------------------


class ValidationError(BonfireError):
    """Input data failed a validation check at a boundary."""

    is_terminal = False
    code = "validation"


class SchemaError(ValidationError):
    """Data violated a declared schema."""

    is_terminal = False
    code = "schema"


class IsolationError(BonfireError):
    """An isolation boundary (e.g. worktree path guard) was violated."""

    is_terminal = False
    code = "isolation"
