# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Unit tests for the ``bonfire run`` driver — NETWORK-FREE.

The driver wires a prompt into a workflow plan and runs it through the
live ``PipelineEngine``. These tests exercise plan selection, result
rendering, exit codes, and the prompt-to-plan handoff using a fake
backend injected via the ``build_engine`` seam — no SDK, no network.

The fake backend mirrors ``tests/unit/test_engine_pipeline.py``'s
``_MockBackend``: it returns COMPLETED envelopes by default and FAILED
envelopes for a configured set of agents.
"""

from __future__ import annotations

import pytest
import typer

from bonfire.cli.commands.run import _run, _select_plan
from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail
from bonfire.protocols import DispatchOptions

# ``debug`` is a gate-free, handler-free workflow (scout -> warrior); every
# stage routes straight through the backend, so a bare fake backend with no
# gate/handler registries drives it to completion with no network.
_GATELESS_WORKFLOW = "debug"


class _FakeBackend:
    """Backend that returns COMPLETED envelopes (FAILED for ``fail_agents``).

    Records every envelope it receives so a test can assert what the plan
    handed the engine — in particular that the prompt reached the plan's
    ``task_description`` and flowed into the dispatched task/context.
    """

    def __init__(self, *, fail_agents: set[str] | None = None) -> None:
        self.fail_agents = fail_agents or set()
        self.calls: list[Envelope] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append(envelope)
        if envelope.agent_name in self.fail_agents:
            return envelope.with_error(
                ErrorDetail(error_type="agent", message=f"{envelope.agent_name} failed")
            )
        return envelope.with_result(f"{envelope.agent_name} done", cost_usd=0.01)

    async def health_check(self) -> bool:
        return True


def _engine_factory(backend: _FakeBackend):
    """Build a ``build_engine`` seam returning an engine wired to *backend*."""

    def _build(plan: object) -> PipelineEngine:
        return PipelineEngine(
            backend=backend,  # type: ignore[arg-type]
            bus=EventBus(),
            config=PipelineConfig(),
        )

    return _build


# ---------------------------------------------------------------------------
# Plan selection — the prompt-to-plan handoff
# ---------------------------------------------------------------------------


class TestSelectPlan:
    """``_select_plan`` stamps the prompt and budget onto the chosen plan."""

    def test_prompt_reaches_task_description(self) -> None:
        plan = _select_plan("ship the widget", budget=None, workflow=_GATELESS_WORKFLOW)
        assert plan.task_description == "ship the widget"

    def test_budget_override_applied(self) -> None:
        plan = _select_plan("x", budget=3.5, workflow=_GATELESS_WORKFLOW)
        assert plan.budget_usd == 3.5

    def test_budget_none_keeps_plan_default(self) -> None:
        from bonfire.workflow.registry import get_default_registry

        factory_default = get_default_registry().get(_GATELESS_WORKFLOW)().budget_usd
        kept = _select_plan("x", budget=None, workflow=_GATELESS_WORKFLOW)
        # The factory's own default budget survives when none is passed.
        assert kept.budget_usd == factory_default

    def test_unknown_workflow_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            _select_plan("x", budget=None, workflow="no_such_workflow")


# ---------------------------------------------------------------------------
# Driver — happy path, failure path, exit codes
# ---------------------------------------------------------------------------


class TestRunDriver:
    """``_run`` drives the engine and renders the result with correct codes."""

    def test_happy_path_exits_zero(self) -> None:
        backend = _FakeBackend()
        with pytest.raises(typer.Exit) as exc_info:
            _run(
                "build a thing",
                workflow=_GATELESS_WORKFLOW,
                build_engine=_engine_factory(backend),
            )
        assert exc_info.value.exit_code == 0

    def test_failure_path_exits_nonzero(self) -> None:
        # Fail the first stage of the debug workflow so the run halts.
        backend = _FakeBackend(fail_agents={"scout"})
        with pytest.raises(typer.Exit) as exc_info:
            _run(
                "build a thing",
                workflow=_GATELESS_WORKFLOW,
                build_engine=_engine_factory(backend),
            )
        assert exc_info.value.exit_code == 1

    def test_prompt_reaches_dispatched_task(self) -> None:
        """The prompt must flow through the plan into the dispatched work."""
        backend = _FakeBackend()
        marker = "REACH-THE-BACKEND-MARKER"
        with pytest.raises(typer.Exit):
            _run(
                marker,
                workflow=_GATELESS_WORKFLOW,
                build_engine=_engine_factory(backend),
            )
        assert backend.calls, "expected the engine to dispatch at least one stage"
        first = backend.calls[0]
        assert marker in first.task or marker in first.context

    def test_unknown_workflow_exits_code_two(self) -> None:
        backend = _FakeBackend()
        with pytest.raises(typer.Exit) as exc_info:
            _run(
                "x",
                workflow="definitely_not_registered",
                build_engine=_engine_factory(backend),
            )
        assert exc_info.value.exit_code == 2
