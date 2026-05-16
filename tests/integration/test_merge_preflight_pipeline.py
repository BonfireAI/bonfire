"""Integration tests for the MergePreflight pipeline stage.

Contract coverage:
    - Integration boundary between MergePreflight and the surrounding
      pipeline (Wizard → MergePreflight → Steward).
    - Composition-root integration: ``standard_build()`` inserts the
      ``merge_preflight`` stage; ``steward.depends_on`` is rewired
      accordingly.
    - The ALLOW-WITH-ANNOTATION path for pre-existing debt.

Scenarios locked:
1. TestSinglePRHappyPath — preflight green -> pipeline reaches Steward.
2. TestSinglePRBlocksOnFailure — preflight returns FAILED with
   error_type='pure_warrior_bug' -> pipeline halts at merge_preflight.
3. TestSiblingBatchEnumWidening — the cross-PR enum-widening
   reproduction. Two synthetic PRs configured via mock; classifier
   returns CROSS_WAVE_INTERACTION; pipeline halts.
4. TestPreExistingDebtAllowed — ALLOW-WITH-ANNOTATION; preflight
   returns COMPLETED with META_PREFLIGHT_TEST_DEBT_NOTED=True; pipeline
   reaches Steward (does NOT halt).
5. TestStandardWorkflowRegistersPreflight — ``standard_build()`` plan
   contains the new stage; ``steward.depends_on == ['merge_preflight']``.
"""

from __future__ import annotations

from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import (
    Envelope,
    ErrorDetail,
    TaskStatus,
)
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _CompletingBackend:
    """Backend that completes every non-handler stage with a canned result.

    Pipeline stages without a handler_name route through the backend; this
    fake just returns a successful envelope so the pipeline can progress
    to the merge_preflight + steward stages where the actual contract lives.
    """

    def __init__(self, *, cost: float = 0.001) -> None:
        self._cost = cost
        self.calls: list[Envelope] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append(envelope)
        return envelope.with_result(f"{envelope.agent_name} done", cost_usd=self._cost)

    async def health_check(self) -> bool:
        return True


class _StubBardHandler:
    """Stub Bard that emits a PR-number-bearing envelope so downstream
    stages have data to extract."""

    async def handle(self, stage, envelope, prior_results):
        return envelope.with_result(
            "https://github.com/owner/repo/pull/100", cost_usd=0.0
        ).with_metadata(pr_number=100, pr_url="https://github.com/owner/repo/pull/100")


class _StubWizardHandler:
    """Stub Wizard that emits an APPROVE verdict so MergePreflight runs."""

    def __init__(self, *, verdict: str = "approve") -> None:
        self._verdict = verdict

    async def handle(self, stage, envelope, prior_results):
        return envelope.with_result(self._verdict, cost_usd=0.0).with_metadata(
            review_verdict=self._verdict
        )


class _StubStewardHandler:
    """Stub Steward that records that it ran (used to assert pipeline
    reached this stage when preflight is green or test-debt-only)."""

    def __init__(self) -> None:
        self.ran = False

    async def handle(self, stage, envelope, prior_results):
        self.ran = True
        return envelope.with_result("merged", cost_usd=0.0)


class _CannedPreflightHandler:
    """Test double for MergePreflightHandler: returns a canned envelope.

    Used to drive the pipeline-level scenarios without standing up the
    full classifier + scratch worktree machinery (those are unit-tested
    elsewhere). The handler-level integration test asserts that the
    pipeline correctly threads the canned status through to the next
    stage's gate.
    """

    def __init__(self, *, mode: str) -> None:
        """``mode`` ∈ {'green', 'pure_warrior_bug', 'cross_wave',
        'pre_existing_debt'}."""
        self._mode = mode
        self.ran = False

    async def handle(self, stage, envelope, prior_results):
        self.ran = True
        from bonfire.models.envelope import (
            META_PREFLIGHT_CLASSIFICATION,
            META_PREFLIGHT_TEST_DEBT_NOTED,
        )

        if self._mode == "green":
            return envelope.with_result(
                "preflight: PASSED (10 tests, 1.5s)", cost_usd=0.0
            ).with_metadata(**{META_PREFLIGHT_CLASSIFICATION: '{"verdict":"green"}'})
        if self._mode == "pre_existing_debt":
            return envelope.with_result(
                "preflight: PASSED with debt annotation", cost_usd=0.0
            ).with_metadata(
                **{
                    META_PREFLIGHT_CLASSIFICATION: '{"verdict":"pre_existing_debt"}',
                    META_PREFLIGHT_TEST_DEBT_NOTED: True,
                }
            )
        if self._mode == "pure_warrior_bug":
            return envelope.with_error(
                ErrorDetail(
                    error_type="pure_warrior_bug",
                    message="preflight blocks merge: pure-Warrior bug",
                    stage_name=stage.name,
                )
            )
        if self._mode == "cross_wave":
            return envelope.with_error(
                ErrorDetail(
                    error_type="cross_wave_interaction",
                    message="Cross-wave interaction detected with PR #17",
                    stage_name=stage.name,
                )
            )
        msg = f"unknown canned preflight mode: {self._mode}"  # pragma: no cover
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(handlers: dict[str, object]) -> PipelineEngine:
    return PipelineEngine(
        backend=_CompletingBackend(),
        bus=EventBus(),
        config=PipelineConfig(),
        handlers=handlers,
    )


