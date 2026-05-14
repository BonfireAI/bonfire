# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract for ``PipelineEngine`` pre/post-bracket plumbing.

The Caronte bracket is the v0.1 Inquisitor-as-post-pipeline-judge
extension to the existing main-DAG pipeline. The Hephaestus bracket
(BON-958, v1.1) lives in the pre-bracket slot but ships empty in
v1.0; the parameter exists for forward-compat so v1.1 can land
without an engine-API change.

API surface defined here:

1. ``PipelineEngine.__init__`` accepts ``pre_bracket`` and
   ``post_bracket`` keyword-only parameters, each typed
   ``list[StageSpec] | None``.
2. Both default to ``None`` (engines constructed without bracket
   stages continue to work unchanged — backward compat).
3. Pre-bracket runs BEFORE the main DAG. In v1.0 it ships empty;
   passing ``None`` or ``[]`` is the canonical path. This test file
   locks the parameter's existence + None/[] no-op behavior; richer
   pre-bracket semantics are Hephaestus v1.1's contract (BON-958).
4. Post-bracket runs sequentially AFTER the main DAG completes
   successfully. Each post-bracket stage is dispatched to its
   registered handler (typically the Inquisitor) with the same
   ``prior_results`` shape main-DAG stages see.
5. The post-bracket Inquisitor stage's verdict status routes the
   pipeline's ``success`` field:

   - ``PASS`` → ``PipelineResult.success=True``; effectuation
     enabled (downstream Steward proceeds).
   - ``CONCERNS`` → ``PipelineResult.success=True`` but the
     bracket envelope's metadata signals
     ``bracket_verdict_effectuate=False`` — halt before effectuation.
   - ``FAIL`` → ``PipelineResult.success=False`` even when all
     main-DAG stages were green.

