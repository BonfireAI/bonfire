# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for BON-1068 H2 — bounce-target cost must reach the running total.

Defect (origin/main, ``engine/pipeline.py``):

  - ``_handle_bounce`` runs the bounce TARGET (a real warrior re-execution
    that can be substantial), adds ``bounce_env.cost_usd`` to a *local*
    ``total_cost`` that is never returned, then runs the retry and returns
    only the retry envelope.
  - ``_handle_gate_result`` returns ``(None, bounced.cost_usd)`` — only the
    RETRY envelope's cost. The bounce-target's own cost is silently dropped
    from the caller's running total, so the budget watchdog under-counts: a
    pipeline can spend ``budget + Σ bounce-target-costs`` before it trips.
  - ``completed[target_name] = bounce_env`` destructively overwrites the
    prior bounce-target envelope; no ``__bounced`` marker preserves the
    original for downstream consumers.

These tests drive ``_handle_bounce`` / ``_handle_gate_result`` directly with
a real ``PipelineEngine`` whose ``_execute_stage`` is monkeypatched to return
deterministic envelopes (bounce-target cost = 0.50, retry cost = 0.20). We
assert:

  1. The cost delta returned by ``_handle_gate_result`` after a successful
     bounce is target + retry = 0.70 (not 0.20). FAILS on current code, which
     returns only 0.20.
  2. After a bounce, ``completed`` preserves the ORIGINAL bounce-target
     envelope under a ``"<target>__bounced"`` key. FAILS on current code,
     which never writes that key.

``pyproject.toml`` sets ``asyncio_mode = "auto"``; async tests run without an
explicit mark.
"""

from __future__ import annotations

import pytest

from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.models.plan import (
    GateContext,
    GateResult,
    StageSpec,
    WorkflowSpec,
    WorkflowType,
)

TARGET_COST = 0.50  # bounce-target re-execution cost (the dropped one)
RETRY_COST = 0.20  # retry of the original stage


class _NullBackend:
    """Minimal AgentBackend stand-in — never actually invoked because we
    monkeypatch ``_execute_stage``."""

    async def execute(self, envelope: Envelope, *, options: object) -> Envelope:
        raise AssertionError("backend.execute must not be called in this test")

    async def health_check(self) -> bool:
        return True


class _PassGate:
    """Gate that passes — used so the post-bounce re-evaluation succeeds and
    ``_handle_bounce`` returns the retry envelope (the success path where the
    target cost must already have been accounted for)."""

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        return GateResult(gate_name="g", passed=True, severity="error")


class _FailThenPassGate:
    """Fails the FIRST evaluation (the original stage's gate, which triggers
    the bounce) and passes every subsequent evaluation (the post-bounce
    re-check on the retried stage, which lets the bounce SUCCEED).

    This is required to exercise the success path of ``_handle_gate_result``:
    original-gate-fails -> bounce -> retry-gate-passes -> the function returns
    ``(None, cost_delta)``. Under the fix, ``cost_delta`` must equal
    target + retry; on current code it is only the retry's cost (or, because
    the same fail/pass dependency does not hold across a single static gate,
    0.0 on the halt path). A stateful gate makes the success path
    deterministic.
    """

    def __init__(self) -> None:
        self._calls = 0

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        self._calls += 1
        if self._calls == 1:
            return GateResult(
                gate_name="g", passed=False, severity="error", message="needs correction"
            )
        return GateResult(gate_name="g", passed=True, severity="error")


def _engine(gates: dict[str, object]) -> PipelineEngine:
    return PipelineEngine(
        backend=_NullBackend(),
        bus=EventBus(),
        config=PipelineConfig(),
        gate_registry=gates,
    )


def _plan() -> WorkflowSpec:
    """A two-stage plan: ``warrior`` bounces to ``scout`` on gate failure."""
    return WorkflowSpec(
        name="p",
        workflow_type=WorkflowType.CUSTOM,
        budget_usd=10.0,
        stages=[
            StageSpec(name="scout", agent_name="scout-agent"),
            StageSpec(
                name="warrior",
                agent_name="warrior-agent",
                gates=["g"],
                on_gate_failure="scout",
            ),
        ],
    )


def _patch_execute_stage(
    engine: PipelineEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace ``_execute_stage`` so the bounce TARGET ('scout') returns a
    completed envelope costing ``TARGET_COST`` and the retried ORIGINAL
    ('warrior') returns a completed envelope costing ``RETRY_COST``.
    Deterministic, no real backend dispatch.
    """

    async def fake_execute_stage(
        spec: StageSpec,
        completed: dict[str, Envelope],
        total_cost: float,
        plan: WorkflowSpec,
        session_id: str,
        initial_envelope: Envelope | None = None,
    ) -> Envelope:
        cost = TARGET_COST if spec.name == "scout" else RETRY_COST
        return Envelope(
            task=spec.name,
            agent_name=spec.agent_name,
            status=TaskStatus.COMPLETED,
            result=f"{spec.name} done",
            cost_usd=cost,
        )

    monkeypatch.setattr(engine, "_execute_stage", fake_execute_stage)


