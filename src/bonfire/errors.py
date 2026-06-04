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

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator

    from bonfire.models.envelope import ErrorDetail


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


# ---------------------------------------------------------------------------
# Verdict failures — pre-flight gate refusals and baseline divergence (terminal)
# ---------------------------------------------------------------------------


class GateError(BonfireError):
    """A pre-flight gate refused to proceed — a verification verdict.

    Distinct from input ``ValidationError``: a gate refusal means a pre-dispatch
    check (tree hygiene, base verification) blocked the operation. Remediation is
    to *fix the flagged condition and re-run the gate*, not to correct caller
    input. Terminal for the current attempt (no auto-retry).
    """

    is_terminal = True
    code = "gate"


class DriftError(BonfireError):
    """A declared baseline diverged from runtime — a divergence verdict.

    Distinct from a static ``ConfigError`` load failure or an ``IsolationError``
    boundary cross: a drift means an expected baseline (cwd, permission matrix)
    no longer matches runtime. Remediation is to *re-sync to the baseline /
    investigate the divergence*. Terminal — the run halts until reconciled.
    """

    is_terminal = True
    code = "drift"


# ---------------------------------------------------------------------------
# Containment helper — never-raise shells capture failure as ErrorDetail
# ---------------------------------------------------------------------------


class _ErrorBox:
    """Mutable carrier for a captured :class:`ErrorDetail`.

    The :func:`contain_as_error` context manager yields one of these so the
    caller can read ``box.error`` *after* the ``with`` block and decide how
    to surface the failure (build a FAILED envelope, log, etc.). The box is
    ``None`` when the body completed without an ordinary exception.
    """

    __slots__ = ("error",)

    def __init__(self) -> None:
        self.error: ErrorDetail | None = None


@contextmanager
def contain_as_error(stage_name: str | None = None) -> Iterator[_ErrorBox]:
    """Run a never-raise shell body, capturing failure as a structured detail.

    Yields an :class:`_ErrorBox`. On an ordinary ``Exception`` the box's
    ``error`` is set to an :class:`~bonfire.models.envelope.ErrorDetail`
    built via ``ErrorDetail.from_exception`` *inside* the ``except`` block,
    so the traceback is live (never the ``"NoneType: None"`` sentinel). The
    exception is then contained (not re-raised) — the caller inspects
    ``box.error`` and builds its own failure result, preserving any
    verdict-before-side-effect ordering the caller owns.

    ``asyncio.CancelledError`` is **re-raised**, never captured: cancellation
    must surface so pipeline orchestration can act on it.

    why: this is the single, shared containment construct named in the
    Elegance Law — every CandyFactory never-raise shell speaks failure in
    the one typed, self-describing vocabulary.
    """
    # Deferred import keeps this module import-cycle-free (it imports nothing
    # from ``bonfire.*`` at module load; ``ErrorDetail`` is pulled in lazily).
    from bonfire.models.envelope import ErrorDetail

    box = _ErrorBox()
    try:
        yield box
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — containment shell by design
        box.error = ErrorDetail.from_exception(exc, stage_name=stage_name)