6. The bracket verdict status MUST be reachable from the
   ``PipelineResult`` — minimally via the post-bracket stage
   envelope's metadata under
   ``META_BRACKET_VERDICT_STATUS`` (PipelineResult's 8-field shape
   is frozen by Sage D8; the bracket signal rides on the stage
   envelope's metadata, not as a new PipelineResult field).

7. ``PipelineResult.stages`` includes post-bracket stage envelopes
   keyed by stage name — same shape as main-DAG stages.

These tests are RED on the current ``PipelineEngine`` (which has
no bracket parameters); the Warriors implement against this contract.
"""

from __future__ import annotations

import inspect
from typing import Any

from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Constants — names the Warrior wires into the implementation
# ---------------------------------------------------------------------------

# Metadata key carrying the post-bracket Inquisitor verdict status.
# Lives on the post-bracket stage's returned envelope's ``metadata``.
META_BRACKET_VERDICT_STATUS = "bracket_verdict_status"

# Metadata key signaling whether the verdict permits effectuation.
# Mirrors the Inquisitor axiom's PASS/CONCERNS/FAIL → effectuate
# routing. Default ``True``; flipped to ``False`` on CONCERNS+FAIL.
META_BRACKET_EFFECTUATE = "bracket_verdict_effectuate"


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _MockBackend:
    """Backend returning COMPLETED envelopes by default."""

    def __init__(self, cost: float = 0.01) -> None:
        self.cost = cost
        self.calls: list[Envelope] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append(envelope)
        return envelope.with_result(f"{envelope.agent_name} done", cost_usd=self.cost)

    async def health_check(self) -> bool:
        return True


class _MockHandler:
    """Stub handler returning a successful envelope."""

    def __init__(self, result: str = "handled") -> None:
        self.result = result
        self.calls = 0

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        self.calls += 1
        return envelope.with_result(self.result, cost_usd=0.01)


class _FakeInquisitorHandler:
    """Post-bracket Inquisitor stand-in.

    Records a verdict status on the returned envelope's metadata under
    ``META_BRACKET_VERDICT_STATUS`` and ``META_BRACKET_EFFECTUATE``.
    The real handler builds these via its own verdict parse; this
    mock skips the parse and emits them directly so the engine
    contract is exercised in isolation.
    """

    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[tuple[StageSpec, Envelope, dict[str, str]]] = []

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        self.calls.append((stage, envelope, dict(prior_results)))
        # CONCERNS + FAIL block effectuation; only PASS proceeds.
        effectuate = self.status == "PASS"
        return envelope.with_result("bracket judged").with_metadata(
            **{
                META_BRACKET_VERDICT_STATUS: self.status,
                META_BRACKET_EFFECTUATE: effectuate,
            }
        )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _main_plan() -> WorkflowPlan:
    return WorkflowPlan(
        name="main",
        workflow_type=WorkflowType.STANDARD,
        stages=[StageSpec(name="A", agent_name="A")],
    )


def _make_engine(
    *,
    backend: _MockBackend | None = None,
    handlers: dict[str, Any] | None = None,
    pre_bracket: list[StageSpec] | None = None,
    post_bracket: list[StageSpec] | None = None,
) -> Any:
    """Construct a PipelineEngine with optional bracket parameters."""
    from bonfire.engine.pipeline import PipelineEngine

    return PipelineEngine(
        backend=backend or _MockBackend(),
        bus=EventBus(),
        config=PipelineConfig(),
        handlers=handlers,
        pre_bracket=pre_bracket,
        post_bracket=post_bracket,
    )


# ===========================================================================
# 1. Constructor surface — pre_bracket / post_bracket parameters
# ===========================================================================


class TestConstructorSurface:
    def test_pipeline_engine_accepts_pre_bracket_kwarg(self) -> None:
        """``PipelineEngine.__init__`` declares a ``pre_bracket``
        keyword-only parameter.

        The parameter exists for v1.1 (Hephaestus / BON-958) forward
        compat; v1.0 ships with no pre-bracket use case but the API
        surface must absorb it without a future engine-API change.
        """
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.__init__)
        params = sig.parameters
        assert "pre_bracket" in params, (
            "PipelineEngine.__init__ must declare a `pre_bracket` kwarg. "
            f"Got params: {sorted(params.keys())!r}"
        )
        # Must be keyword-only (per existing engine constructor style).
        assert params["pre_bracket"].kind == inspect.Parameter.KEYWORD_ONLY, (
            "pre_bracket must be keyword-only"
        )
        # Must default to None (backward compat for existing callers).
        assert params["pre_bracket"].default is None

    def test_pipeline_engine_accepts_post_bracket_kwarg(self) -> None:
        """``PipelineEngine.__init__`` declares a ``post_bracket``
        keyword-only parameter, defaulting to ``None``."""
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.__init__)
        params = sig.parameters
        assert "post_bracket" in params, (
            "PipelineEngine.__init__ must declare a `post_bracket` kwarg. "
            f"Got params: {sorted(params.keys())!r}"
        )
        assert params["post_bracket"].kind == inspect.Parameter.KEYWORD_ONLY
        assert params["post_bracket"].default is None

    def test_pre_bracket_accepts_none(self) -> None:
        """``pre_bracket=None`` is a valid construction — the default
        v1.0 ship configuration."""
        engine = _make_engine(pre_bracket=None)
        assert engine is not None

    def test_pre_bracket_accepts_empty_list(self) -> None:
        """``pre_bracket=[]`` is equivalent to ``None`` (no pre-bracket
        stages). The v1.0 ship configuration."""
        engine = _make_engine(pre_bracket=[])
        assert engine is not None

    def test_post_bracket_accepts_none(self) -> None:
        engine = _make_engine(post_bracket=None)
        assert engine is not None


# ===========================================================================
# 2. Backward compat — no bracket parameters
# ===========================================================================


class TestBackwardCompat:
    async def test_engine_without_brackets_unchanged_success(self) -> None:
        """Construction without bracket kwargs preserves current
        behavior — main-DAG-only pipelines succeed unchanged."""
        engine = _make_engine()
        plan = _main_plan()
        result = await engine.run(plan)
        assert result.success is True
        assert "A" in result.stages

    async def test_engine_with_none_brackets_unchanged_success(self) -> None:
        """Explicit ``pre_bracket=None``/``post_bracket=None`` is
        equivalent to omitting them."""
        engine = _make_engine(pre_bracket=None, post_bracket=None)
        plan = _main_plan()
        result = await engine.run(plan)
        assert result.success is True


# ===========================================================================
# 3. Pre-bracket — v1.0 ships empty (forward-compat slot)
# ===========================================================================


class TestPreBracketV1Empty:
    async def test_empty_pre_bracket_does_not_change_pipeline_outcome(self) -> None:
        """``pre_bracket=[]`` is a no-op. Pipeline outcome identical to
        the ``pre_bracket=None`` case. This locks the v1.0 ship
        semantics; Hephaestus v1.1 (BON-958) carves richer pre-bracket
        contracts on top."""
        engine = _make_engine(pre_bracket=[])
        plan = _main_plan()
        result = await engine.run(plan)
        assert result.success is True
        assert "A" in result.stages


# ===========================================================================
# 4. Post-bracket execution — runs after main DAG
# ===========================================================================


class TestPostBracketExecution:
    async def test_post_bracket_stage_dispatched(self) -> None:
        """A post-bracket stage with a registered handler runs after
        the main DAG completes."""
        bracket_handler = _FakeInquisitorHandler(status="PASS")
        post_stage = StageSpec(
            name="inquisitor",
            agent_name="inquisitor",
            handler_name="inquisitor",
        )
        engine = _make_engine(
            handlers={"inquisitor": bracket_handler},
            post_bracket=[post_stage],
        )
        result = await engine.run(_main_plan())
        assert bracket_handler.calls, "Post-bracket handler must be dispatched after main DAG"
        assert "inquisitor" in result.stages, (
            "Post-bracket stage envelope must appear in PipelineResult.stages"
        )

    async def test_post_bracket_sees_main_dag_prior_results(self) -> None:
        """The post-bracket handler receives the main-DAG stage
        results in its ``prior_results`` argument — so the Inquisitor
        can judge the closed envelope chain."""
        bracket_handler = _FakeInquisitorHandler(status="PASS")
        post_stage = StageSpec(
            name="inquisitor",
            agent_name="inquisitor",
            handler_name="inquisitor",
        )
        engine = _make_engine(
            handlers={"inquisitor": bracket_handler},
            post_bracket=[post_stage],
        )
        await engine.run(_main_plan())
        assert bracket_handler.calls, "Inquisitor handler not dispatched"
        _, _, prior_results = bracket_handler.calls[0]
        assert "A" in prior_results, (
            f"Inquisitor must see main-DAG stage 'A' result via "
            f"prior_results. Got keys: {sorted(prior_results.keys())!r}"
        )


# ===========================================================================
# 5. Verdict routing — PASS / CONCERNS / FAIL
# ===========================================================================


class TestVerdictRouting:
    async def test_pass_verdict_yields_success_true(self) -> None:
        """``status=PASS`` → ``PipelineResult.success=True``; bracket
        metadata signals ``effectuate=True``."""
        bracket_handler = _FakeInquisitorHandler(status="PASS")
        post_stage = StageSpec(
            name="inquisitor",
            agent_name="inquisitor",
            handler_name="inquisitor",
        )
        engine = _make_engine(
            handlers={"inquisitor": bracket_handler},
            post_bracket=[post_stage],
        )
        result = await engine.run(_main_plan())

        assert result.success is True, (
            f"PASS verdict must yield success=True. Got error={result.error!r}"
        )
        bracket_env = result.stages.get("inquisitor")
        assert bracket_env is not None
        assert bracket_env.metadata.get(META_BRACKET_VERDICT_STATUS) == "PASS"
        assert bracket_env.metadata.get(META_BRACKET_EFFECTUATE) is True

    async def test_concerns_verdict_yields_success_true_with_effectuate_false(
        self,
    ) -> None:
        """``status=CONCERNS`` → ``success=True`` (pipeline ran clean)
        BUT bracket metadata signals ``effectuate=False`` (Steward
        halts before applying side effects).

        This is the Anta-triages-via-Deck path: the run produced
        artifacts worth examining but the Inquisitor flagged enough
        concern that effectuation is not auto-approved."""
        bracket_handler = _FakeInquisitorHandler(status="CONCERNS")
        post_stage = StageSpec(
            name="inquisitor",
            agent_name="inquisitor",
            handler_name="inquisitor",
        )
        engine = _make_engine(
            handlers={"inquisitor": bracket_handler},
            post_bracket=[post_stage],
        )
        result = await engine.run(_main_plan())

        assert result.success is True, (
            "CONCERNS verdict still yields success=True (pipeline "
            "completed). The block on effectuation is signaled via "
            "metadata, not via PipelineResult.success."
        )
        bracket_env = result.stages.get("inquisitor")
        assert bracket_env is not None
        assert bracket_env.metadata.get(META_BRACKET_VERDICT_STATUS) == "CONCERNS"
        assert bracket_env.metadata.get(META_BRACKET_EFFECTUATE) is False, (
            "CONCERNS verdict must signal `effectuate=False` on the bracket envelope's metadata."
        )

    async def test_fail_verdict_yields_success_false(self) -> None:
        """``status=FAIL`` → ``PipelineResult.success=False`` even if
        every main-DAG stage was green.

        The Inquisitor's FAIL is authoritative: the run is rejected at
        the bracket regardless of the main pipeline's outcome."""
        bracket_handler = _FakeInquisitorHandler(status="FAIL")
        post_stage = StageSpec(
            name="inquisitor",
            agent_name="inquisitor",
            handler_name="inquisitor",
        )
        engine = _make_engine(
            handlers={"inquisitor": bracket_handler},
            post_bracket=[post_stage],
        )
        result = await engine.run(_main_plan())

        assert result.success is False, "FAIL verdict must yield PipelineResult.success=False."
        bracket_env = result.stages.get("inquisitor")
        assert bracket_env is not None
        assert bracket_env.metadata.get(META_BRACKET_VERDICT_STATUS) == "FAIL"
        assert bracket_env.metadata.get(META_BRACKET_EFFECTUATE) is False


# ===========================================================================
# 6. Main-DAG failure short-circuits the bracket
# ===========================================================================


class TestMainDAGFailureShortCircuit:
    async def test_post_bracket_skipped_when_main_dag_fails(self) -> None:
        """If the main DAG fails, the post-bracket Inquisitor does NOT
        run — the pipeline is already lost; judging a half-built
        artifact is wasted budget."""

        class _FailingHandler:
            async def handle(
                self,
                stage: StageSpec,
                envelope: Envelope,
                prior_results: dict[str, str],
            ) -> Envelope:
                return envelope.with_error(ErrorDetail(error_type="test", message="boom"))

        bracket_handler = _FakeInquisitorHandler(status="PASS")
        post_stage = StageSpec(
            name="inquisitor",
            agent_name="inquisitor",
            handler_name="inquisitor",
        )
        plan = WorkflowPlan(
            name="failing",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(
                    name="A",
                    agent_name="A",
                    handler_name="handler-A",
                )
            ],
        )
        engine = _make_engine(
            handlers={
                "handler-A": _FailingHandler(),
                "inquisitor": bracket_handler,
            },
            post_bracket=[post_stage],
        )
        result = await engine.run(plan)
        assert result.success is False
        assert not bracket_handler.calls, (
            "Post-bracket Inquisitor must NOT run when main DAG fails."
        )
