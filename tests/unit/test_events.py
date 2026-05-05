"""RED tests for bonfire.models.events.

Contract derived from the hardened v1 engine. Public v0.1 drops
internal-only fields and cross-module dependencies — see
docs/release-gates.md for the transfer-target discipline.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

# RED-phase import shim: the implementation does not exist yet. Tests still
# reference real names; each test will fail via the autouse fixture while the
# module is missing. Collection succeeds because the import error is swallowed
# at module load time.
try:
    from bonfire.models.events import (
        EVENT_REGISTRY,
        AxiomLoaded,
        BonfireEvent,
        BonfireEventUnion,
        CostAccrued,
        CostBudgetExceeded,
        CostBudgetWarning,
        DispatchCompleted,
        DispatchFailed,
        DispatchRetry,
        DispatchStarted,
        GitBranchCreated,
        GitCommitCreated,
        GitPRCreated,
        GitPRMerged,
        PipelineCompleted,
        PipelineFailed,
        PipelinePaused,
        PipelineStarted,
        QualityBypassed,
        QualityFailed,
        QualityPassed,
        SessionEnded,
        SessionStarted,
        StageCompleted,
        StageFailed,
        StageSkipped,
        StageStarted,
        XPAwarded,
        XPPenalty,
        XPRespawn,
        event_adapter,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    EVENT_REGISTRY = None  # type: ignore[assignment]
    AxiomLoaded = BonfireEvent = BonfireEventUnion = None  # type: ignore[assignment,misc]
    CostAccrued = CostBudgetExceeded = CostBudgetWarning = None  # type: ignore[assignment,misc]
    DispatchCompleted = DispatchFailed = DispatchRetry = DispatchStarted = None  # type: ignore[assignment,misc]
    GitBranchCreated = GitCommitCreated = GitPRCreated = GitPRMerged = None  # type: ignore[assignment,misc]
    PipelineCompleted = PipelineFailed = PipelinePaused = PipelineStarted = None  # type: ignore[assignment,misc]
    QualityBypassed = QualityFailed = QualityPassed = None  # type: ignore[assignment,misc]
    SessionEnded = SessionStarted = None  # type: ignore[assignment,misc]
    StageCompleted = StageFailed = StageSkipped = StageStarted = None  # type: ignore[assignment,misc]
    XPAwarded = XPPenalty = XPRespawn = None  # type: ignore[assignment,misc]
    event_adapter = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.models.events is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.models.events not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Reusable session context
# ---------------------------------------------------------------------------

SESSION = {"session_id": "sess-abc", "sequence": 1}


# ---------------------------------------------------------------------------
# BonfireEvent base
# ---------------------------------------------------------------------------


class TestBonfireEventBase:
    """Base class exposes standard fields and a category property."""

    def test_base_standard_fields_present(self):
        """event_id, timestamp, session_id, sequence are declared; event_type per subclass."""
        field_names = set(BonfireEvent.model_fields.keys())
        assert {"event_id", "timestamp", "session_id", "sequence"}.issubset(field_names)

    def test_event_id_default_is_12_hex_chars(self):
        e = PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION)
        assert isinstance(e.event_id, str)
        assert len(e.event_id) == 12
        int(e.event_id, 16)

    def test_timestamp_is_float(self):
        e = PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION)
        assert isinstance(e.timestamp, float)
        assert e.timestamp > 0

    def test_event_ids_are_unique(self):
        ids = {
            PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION).event_id for _ in range(50)
        }
        assert len(ids) == 50

    def test_category_property(self):
        e = PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION)
        assert e.category == "pipeline"

    def test_category_strips_action(self):
        e = StageStarted(stage_name="s", agent_name="a", **SESSION)
        assert e.category == "stage"

    def test_frozen(self):
        e = PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION)
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            e.plan_name = "changed"


# ---------------------------------------------------------------------------
# Category: Pipeline (4)
# ---------------------------------------------------------------------------


class TestPipelineEvents:
    def test_pipeline_started_event_type(self):
        e = PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION)
        assert e.event_type == "pipeline.started"
        assert e.plan_name == "p"
        assert e.budget_usd == 1.0

    def test_pipeline_completed_event_type(self):
        e = PipelineCompleted(
            total_cost_usd=0.5, duration_seconds=12.0, stages_completed=3, **SESSION
        )
        assert e.event_type == "pipeline.completed"
        assert e.total_cost_usd == 0.5
        assert e.duration_seconds == 12.0
        assert e.stages_completed == 3

    def test_pipeline_failed_event_type(self):
        e = PipelineFailed(failed_stage="knight", error_message="boom", **SESSION)
        assert e.event_type == "pipeline.failed"
        assert e.failed_stage == "knight"
        assert e.error_message == "boom"

    def test_pipeline_paused_event_type(self):
        e = PipelinePaused(reason="budget", checkpoint_path="/tmp/ck", **SESSION)
        assert e.event_type == "pipeline.paused"
        assert e.reason == "budget"
        assert e.checkpoint_path == "/tmp/ck"

    def test_all_pipeline_events_share_category(self):
        events = [
            PipelineStarted(plan_name="p", budget_usd=1.0, **SESSION),
            PipelineCompleted(
                total_cost_usd=0.0, duration_seconds=0.0, stages_completed=0, **SESSION
            ),
            PipelineFailed(failed_stage="s", error_message="m", **SESSION),
            PipelinePaused(reason="r", checkpoint_path="p", **SESSION),
        ]
        for e in events:
            assert e.category == "pipeline"


# ---------------------------------------------------------------------------
# Category: Stage (4)
# ---------------------------------------------------------------------------


class TestStageEvents:
    def test_stage_started(self):
        e = StageStarted(stage_name="s1", agent_name="knight", **SESSION)
        assert e.event_type == "stage.started"
        assert e.stage_name == "s1"
        assert e.agent_name == "knight"

    def test_stage_completed(self):
        e = StageCompleted(
            stage_name="s1",
            agent_name="knight",
            duration_seconds=5.0,
            cost_usd=0.2,
            **SESSION,
        )
        assert e.event_type == "stage.completed"
        assert e.duration_seconds == 5.0
        assert e.cost_usd == 0.2

    def test_stage_failed(self):
        e = StageFailed(stage_name="s1", agent_name="knight", error_message="nope", **SESSION)
        assert e.event_type == "stage.failed"
        assert e.error_message == "nope"

    def test_stage_skipped(self):
        e = StageSkipped(stage_name="s1", reason="gate", **SESSION)
        assert e.event_type == "stage.skipped"
        assert e.reason == "gate"

    def test_all_stage_events_share_category(self):
        assert StageStarted(stage_name="s", agent_name="a", **SESSION).category == "stage"
        assert (
            StageCompleted(
                stage_name="s",
                agent_name="a",
                duration_seconds=0.0,
                cost_usd=0.0,
                **SESSION,
            ).category
            == "stage"
        )
        assert (
            StageFailed(stage_name="s", agent_name="a", error_message="m", **SESSION).category
            == "stage"
        )
        assert StageSkipped(stage_name="s", reason="r", **SESSION).category == "stage"


# ---------------------------------------------------------------------------
# Category: Dispatch (4)
# ---------------------------------------------------------------------------


class TestDispatchEvents:
    def test_dispatch_started(self):
        e = DispatchStarted(agent_name="knight", model="claude-sonnet", **SESSION)
        assert e.event_type == "dispatch.started"
        assert e.agent_name == "knight"
        assert e.model == "claude-sonnet"

    def test_dispatch_completed(self):
        e = DispatchCompleted(agent_name="knight", cost_usd=0.3, duration_seconds=4.0, **SESSION)
        assert e.event_type == "dispatch.completed"

    def test_dispatch_failed(self):
        e = DispatchFailed(agent_name="knight", error_message="timeout", **SESSION)
        assert e.event_type == "dispatch.failed"

    def test_dispatch_retry(self):
        e = DispatchRetry(agent_name="knight", attempt=2, reason="rate_limit", **SESSION)
        assert e.event_type == "dispatch.retry"
        assert e.attempt == 2

    def test_all_dispatch_events_share_category(self):
        assert DispatchStarted(agent_name="a", model="m", **SESSION).category == "dispatch"
        assert (
            DispatchRetry(agent_name="a", attempt=1, reason="r", **SESSION).category == "dispatch"
        )

    # -- BON-351 D4 -- DispatchCompleted gains a ``model`` field ----------------
    #
    # Symmetric with DispatchStarted.model. The runner has options.model in
    # scope at both emission points. Default is "" so the existing
    # _minimal_kwargs registry (line 608-613) does NOT need updating —
    # registry sentinel survives unchanged.

    def test_dispatch_completed_has_model_field(self):
        """Sage memo D4 — DispatchCompleted.model defaults to empty string,
        keeping the existing _minimal_kwargs registry compatible without
        mutation. Locks the backward-compat invariant for the registry
        sentinel test (TestEventCount).
        """
        e = DispatchCompleted(agent_name="x", cost_usd=0.0, duration_seconds=0.0, **SESSION)
        assert e.model == ""

    def test_dispatch_completed_accepts_model(self):
        """Sage memo D4 — when the runner sets ``model=options.model`` on
        emission, the value round-trips onto the event for downstream
        consumers (CostLedgerConsumer per D7).
        """
        e = DispatchCompleted(
            agent_name="x",
            cost_usd=0.0,
            duration_seconds=0.0,
            model="claude-opus-4-7",
            **SESSION,
        )
        assert e.model == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Category: Quality (3)
# ---------------------------------------------------------------------------


class TestQualityEvents:
    def test_quality_passed(self):
        e = QualityPassed(gate_name="lint", stage_name="knight", **SESSION)
        assert e.event_type == "quality.passed"

    def test_quality_failed_defaults(self):
        e = QualityFailed(gate_name="lint", message="ugly", **SESSION)
        assert e.event_type == "quality.failed"
        assert e.stage_name == ""
        assert e.severity == "error"

    def test_quality_failed_custom_severity(self):
        e = QualityFailed(
            gate_name="lint",
            stage_name="knight",
            severity="warning",
            message="m",
            **SESSION,
        )
        assert e.severity == "warning"

    def test_quality_bypassed(self):
        e = QualityBypassed(gate_name="lint", stage_name="knight", reason="flaky", **SESSION)
        assert e.event_type == "quality.bypassed"

    def test_all_quality_events_share_category(self):
        assert QualityPassed(gate_name="g", stage_name="s", **SESSION).category == "quality"
        assert QualityFailed(gate_name="g", message="m", **SESSION).category == "quality"
        assert (
            QualityBypassed(gate_name="g", stage_name="s", reason="r", **SESSION).category
            == "quality"
        )


# ---------------------------------------------------------------------------
# Category: Git (4)
# ---------------------------------------------------------------------------


class TestGitEvents:
    def test_git_branch_created(self):
        e = GitBranchCreated(branch_name="feature/x", **SESSION)
        assert e.event_type == "git.branch_created"
        assert e.branch_name == "feature/x"

    def test_git_commit_created(self):
        e = GitCommitCreated(sha="abc1234", message="commit msg", **SESSION)
        assert e.event_type == "git.commit_created"
        assert e.sha == "abc1234"

    def test_git_pr_created(self):
        e = GitPRCreated(pr_number=42, pr_url="https://x/pr/42", **SESSION)
        assert e.event_type == "git.pr_created"
        assert e.pr_number == 42

    def test_git_pr_merged(self):
        e = GitPRMerged(pr_number=42, **SESSION)
        assert e.event_type == "git.pr_merged"
        assert e.pr_number == 42

    def test_all_git_events_share_category(self):
        assert GitBranchCreated(branch_name="b", **SESSION).category == "git"
        assert GitCommitCreated(sha="s", message="m", **SESSION).category == "git"
        assert GitPRCreated(pr_number=1, pr_url="u", **SESSION).category == "git"
        assert GitPRMerged(pr_number=1, **SESSION).category == "git"


# ---------------------------------------------------------------------------
# Category: Cost (3)
# ---------------------------------------------------------------------------


class TestCostEvents:
    def test_cost_accrued(self):
        e = CostAccrued(amount_usd=0.1, source="knight", running_total_usd=0.5, **SESSION)
        assert e.event_type == "cost.accrued"

    def test_cost_budget_warning(self):
        e = CostBudgetWarning(current_usd=4.0, budget_usd=5.0, percent=0.8, **SESSION)
        assert e.event_type == "cost.budget_warning"
        assert e.percent == 0.8

    def test_cost_budget_exceeded(self):
        e = CostBudgetExceeded(current_usd=6.0, budget_usd=5.0, **SESSION)
        assert e.event_type == "cost.budget_exceeded"

    def test_all_cost_events_share_category(self):
        assert (
            CostAccrued(amount_usd=0.1, source="s", running_total_usd=0.1, **SESSION).category
            == "cost"
        )


# ---------------------------------------------------------------------------
# Category: Session (2)
# ---------------------------------------------------------------------------


class TestSessionEvents:
    def test_session_started(self):
        e = SessionStarted(task="t", workflow="standard", **SESSION)
        assert e.event_type == "session.started"
        assert e.task == "t"
        assert e.workflow == "standard"

    def test_session_ended(self):
        e = SessionEnded(status="completed", total_cost_usd=1.0, **SESSION)
        assert e.event_type == "session.ended"
        assert e.status == "completed"

    def test_all_session_events_share_category(self):
        assert SessionStarted(task="t", workflow="w", **SESSION).category == "session"
        assert SessionEnded(status="s", total_cost_usd=0.0, **SESSION).category == "session"


# ---------------------------------------------------------------------------
# Category: XP (3)
# ---------------------------------------------------------------------------


class TestXPEvents:
    def test_xp_awarded(self):
        e = XPAwarded(amount=10, reason="green", **SESSION)
        assert e.event_type == "xp.awarded"
        assert e.amount == 10

    def test_xp_penalty(self):
        e = XPPenalty(amount=5, reason="red", **SESSION)
        assert e.event_type == "xp.penalty"

    def test_xp_respawn(self):
        e = XPRespawn(checkpoint="ck-1", reason="stuck", **SESSION)
        assert e.event_type == "xp.respawn"

    def test_all_xp_events_share_category(self):
        assert XPAwarded(amount=1, reason="r", **SESSION).category == "xp"
        assert XPPenalty(amount=1, reason="r", **SESSION).category == "xp"
        assert XPRespawn(checkpoint="c", reason="r", **SESSION).category == "xp"


# ---------------------------------------------------------------------------
# Category: Axiom (1)
# ---------------------------------------------------------------------------


class TestAxiomEvents:
    def test_axiom_loaded_event_type(self):
        e = AxiomLoaded(role="knight", axiom_version="v1")
        assert e.event_type == "axiom.loaded"
        assert e.role == "knight"
        assert e.axiom_version == "v1"

    def test_axiom_loaded_default_cognitive_pattern(self):
        e = AxiomLoaded(role="knight", axiom_version="v1")
        assert e.cognitive_pattern == "observe"

    def test_axiom_loaded_session_id_default_empty(self):
        """AxiomLoaded allows emission outside session context."""
        e = AxiomLoaded(role="knight", axiom_version="v1")
        assert e.session_id == ""
        assert e.sequence == 0

    def test_axiom_loaded_accepts_valid_cognitive_patterns(self):
        for pattern in [
            "observe",
            "contract",
            "execute",
            "synthesize",
            "audit",
            "publish",
            "announce",
        ]:
            e = AxiomLoaded(role="r", axiom_version="v", cognitive_pattern=pattern)
            assert e.cognitive_pattern == pattern

    def test_axiom_loaded_rejects_bad_cognitive_pattern(self):
        with pytest.raises(ValidationError):
            AxiomLoaded(role="r", axiom_version="v", cognitive_pattern="invalid")

    def test_axiom_loaded_category(self):
        e = AxiomLoaded(role="r", axiom_version="v")
        assert e.category == "axiom"


# ---------------------------------------------------------------------------
# Event count & union
# ---------------------------------------------------------------------------


class TestEventCount:
    """29 concrete events after BON-338 added SecurityDenied."""

    def test_registry_has_28_events(self):
        assert len(EVENT_REGISTRY) == 29

    def test_registry_keys_match_event_types(self):
        for key, cls in EVENT_REGISTRY.items():
            instance_kwargs = _minimal_kwargs(cls)
            instance = cls(**instance_kwargs)
            assert instance.event_type == key

    def test_registry_values_all_subclass_bonfire_event(self):
        for cls in EVENT_REGISTRY.values():
            assert issubclass(cls, BonfireEvent)

    def test_distinct_categories_match_expected_set(self):
        """Registry covers these exact category prefixes."""
        categories = set()
        for cls in EVENT_REGISTRY.values():
            instance = cls(**_minimal_kwargs(cls))
            categories.add(instance.category)
        assert categories == {
            "pipeline",
            "stage",
            "dispatch",
            "quality",
            "git",
            "cost",
            "session",
            "xp",
            "axiom",
            "security",
        }

    def test_category_counts(self):
        counts: dict[str, int] = {}
        for cls in EVENT_REGISTRY.values():
            instance = cls(**_minimal_kwargs(cls))
            counts[instance.category] = counts.get(instance.category, 0) + 1
        assert counts["pipeline"] == 4
        assert counts["stage"] == 4
        assert counts["dispatch"] == 4
        assert counts["quality"] == 3
        assert counts["git"] == 4
        assert counts["cost"] == 3
        assert counts["session"] == 2
        assert counts["xp"] == 3
        assert counts["axiom"] == 1
        assert counts["security"] == 1


class TestEventUnion:
    """BonfireEventUnion is a discriminated union over all 29 event types."""

    def test_union_has_28_members(self):
        # BonfireEventUnion is Annotated[Union[...], Field(discriminator=...)]
        # Access the underlying union via __args__[0].__args__
        members = BonfireEventUnion.__args__[0].__args__
        assert len(members) == 29

    def test_union_members_all_unique_event_types(self):
        members = BonfireEventUnion.__args__[0].__args__
        types_seen = set()
        for m in members:
            instance = m(**_minimal_kwargs(m))
            types_seen.add(instance.event_type)
        assert len(types_seen) == 29

    def test_event_adapter_validates_python_dict(self):
        data = {
            "event_type": "pipeline.started",
            "session_id": "s",
            "sequence": 1,
            "plan_name": "p",
            "budget_usd": 1.0,
        }
        e = event_adapter.validate_python(data)
        assert isinstance(e, PipelineStarted)

    def test_event_adapter_json_round_trip_pipeline_started(self):
        original = PipelineStarted(plan_name="p", budget_usd=1.5, **SESSION)
        blob = event_adapter.dump_json(original)
        restored = event_adapter.validate_json(blob)
        assert isinstance(restored, PipelineStarted)
        assert restored.plan_name == "p"
        assert restored.budget_usd == 1.5
        assert restored.session_id == SESSION["session_id"]

    def test_event_adapter_json_round_trip_stage_completed(self):
        original = StageCompleted(
            stage_name="s",
            agent_name="a",
            duration_seconds=5.0,
            cost_usd=0.25,
            **SESSION,
        )
        blob = event_adapter.dump_json(original)
        restored = event_adapter.validate_json(blob)
        assert isinstance(restored, StageCompleted)
        assert restored.cost_usd == 0.25

    def test_event_adapter_json_round_trip_axiom_loaded(self):
        original = AxiomLoaded(role="knight", axiom_version="v1", cognitive_pattern="execute")
        blob = event_adapter.dump_json(original)
        restored = event_adapter.validate_json(blob)
        assert isinstance(restored, AxiomLoaded)
        assert restored.role == "knight"
        assert restored.cognitive_pattern == "execute"

    def test_event_adapter_discriminator_routes_by_event_type(self):
        blob = b'{"event_type":"git.pr_merged","session_id":"s","sequence":1,"pr_number":7}'
        restored = event_adapter.validate_json(blob)
        assert isinstance(restored, GitPRMerged)
        assert restored.pr_number == 7

    def test_event_adapter_rejects_unknown_event_type(self):
        data = {
            "event_type": "nope.bad",
            "session_id": "s",
            "sequence": 1,
        }
        with pytest.raises(ValidationError):
            event_adapter.validate_python(data)


# ---------------------------------------------------------------------------
# Helpers for constructing minimal event instances by class
# ---------------------------------------------------------------------------


def _minimal_kwargs(cls: type[BonfireEvent]) -> dict:
    """Return the smallest kwargs dict that constructs a valid instance of cls."""
    # AxiomLoaded has its own defaults for session_id/sequence
    if cls is AxiomLoaded:
        return {"role": "r", "axiom_version": "v"}
    base = dict(SESSION)
    # per-class required fields
    per_class: dict[type, dict] = {
        PipelineStarted: {"plan_name": "p", "budget_usd": 1.0},
        PipelineCompleted: {
            "total_cost_usd": 0.0,
            "duration_seconds": 0.0,
            "stages_completed": 0,
        },
        PipelineFailed: {"failed_stage": "s", "error_message": "m"},
        PipelinePaused: {"reason": "r", "checkpoint_path": "p"},
        StageStarted: {"stage_name": "s", "agent_name": "a"},
        StageCompleted: {
            "stage_name": "s",
            "agent_name": "a",
            "duration_seconds": 0.0,
            "cost_usd": 0.0,
        },
        StageFailed: {"stage_name": "s", "agent_name": "a", "error_message": "m"},
        StageSkipped: {"stage_name": "s", "reason": "r"},
        DispatchStarted: {"agent_name": "a", "model": "m"},
        DispatchCompleted: {
            "agent_name": "a",
            "cost_usd": 0.0,
            "duration_seconds": 0.0,
        },
        DispatchFailed: {"agent_name": "a", "error_message": "m"},
        DispatchRetry: {"agent_name": "a", "attempt": 1, "reason": "r"},
        QualityPassed: {"gate_name": "g", "stage_name": "s"},
        QualityFailed: {"gate_name": "g", "message": "m"},
        QualityBypassed: {"gate_name": "g", "stage_name": "s", "reason": "r"},
        GitBranchCreated: {"branch_name": "b"},
        GitCommitCreated: {"sha": "s", "message": "m"},
        GitPRCreated: {"pr_number": 1, "pr_url": "u"},
        GitPRMerged: {"pr_number": 1},
        CostAccrued: {"amount_usd": 0.0, "source": "s", "running_total_usd": 0.0},
        CostBudgetWarning: {"current_usd": 0.0, "budget_usd": 1.0, "percent": 0.0},
        CostBudgetExceeded: {"current_usd": 0.0, "budget_usd": 1.0},
        SessionStarted: {"task": "t", "workflow": "w"},
        SessionEnded: {"status": "s", "total_cost_usd": 0.0},
        XPAwarded: {"amount": 1, "reason": "r"},
        XPPenalty: {"amount": 1, "reason": "r"},
        XPRespawn: {"checkpoint": "c", "reason": "r"},
    }
    # SecurityDenied — import lazily here so the registry can include it
    # without every _minimal_kwargs caller needing the import at module load.
    try:
        from bonfire.models.events import SecurityDenied as _SD  # type: ignore[import]

        per_class[_SD] = {
            "tool_name": "Bash",
            "reason": "r",
            "pattern_id": "C1.1-rm-rf-non-temp",
        }
    except ImportError:
        pass
    base.update(per_class.get(cls, {}))
    return base