# ---------------------------------------------------------------------------
# H2.a — bounce-target cost reaches the caller's running total
# ---------------------------------------------------------------------------


class TestBounceTargetCostPropagated:
    async def test_handle_gate_result_returns_target_plus_retry_cost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a failed gate triggers a successful bounce, the cost delta
        returned to the caller MUST be target + retry (0.70). On current code
        ``_handle_gate_result`` returns only ``bounced.cost_usd`` (0.20),
        dropping the 0.50 bounce-target cost from the budget watchdog total.
        """
        engine = _engine({"g": _FailThenPassGate()})
        _patch_execute_stage(engine, monkeypatch)

        plan = _plan()
        stage_map = {s.name: s for s in plan.stages}
        warrior_spec = stage_map["warrior"]

        # Original warrior envelope that just "failed" its gate.
        warrior_env = Envelope(
            task="warrior",
            agent_name="warrior-agent",
            status=TaskStatus.COMPLETED,
            result="warrior first attempt",
            cost_usd=0.0,
        )
        stages_done: dict[str, Envelope] = {"warrior": warrior_env}

        _halt, cost_delta = await engine._handle_gate_result(
            warrior_spec,
            warrior_env,
            "warrior",
            stages_done,
            0.0,
            0.0,
            "ses",
            plan,
            stage_map,
        )

        assert cost_delta == pytest.approx(TARGET_COST + RETRY_COST), (
            "bounce-target cost (0.50) must be added to the retry cost (0.20); "
            f"got {cost_delta} — the target cost was dropped"
        )

    async def test_handle_bounce_preserves_original_target_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a bounce, ``completed`` MUST retain the ORIGINAL bounce-target
        envelope under a ``"<target>__bounced"`` key so downstream consumers
        that reference the pre-bounce 'scout' output still see it. On current
        code ``_handle_bounce`` overwrites ``completed['scout']`` with the
        bounce envelope and never writes any ``__bounced`` key.
        """
        engine = _engine({"g": _PassGate()})
        _patch_execute_stage(engine, monkeypatch)

        plan = _plan()
        stage_map = {s.name: s for s in plan.stages}
        warrior_spec = stage_map["warrior"]

        # A prior scout output exists in `completed` before the bounce re-runs
        # scout — this original must be preserved.
        original_scout = Envelope(
            task="scout",
            agent_name="scout-agent",
            status=TaskStatus.COMPLETED,
            result="ORIGINAL scout output",
            cost_usd=0.11,
        )
        completed: dict[str, Envelope] = {"scout": original_scout}

        gate_failure = GateResult(
            gate_name="g", passed=False, severity="error", message="bounce me"
        )

        result = await engine._handle_bounce(
            plan,
            warrior_spec,
            gate_failure,
            completed,
            0.0,
            "ses",
            stage_map,
        )

        # Bounce succeeded -> retry envelope returned.
        assert result is not None
        # Original scout output preserved under the __bounced marker.
        assert "scout__bounced" in completed, (
            "original bounce-target envelope must be preserved under "
            "'scout__bounced'; keys present: " + ", ".join(sorted(completed))
        )
        assert completed["scout__bounced"].result == "ORIGINAL scout output"