def _build_plan_with_preflight() -> WorkflowPlan:
    """Mini plan: bard -> wizard -> merge_preflight -> steward.

    Drops scout/knight/warrior/prover (pure backend stages) for test
    speed; the contract is preserved at the
    wizard -> merge_preflight -> steward slice that the merge-
    preflight stage introduces.
    """
    return WorkflowPlan(
        name="preflight_integration",
        workflow_type=WorkflowType.STANDARD,
        stages=[
            StageSpec(name="bard", agent_name="bard", handler_name="bard", role="bard"),
            StageSpec(
                name="wizard",
                agent_name="wizard",
                handler_name="wizard",
                role="wizard",
                depends_on=["bard"],
            ),
            StageSpec(
                name="merge_preflight",
                agent_name="merge_preflight",
                handler_name="merge_preflight",
                role="verifier",
                depends_on=["wizard"],
            ),
            StageSpec(
                name="steward",
                agent_name="steward",
                handler_name="steward",
                role="steward",
                depends_on=["merge_preflight"],
            ),
        ],
        budget_usd=10.0,
    )


# ---------------------------------------------------------------------------
# 1. Single-PR happy path — Sage §D-CL.2 line 911.
# ---------------------------------------------------------------------------


class TestSinglePRHappyPath:
    """One PR, no siblings, all tests pass -> pipeline reaches Steward."""

    async def test_pipeline_progresses_to_steward_when_preflight_green(self) -> None:
        """Sage §D-CL.2 line 911: assert result.success is True, all stages
        in result.stages, result.stages['merge_preflight'].status == COMPLETED,
        result.stages['steward'].status == COMPLETED."""
        steward = _StubStewardHandler()
        engine = _make_engine(
            handlers={
                "bard": _StubBardHandler(),
                "wizard": _StubWizardHandler(verdict="approve"),
                "merge_preflight": _CannedPreflightHandler(mode="green"),
                "steward": steward,
            }
        )
        result = await engine.run(_build_plan_with_preflight())

        assert result.success is True, f"pipeline failed: {result.error}"
        assert "merge_preflight" in result.stages
        assert result.stages["merge_preflight"].status == TaskStatus.COMPLETED
        assert "steward" in result.stages
        assert result.stages["steward"].status == TaskStatus.COMPLETED
        assert steward.ran is True


# ---------------------------------------------------------------------------
# 2. Single-PR blocks on Warrior bug — Sage §D-CL.2 line 912.
# ---------------------------------------------------------------------------


class TestSinglePRBlocksOnFailure:
    """Preflight FAILED with error_type='pure_warrior_bug' -> pipeline halts;
    steward NOT called."""

    async def test_pipeline_halts_on_pure_warrior_bug(self) -> None:
        """Sage §D-CL.2 line 912: result.success is False,
        result.failed_stage == 'merge_preflight', 'steward' not in result.stages."""
        steward = _StubStewardHandler()
        engine = _make_engine(
            handlers={
                "bard": _StubBardHandler(),
                "wizard": _StubWizardHandler(verdict="approve"),
                "merge_preflight": _CannedPreflightHandler(mode="pure_warrior_bug"),
                "steward": steward,
            }
        )
        result = await engine.run(_build_plan_with_preflight())

        assert result.success is False
        assert result.failed_stage == "merge_preflight"
        assert "steward" not in result.stages
        assert steward.ran is False
        # Error detail surfaces via the failed envelope on merge_preflight.
        preflight_env = result.stages["merge_preflight"]
        assert preflight_env.status == TaskStatus.FAILED
        assert preflight_env.error is not None
        assert preflight_env.error.error_type == "pure_warrior_bug"


# ---------------------------------------------------------------------------
# 3. Sibling-batch enum widening — THE S007 reproduction.
#    Sage §D-CL.2 line 913 + §D8 line 665.
# ---------------------------------------------------------------------------


