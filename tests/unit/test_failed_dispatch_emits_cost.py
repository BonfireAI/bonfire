# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for BON-1068 — failed-dispatch events must carry the REAL cost.

Defect (origin/main, ``src/bonfire/dispatch/runner.py``): all three
``DispatchFailed(...)`` emissions in ``execute_with_retry`` omit ``cost_usd``,
so the event defaults to ``cost_usd=0.0`` even though the dispatch already
burned tokens and the true ``cumulative_cost`` is in scope at the emit (the
sibling ``DispatchResult(..., cost_usd=cumulative_cost)`` returns prove it).

``CostLedgerConsumer`` reads ``event.cost_usd`` off ``DispatchFailed`` and
writes it to the ledger (see ``test_cost_ledger_failed_records.py``). Because
the runner always emits ``0.0``, the ledger silently records $0.00 of burned
spend for every failed dispatch — the "Built by Bonfire for $X.XX" rollup
under-counts.

These tests assert the FIXED behavior across the THREE failure paths:

  1. Terminal error (no retry) — ``DispatchFailed.cost_usd`` equals the burned
     cost, not 0.0.
  2. Retries exhausted on a FAILED envelope — same.
  3. Exhaustion via the exception path after an earlier costed attempt — same.

And — wiring through the real ``CostLedgerConsumer`` exactly as the existing
BON-1068 tests do — the persisted ``failed`` ledger row reflects that real
cost rather than 0.0.

Why each FAILS on current code: the runner emits ``DispatchFailed`` WITHOUT
``cost_usd``, so the event's ``cost_usd`` is the model default ``0.0`` and
every assertion below (``== cumulative_cost`` / ``> 0``) fails.

``pyproject.toml`` sets ``asyncio_mode = "auto"``; ``async def`` tests run
without an explicit mark.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.dispatch.runner import execute_with_retry
from bonfire.events.bus import EventBus
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import BonfireEvent, DispatchFailed
from bonfire.protocols import DispatchOptions

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test doubles / helpers (mirrors test_dispatch_runner.py idioms)
# ---------------------------------------------------------------------------


