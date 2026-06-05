# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Agent execution with retry, timeout, and event emission.

The dispatch runner sits between the pipeline engine and agent backends.
It wraps every ``backend.execute()`` call with:

- Retry with exponential backoff for infrastructure AND transient agent failures.
- Per-attempt timeout enforcement via ``asyncio.timeout``.
- Wall-clock duration and cost tracking across all attempts.
- Event emission (started, completed, failed, retry) through an optional bus.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import TYPE_CHECKING

from bonfire import errors as errors_module
from bonfire.dispatch.result import DispatchResult
from bonfire.errors import BonfireError
from bonfire.models.envelope import ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    DispatchCompleted,
    DispatchFailed,
    DispatchRetry,
    DispatchStarted,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus
    from bonfire.models.envelope import Envelope
    from bonfire.protocols import AgentBackend, DispatchOptions

# Terminality is sourced from the one typed failure vocabulary, not a
# duplicated string-set: each BonfireError subclass declares its own
# ``is_terminal``. We index the taxonomy by its stable wire ``code`` so a
# FAILED envelope's ``error_type`` string resolves back to the typed class
# that owns the retry decision.
_ERROR_CODE_TO_CLASS: dict[str, type[BonfireError]] = {
    cls.code: cls
    for _, cls in inspect.getmembers(errors_module, inspect.isclass)
    if issubclass(cls, BonfireError) and cls is not BonfireError
}

# Codes that are *taxonomy*-terminal but NOT *dispatch*-terminal.
#
# ``gate`` (GateError) and ``drift`` (DriftError) carry ``is_terminal = True``
# in the typed vocabulary, but they are never raised inside the agent-backend
# dispatch FAILED path this runner retries — they belong to pipeline-gate and
# drift-detection surfaces. The dispatch-terminal set is deliberately the five
# backend-originating codes
# ``{AgentError, RateLimitError, config, CLINotFoundError, executor}``; widening
# it to seven by reflecting the whole taxonomy would silently retire retries
# for failures that never reach here. This exclusion is a runner-local scope
# decision, NOT a taxonomy change — the typed classes stay terminal everywhere
# else. Taxonomy growth remains Wizard-gated.
_NON_DISPATCH_TERMINAL_CODES = frozenset({"gate", "drift"})


def _is_terminal_error_type(error_type: str) -> bool:
    """Whether a FAILED envelope's ``error_type`` is dispatch-terminal (no retry).

    Reads the typed vocabulary: resolve the wire string back to its
    ``BonfireError`` subclass and consult ``is_terminal``. An unrecognized
    ``error_type`` (no taxonomy entry) is treated as retryable — the safer
    default that preserves the previous behavior. Codes that are
    taxonomy-terminal but never surface in a dispatch FAILED envelope
    (see ``_NON_DISPATCH_TERMINAL_CODES``) stay retryable here so the
    effective dispatch-terminal set is exactly the five backend codes.
    """
    if error_type in _NON_DISPATCH_TERMINAL_CODES:
        return False
    cls = _ERROR_CODE_TO_CLASS.get(error_type)
    if cls is None:
        return False
    return cls.is_terminal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _emit(bus: EventBus | None, event: BonfireEvent) -> None:
    """Emit *event* on *bus* if the bus exists. No-op otherwise."""
    if bus is not None:
        await bus.emit(event)