class TestSiblingBatchEnumWidening:
    """Two synthetic in-temp-repo PRs configured via mock; preflight applies
    both diffs, pytest fails, classifier returns CROSS_WAVE_INTERACTION;
    pipeline halts. This is a regression test for the historical
    cross-PR enum-widening incident."""

    async def test_cross_wave_interaction_blocked(self) -> None:
        """Sage §D-CL.2 line 913: pipeline halts; result.failed_stage ==
        'merge_preflight'.

        At the integration level we drive the failure mode via the canned
        handler (the unit-level classifier tests cover the algorithmic
        verdict). What this test asserts is the PIPELINE behavior: a
        CROSS_WAVE_INTERACTION FAILED envelope halts the run and does NOT
        proceed to Steward.
        """
        steward = _StubStewardHandler()
        engine = _make_engine(
            handlers={
                "bard": _StubBardHandler(),
                "wizard": _StubWizardHandler(verdict="approve"),
                "merge_preflight": _CannedPreflightHandler(mode="cross_wave"),
                "steward": steward,
            }
        )
        result = await engine.run(_build_plan_with_preflight())

        assert result.success is False
        assert result.failed_stage == "merge_preflight"
        assert "steward" not in result.stages
        assert steward.ran is False
        preflight_env = result.stages["merge_preflight"]
        assert preflight_env.error is not None
        assert preflight_env.error.error_type == "cross_wave_interaction"


# ---------------------------------------------------------------------------
# 4. Pre-existing debt ALLOWED — Sage Q6 ratified, §D-CL.2 line 914.
# ---------------------------------------------------------------------------


class TestPreExistingDebtAllowed:
    """Q6 ALLOW-WITH-ANNOTATION — baseline already failing; preflight
    returns COMPLETED with META_PREFLIGHT_TEST_DEBT_NOTED=True; pipeline
    reaches Steward (does NOT halt)."""

    async def test_pipeline_completes_with_debt_annotation(self) -> None:
        """Sage §D-CL.2 line 914 + §A Q6 line 156: COMPLETED status with
        META_PREFLIGHT_TEST_DEBT_NOTED=True; steward runs."""
        from bonfire.models.envelope import META_PREFLIGHT_TEST_DEBT_NOTED

        steward = _StubStewardHandler()
        engine = _make_engine(
            handlers={
                "bard": _StubBardHandler(),
                "wizard": _StubWizardHandler(verdict="approve"),
                "merge_preflight": _CannedPreflightHandler(mode="pre_existing_debt"),
                "steward": steward,
            }
        )
        result = await engine.run(_build_plan_with_preflight())

        assert result.success is True
        assert "merge_preflight" in result.stages
        preflight_env = result.stages["merge_preflight"]
        assert preflight_env.status == TaskStatus.COMPLETED
        assert preflight_env.metadata.get(META_PREFLIGHT_TEST_DEBT_NOTED) is True
        # Steward MUST run -- debt is annotated, not blocked.
        assert "steward" in result.stages
        assert result.stages["steward"].status == TaskStatus.COMPLETED
        assert steward.ran is True


# ---------------------------------------------------------------------------
# 5. standard_build() registers the merge_preflight stage.
#    Sage §D-CL.2 lines 915-916 + §D6 lines 530-544.
# ---------------------------------------------------------------------------


class TestStandardWorkflowRegistersPreflight:
    """standard_build() inserts merge_preflight between wizard and steward;
    steward.depends_on rewired to ['merge_preflight']."""

    def test_plan_contains_preflight_stage(self) -> None:
        """Sage §D-CL.2 line 915: stage with name='merge_preflight',
        handler_name='merge_preflight', role='verifier',
        depends_on=['wizard']."""
        from bonfire.workflow.standard import standard_build

        plan = standard_build()
        names = [s.name for s in plan.stages]
        assert "merge_preflight" in names

        preflight_stage = next(s for s in plan.stages if s.name == "merge_preflight")
        assert preflight_stage.handler_name == "merge_preflight"
        assert preflight_stage.role == "verifier"
        assert preflight_stage.depends_on == ["wizard"]

    def test_steward_depends_on_preflight(self) -> None:
        """Sage §D-CL.2 line 916 + §D6 line 542: steward.depends_on ==
        ['merge_preflight'] (NOT ['wizard'])."""
        from bonfire.workflow.standard import standard_build

        plan = standard_build()
        steward_stage = next(s for s in plan.stages if s.name == "steward")
        assert steward_stage.depends_on == ["merge_preflight"]

    def test_preflight_inserted_between_wizard_and_steward(self) -> None:
        """Order discipline: in the stage list, merge_preflight appears
        AFTER wizard and BEFORE steward."""
        from bonfire.workflow.standard import standard_build

        plan = standard_build()
        names = [s.name for s in plan.stages]
        wizard_idx = names.index("wizard")
        preflight_idx = names.index("merge_preflight")
        steward_idx = names.index("steward")
        assert wizard_idx < preflight_idx < steward_idx