class ScriptedBackend:
    """Fake ``AgentBackend`` returning pre-configured envelopes/exceptions."""

    def __init__(self, responses: list[Envelope | Exception]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.call_count += 1
        if not self._responses:
            return envelope.with_error(
                ErrorDetail(error_type="exhausted", message="no more scripted responses")
            )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def health_check(self) -> bool:
        return True


class FailedCapture:
    """Collects emitted ``DispatchFailed`` events."""

    def __init__(self) -> None:
        self.events: list[DispatchFailed] = []

    async def handler(self, event: BonfireEvent) -> None:
        if isinstance(event, DispatchFailed):
            self.events.append(event)


def _envelope() -> Envelope:
    return Envelope(task="burn tokens then fail", agent_name="warrior", model="claude-sonnet")


def _options() -> DispatchOptions:
    return DispatchOptions(model="claude-sonnet", max_budget_usd=1.0)


def _failed_with_cost(env: Envelope, error_type: str, message: str, cost: float) -> Envelope:
    """A FAILED envelope carrying a real cost (mirrors the runner test idiom)."""
    return env.with_error(ErrorDetail(error_type=error_type, message=message)).model_copy(
        update={"cost_usd": cost}
    )


# ---------------------------------------------------------------------------
# Path 1 — terminal error (no retry): emit ~line 137
# ---------------------------------------------------------------------------


async def test_terminal_failure_event_carries_real_cost() -> None:
    env = _envelope()
    bus = EventBus()
    capture = FailedCapture()
    bus.subscribe(DispatchFailed, capture.handler)

    # AgentError is terminal → no retry → returns immediately at emit ~137.
    backend = ScriptedBackend([_failed_with_cost(env, "AgentError", "refused", 0.42)])
    result = await execute_with_retry(
        backend, env, _options(), max_retries=3, retry_delay=0.0, event_bus=bus
    )

    assert result.envelope.status == TaskStatus.FAILED
    assert result.cost_usd == pytest.approx(0.42)
    assert len(capture.events) == 1
    # On current (buggy) code this is 0.0, not 0.42.
    assert capture.events[0].cost_usd == pytest.approx(0.42), (
        "terminal DispatchFailed must carry the burned cost, not 0.0"
    )


# ---------------------------------------------------------------------------
# Path 2 — retries exhausted on a FAILED envelope: emit ~line 172
# ---------------------------------------------------------------------------


async def test_retry_exhausted_failure_event_carries_cumulative_cost() -> None:
    env = _envelope()
    bus = EventBus()
    capture = FailedCapture()
    bus.subscribe(DispatchFailed, capture.handler)

    # Retryable (non-terminal) FAILED envelope every attempt, each costing 0.05.
    # max_retries=2 → 3 attempts → cumulative_cost == 0.15.
    responses: list[Envelope | Exception] = [
        _failed_with_cost(env, "ProcessError", "crash", 0.05) for _ in range(3)
    ]
    backend = ScriptedBackend(responses)
    result = await execute_with_retry(
        backend, env, _options(), max_retries=2, retry_delay=0.0, event_bus=bus
    )

    assert result.envelope.status == TaskStatus.FAILED
    assert result.cost_usd == pytest.approx(0.15)
    assert len(capture.events) == 1
    assert capture.events[0].cost_usd == pytest.approx(0.15), (
        "retry-exhausted DispatchFailed must carry the cumulative burned cost, not 0.0"
    )


# ---------------------------------------------------------------------------
# Path 3 — exhaustion via the exception path after an earlier costed attempt:
# emit ~line 234
# ---------------------------------------------------------------------------


async def test_exception_exhaustion_failure_event_carries_prior_cost() -> None:
    env = _envelope()
    bus = EventBus()
    capture = FailedCapture()
    bus.subscribe(DispatchFailed, capture.handler)

    # Attempt 0: retryable FAILED envelope costing 0.08 (accrues, continues).
    # Attempts 1+: raise → final exhaustion lands on the exception-path emit,
    # where cumulative_cost still holds the earlier 0.08.
    responses: list[Envelope | Exception] = [
        _failed_with_cost(env, "ProcessError", "crash", 0.08),
        RuntimeError("infra down"),
        RuntimeError("infra down"),
    ]
    backend = ScriptedBackend(responses)
    result = await execute_with_retry(
        backend, env, _options(), max_retries=2, retry_delay=0.0, event_bus=bus
    )

    assert result.envelope.status == TaskStatus.FAILED
    assert result.cost_usd == pytest.approx(0.08)
    assert len(capture.events) == 1
    assert capture.events[0].cost_usd == pytest.approx(0.08), (
        "exception-exhaustion DispatchFailed must carry the earlier burned cost, not 0.0"
    )


# ---------------------------------------------------------------------------
# End-to-end — through the real CostLedgerConsumer (as the BON-1068 tests do)
# ---------------------------------------------------------------------------


async def test_failed_dispatch_ledger_row_reflects_real_cost(tmp_path: Path) -> None:
    """A terminal failure routed through the runner AND the real consumer must
    persist a ``failed`` ledger row carrying the true burned cost — not $0.00.
    """
    ledger_path = tmp_path / "cost" / "cost_ledger.jsonl"
    env = _envelope()
    bus = EventBus()
    consumer = CostLedgerConsumer(ledger_path=ledger_path)
    consumer.register(bus)

    backend = ScriptedBackend([_failed_with_cost(env, "AgentError", "refused", 0.42)])
    await execute_with_retry(
        backend, env, _options(), max_retries=3, retry_delay=0.0, event_bus=bus
    )

    assert ledger_path.exists(), "failed dispatch must produce a ledger row"
    rows = [json.loads(ln) for ln in ledger_path.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "dispatch"
    assert row["status"] == "failed"
    assert row["cost_usd"] == pytest.approx(0.42), (
        "ledger must record the real burned cost of a failed dispatch, not 0.0"
    )
