# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Shared handler-dispatch helper — bus-vs-PipelineResult parity at the handler seam.

Background
----------
Pipeline stages reach the agent backend via two paths:

1.  The engine's main path:
    ``engine/pipeline.py`` -> :func:`bonfire.dispatch.runner.execute_with_retry`
    -> ``backend.execute``. The runner emits ``DispatchStarted`` /
    ``DispatchCompleted`` / ``DispatchFailed`` and threads cumulative
    cost into the result.

2.  Handler-owned dispatches (e.g. ``handlers/sage_correction_bounce``):
    historically bypassed the runner and called ``backend.execute``
    directly. That broke two invariants the rest of the framework
    relies on:

    * **Event emission.** No ``Dispatch*`` events fire from the handler
      path. Bus observers (``CostTracker``, ``CostLedgerConsumer``,
      ``KnowledgeIngestConsumer``, the budget watchdog) silently miss
      every dollar the handler-owned dispatch spent.
    * **Cost stamping.** The handler returned an envelope with
      ``cost_usd = 0.0`` because nothing read
      ``backend_result.cost_usd``. The dollars vanished from
      ``PipelineResult.total_cost_usd`` too.

Wave 10 + Wave 11 Lanes A/B/C restored bus-vs-``PipelineResult`` parity on
every other halt branch. Lane D closes the handler-seam gap with a thin
shared helper that handlers route through instead of calling
``backend.execute`` raw.

Helper contract
---------------
:func:`run_handler_dispatch` wraps a single ``backend.execute`` call with:

* ``DispatchStarted`` emit BEFORE the call.
* ``DispatchCompleted`` emit on success, ``cost_usd`` populated from the
  backend's returned envelope so the bus side matches the envelope side.
* ``DispatchFailed`` emit on exception, then re-raise so the caller can
  decide how to route the failure (the calling handler's own try/except
  wraps this; the helper does NOT swallow).

Helper does NOT retry — handler-owned dispatch is single-shot per cycle.
The handler decides cycle budgeting; this helper owns event emission and
cost-bearing return.

``options`` is typed ``Any`` so handlers may pass either a real
``DispatchOptions`` (engine main path) or a handler-specific dataclass
(e.g. ``SageCorrectionDispatchOptions``) — whatever the backend accepts
under the ``options=`` keyword. The helper forwards ``options`` verbatim
and reads ``model`` for the event-emission name via a ``getattr`` with an
empty-string fallback (no exception on options-types that lack the
attribute).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bonfire.models.events import (
    BonfireEvent,
    DispatchCompleted,
    DispatchFailed,
    DispatchStarted,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus
    from bonfire.models.envelope import Envelope
    from bonfire.protocols import AgentBackend

__all__ = ["run_handler_dispatch"]


async def _emit(bus: EventBus | None, event: BonfireEvent) -> None:
    """Emit *event* on *bus* if a bus was provided; no-op otherwise."""
    if bus is not None:
        await bus.emit(event)


async def run_handler_dispatch(
    *,
    backend: AgentBackend,
    envelope: Envelope,
    options: Any,
    event_bus: EventBus | None = None,
) -> Envelope:
    """Invoke ``backend.execute`` once, emitting Dispatch* events.

    Single-shot — no retry. Returns the backend's envelope unchanged on
    success so the caller can read ``cost_usd`` and any structured
    metadata directly. Re-raises on exception after emitting
    ``DispatchFailed`` so the caller's existing try/except can route
    the failure.

    The handler's calling site looks like::

        try:
            backend_result = await run_handler_dispatch(
                backend=self._backend,
                envelope=envelope,
                options=dispatch_options,
                event_bus=self._event_bus,
            )
        except Exception as exc:
            # handler-specific failure routing
            ...

    Keyword-only to keep the call site self-documenting and to leave
    room for adding non-defaulted arguments later without breaking
    positional callers.
    """
    session_id = envelope.envelope_id
    agent_name = envelope.agent_name
    # ``options`` may be a Pydantic ``DispatchOptions`` (which has
    # ``.model``) or a handler-specific dataclass (e.g.
    # ``SageCorrectionDispatchOptions``) that does not. Empty-string
    # fallback keeps the event schema satisfied without forcing every
    # handler to construct a full ``DispatchOptions``.
    model_name = getattr(options, "model", "") or ""

    await _emit(
        event_bus,
        DispatchStarted(
            session_id=session_id,
            sequence=0,
            agent_name=agent_name,
            model=model_name,
        ),
    )

    try:
        result_env = await backend.execute(envelope, options=options)
    except Exception as exc:
        await _emit(
            event_bus,
            DispatchFailed(
                session_id=session_id,
                sequence=0,
                agent_name=agent_name,
                error_message=str(exc),
                cost_usd=0.0,
            ),
        )
        raise

    # Cost-bearing return: the bus event mirrors ``backend_result.cost_usd``
    # so a sum-of-observed-events reconstructs the engine accumulator.
    # ``getattr`` with a ``0.0`` fallback tolerates mocks that return a
    # plain ``MagicMock`` without ``.cost_usd`` set.
    result_cost = float(getattr(result_env, "cost_usd", 0.0) or 0.0)

    await _emit(
        event_bus,
        DispatchCompleted(
            session_id=session_id,
            sequence=0,
            agent_name=agent_name,
            cost_usd=result_cost,
            duration_seconds=0.0,
            model=model_name,
        ),
    )
    return result_env