async def _attempt_once(
    backend: AgentBackend,
    envelope: Envelope,
    options: DispatchOptions,
    *,
    timeout_seconds: float | None,
) -> Envelope:
    """Execute a single backend call, optionally wrapped in a timeout.

    Raises on infrastructure failure or timeout — the caller decides
    whether to retry.
    """
    if timeout_seconds is not None:
        async with asyncio.timeout(timeout_seconds):
            return await backend.execute(envelope, options=options)
    return await backend.execute(envelope, options=options)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_with_retry(
    backend: AgentBackend,
    envelope: Envelope,
    options: DispatchOptions,
    *,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    timeout_seconds: float | None = None,
    event_bus: EventBus | None = None,
) -> DispatchResult:
    """Execute an agent dispatch with retry, timeout, and event tracking.

    Returns a :class:`DispatchResult` — **never raises**.

    Retry policy:
        - Infrastructure failures (exceptions) trigger a retry with
          exponential backoff: ``retry_delay * 2 ** attempt_index``.
        - FAILED envelopes with retryable error types (subprocess crash,
          timeout) also trigger retry. Terminal errors (rate limit,
          config, CLI not found) return immediately.
    """
    session_id = envelope.envelope_id
    agent_name = envelope.agent_name

    await _emit(
        event_bus,
        DispatchStarted(
            session_id=session_id,
            sequence=0,
            agent_name=agent_name,
            model=options.model,
        ),
    )

    start = time.monotonic()
    last_error_msg = ""
    last_exception_type = ""
    cumulative_cost = 0.0

    for attempt in range(max_retries + 1):
        try:
            result_env = await _attempt_once(
                backend, envelope, options, timeout_seconds=timeout_seconds
            )
            cumulative_cost += result_env.cost_usd

            if result_env.status == TaskStatus.FAILED:
                error_type = result_env.error.error_type if result_env.error else ""
                last_error_msg = result_env.error.message if result_env.error else "unknown"

                # Terminal errors: return immediately, no retry.
                if _is_terminal_error_type(error_type):
                    duration = time.monotonic() - start
                    await _emit(
                        event_bus,
                        DispatchFailed(
                            session_id=session_id,
                            sequence=0,
                            agent_name=agent_name,
                            error_message=last_error_msg,
                            cost_usd=cumulative_cost,
                        ),
                    )
                    return DispatchResult(
                        envelope=result_env,
                        duration_seconds=duration,
                        retries=attempt,
                        cost_usd=cumulative_cost,
                    )

                # Retryable failure: backoff and try again if attempts remain.
                if attempt < max_retries:
                    await _emit(
                        event_bus,
                        DispatchRetry(
                            session_id=session_id,
                            sequence=0,
                            agent_name=agent_name,
                            attempt=attempt + 1,
                            reason=f"[{error_type}] {last_error_msg}",
                        ),
                    )
                    delay = retry_delay * (2**attempt)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue

                # Retries exhausted on a FAILED envelope.
                duration = time.monotonic() - start
                await _emit(
                    event_bus,
                    DispatchFailed(
                        session_id=session_id,
                        sequence=0,
                        agent_name=agent_name,
                        error_message=last_error_msg,
                        cost_usd=cumulative_cost,
                    ),
                )
                return DispatchResult(
                    envelope=result_env,
                    duration_seconds=duration,
                    retries=attempt,
                    cost_usd=cumulative_cost,
                )

            # Success path.
            duration = time.monotonic() - start
            await _emit(
                event_bus,
                DispatchCompleted(
                    session_id=session_id,
                    sequence=0,
                    agent_name=agent_name,
                    cost_usd=cumulative_cost,
                    duration_seconds=duration,
                    model=options.model,
                ),
            )
            return DispatchResult(
                envelope=result_env,
                duration_seconds=duration,
                retries=attempt,
                cost_usd=cumulative_cost,
            )

        except Exception as exc:  # noqa: BLE001
            last_error_msg = str(exc)
            last_exception_type = type(exc).__name__

            # If we still have retries left, emit retry event and backoff.
            if attempt < max_retries:
                await _emit(
                    event_bus,
                    DispatchRetry(
                        session_id=session_id,
                        sequence=0,
                        agent_name=agent_name,
                        attempt=attempt + 1,
                        reason=last_error_msg,
                    ),
                )
                delay = retry_delay * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)

    # All retries exhausted via exception path.
    duration = time.monotonic() - start
    failed_env = envelope.with_error(
        ErrorDetail(error_type=last_exception_type or "infrastructure", message=last_error_msg)
    )

    await _emit(
        event_bus,
        DispatchFailed(
            session_id=session_id,
            sequence=0,
            agent_name=agent_name,
            error_message=last_error_msg,
            cost_usd=cumulative_cost,
        ),
    )

    return DispatchResult(
        envelope=failed_env,
        duration_seconds=duration,
        retries=max_retries,
        cost_usd=cumulative_cost,
    )
