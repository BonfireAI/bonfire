"""RED tests for bonfire.models.plan.

Contract derived from the hardened v1 engine. Public v0.1 drops
internal-only fields and cross-module dependencies — see
docs/release-gates.md for the transfer-target discipline.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

# RED-phase import shim: see test_envelope.py for the rationale.
try:
    from bonfire.models.plan import (
        GateContext,
        GateResult,
        StageSpec,
        WorkflowPlan,
        WorkflowType,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    GateContext = GateResult = StageSpec = WorkflowPlan = WorkflowType = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.models.plan is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.models.plan not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# WorkflowType
# ---------------------------------------------------------------------------


class TestWorkflowType:
    def test_is_str_enum(self):
        from enum import StrEnum

        assert issubclass(WorkflowType, StrEnum)

    def test_exactly_five_values(self):
        assert len(WorkflowType) == 5

    def test_standard(self):
        assert WorkflowType.STANDARD == "standard"

    def test_single(self):
        assert WorkflowType.SINGLE == "single"

    def test_research(self):
        assert WorkflowType.RESEARCH == "research"

    def test_debug(self):
        assert WorkflowType.DEBUG == "debug"

    def test_custom(self):
        assert WorkflowType.CUSTOM == "custom"


# ---------------------------------------------------------------------------
# GateContext
# ---------------------------------------------------------------------------


class TestGateContext:
    def test_construction_minimal(self):
        gc = GateContext(pipeline_cost_usd=0.5)
        assert gc.pipeline_cost_usd == 0.5
        assert gc.prior_results == {}

    def test_with_prior_results(self):
        gc = GateContext(pipeline_cost_usd=1.0, prior_results={"stage1": "ok"})
        assert gc.prior_results == {"stage1": "ok"}

    def test_frozen(self):
        gc = GateContext(pipeline_cost_usd=0.5)
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            gc.pipeline_cost_usd = 2.0

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            GateContext()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


class TestGateResult:
    def test_construction_minimal(self):
        r = GateResult(gate_name="lint", passed=True, severity="info")
        assert r.gate_name == "lint"
        assert r.passed is True
        assert r.severity == "info"
        assert r.message == ""

    def test_with_message(self):
        r = GateResult(gate_name="lint", passed=False, severity="error", message="bad syntax")
        assert r.message == "bad syntax"

    def test_frozen(self):
        r = GateResult(gate_name="lint", passed=True, severity="info")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            r.passed = False

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            GateResult(gate_name="lint")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# StageSpec
# ---------------------------------------------------------------------------


class TestStageSpec:
    def test_construction_minimal(self):
        s = StageSpec(name="build", agent_name="knight")
        assert s.name == "build"
        assert s.agent_name == "knight"

    def test_default_fields(self):
        s = StageSpec(name="build", agent_name="knight")
        assert s.role == ""
        assert s.handler_name is None
        assert s.gates == []
        assert s.on_gate_failure is None
        assert s.parallel_group is None
        assert s.depends_on == []
        assert s.max_iterations == 1
        assert s.model_override is None
        assert s.metadata == {}

    def test_eleven_fields(self):
        """StageSpec exposes 11 fields on the public contract."""
        expected = {
            "name",
            "agent_name",
            "role",
            "handler_name",
            "gates",
            "on_gate_failure",
            "parallel_group",
            "depends_on",
            "max_iterations",
            "model_override",
            "metadata",
        }
        assert set(StageSpec.model_fields.keys()) == expected

    def test_agent_alias_accepted(self):
        """`agent` is an input alias for `agent_name`."""
        s = StageSpec(name="build", agent="knight")  # type: ignore[call-arg]
        assert s.agent_name == "knight"

    def test_agent_name_accepted(self):
        s = StageSpec(name="build", agent_name="knight")
        assert s.agent_name == "knight"

    def test_model_alias_accepted(self):
        s = StageSpec(name="build", agent_name="knight", model="claude-opus")  # type: ignore[call-arg]
        assert s.model_override == "claude-opus"

    def test_model_override_accepted(self):
        s = StageSpec(name="build", agent_name="knight", model_override="claude-opus")
        assert s.model_override == "claude-opus"

    def test_frozen(self):
        s = StageSpec(name="build", agent_name="knight")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            s.name = "changed"

    def test_full_construction(self):
        s = StageSpec(
            name="build",
            agent_name="knight",
            role="tester",
            handler_name="test_handler",
            gates=["lint", "typecheck"],
            on_gate_failure="fallback",
            parallel_group="group-a",
            depends_on=["fetch"],
            max_iterations=3,
            model_override="claude-opus",
            metadata={"priority": "high"},
        )
        assert s.gates == ["lint", "typecheck"]
        assert s.on_gate_failure == "fallback"
        assert s.parallel_group == "group-a"
        assert s.depends_on == ["fetch"]
        assert s.max_iterations == 3
        assert s.model_override == "claude-opus"
        assert s.metadata == {"priority": "high"}

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            StageSpec(name="build")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# WorkflowPlan — happy path
# ---------------------------------------------------------------------------


class TestWorkflowPlanConstruction:
    def test_single_stage(self):
        plan = WorkflowPlan(
            name="test",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="build", agent_name="knight")],
        )
        assert plan.name == "test"
        assert len(plan.stages) == 1

    def test_linear_three_stages(self):
        plan = WorkflowPlan(
            name="test",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="a", agent_name="knight"),
                StageSpec(name="b", agent_name="warrior", depends_on=["a"]),
                StageSpec(name="c", agent_name="sage", depends_on=["b"]),
            ],
        )
        assert len(plan.stages) == 3

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D is a valid DAG."""
        plan = WorkflowPlan(
            name="diamond",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="a", agent_name="k"),
                StageSpec(name="b", agent_name="k", depends_on=["a"]),
                StageSpec(name="c", agent_name="k", depends_on=["a"]),
                StageSpec(name="d", agent_name="k", depends_on=["b", "c"]),
            ],
        )
        assert len(plan.stages) == 4

    def test_default_budget(self):
        plan = WorkflowPlan(
            name="t",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="k")],
        )
        assert plan.budget_usd == 10.0

    def test_custom_budget(self):
        plan = WorkflowPlan(
            name="t",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="k")],
            budget_usd=25.0,
        )
        assert plan.budget_usd == 25.0

    def test_task_alias_accepted(self):
        """`task` is an input alias for `name`."""
        plan = WorkflowPlan(
            task="aliased-task",  # type: ignore[call-arg]
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="k")],
        )
        assert plan.name == "aliased-task"

    def test_frozen(self):
        plan = WorkflowPlan(
            name="t",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="k")],
        )
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            plan.name = "changed"


# ---------------------------------------------------------------------------
# WorkflowPlan — empty stages
# ---------------------------------------------------------------------------


class TestWorkflowPlanEmptyStages:
    def test_empty_rejected_for_standard(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(name="t", workflow_type=WorkflowType.STANDARD, stages=[])
        assert "empty" in str(exc.value).lower() or "stages" in str(exc.value).lower()

    def test_empty_rejected_for_research(self):
        with pytest.raises(ValidationError):
            WorkflowPlan(name="t", workflow_type=WorkflowType.RESEARCH, stages=[])

    def test_empty_rejected_for_debug(self):
        with pytest.raises(ValidationError):
            WorkflowPlan(name="t", workflow_type=WorkflowType.DEBUG, stages=[])

    def test_empty_rejected_for_custom(self):
        with pytest.raises(ValidationError):
            WorkflowPlan(name="t", workflow_type=WorkflowType.CUSTOM, stages=[])

    def test_empty_allowed_for_single(self):
        """SINGLE workflow may have an empty stages list."""
        plan = WorkflowPlan(name="t", workflow_type=WorkflowType.SINGLE, stages=[])
        assert plan.stages == []


# ---------------------------------------------------------------------------
# WorkflowPlan — duplicate names
# ---------------------------------------------------------------------------


class TestWorkflowPlanDuplicateNames:
    def test_duplicate_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k"),
                    StageSpec(name="a", agent_name="k"),
                ],
            )
        assert "a" in str(exc.value)
        assert "duplicate" in str(exc.value).lower()

    def test_duplicate_error_names_the_duplicate(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="lint", agent_name="k"),
                    StageSpec(name="test", agent_name="k"),
                    StageSpec(name="lint", agent_name="k"),
                ],
            )
        assert "'lint'" in str(exc.value) or "lint" in str(exc.value)


# ---------------------------------------------------------------------------
# WorkflowPlan — dangling references
# ---------------------------------------------------------------------------


class TestWorkflowPlanDanglingReferences:
    def test_depends_on_unknown_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[StageSpec(name="a", agent_name="k", depends_on=["ghost"])],
            )
        assert "ghost" in str(exc.value)

    def test_on_gate_failure_unknown_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[StageSpec(name="a", agent_name="k", on_gate_failure="ghost")],
            )
        assert "ghost" in str(exc.value)

    def test_dangling_error_message_contains_name(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k"),
                    StageSpec(name="b", agent_name="k", depends_on=["nonexistent"]),
                ],
            )
        assert "nonexistent" in str(exc.value)
        assert "'b'" in str(exc.value) or "b" in str(exc.value)


# ---------------------------------------------------------------------------
# WorkflowPlan — self-bounce
# ---------------------------------------------------------------------------


class TestWorkflowPlanSelfBounce:
    def test_self_bounce_on_depends_on_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[StageSpec(name="a", agent_name="k", depends_on=["a"])],
            )
        msg = str(exc.value).lower()
        assert "self" in msg or "bounce" in msg or "itself" in msg

    def test_self_bounce_on_gate_failure_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[StageSpec(name="a", agent_name="k", on_gate_failure="a")],
            )
        msg = str(exc.value).lower()
        assert "self" in msg or "bounce" in msg or "itself" in msg


# ---------------------------------------------------------------------------
# WorkflowPlan — cycle detection
# ---------------------------------------------------------------------------


class TestWorkflowPlanCycles:
    def test_two_node_cycle_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k", depends_on=["b"]),
                    StageSpec(name="b", agent_name="k", depends_on=["a"]),
                ],
            )
        msg = str(exc.value).lower()
        assert "cycle" in msg

    def test_two_node_cycle_error_includes_path(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k", depends_on=["b"]),
                    StageSpec(name="b", agent_name="k", depends_on=["a"]),
                ],
            )
        msg = str(exc.value)
        assert "\u2192" in msg or "->" in msg

    def test_two_node_cycle_path_names_both_nodes(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k", depends_on=["b"]),
                    StageSpec(name="b", agent_name="k", depends_on=["a"]),
                ],
            )
        msg = str(exc.value)
        assert "a" in msg and "b" in msg

    def test_three_node_cycle_rejected(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k", depends_on=["c"]),
                    StageSpec(name="b", agent_name="k", depends_on=["a"]),
                    StageSpec(name="c", agent_name="k", depends_on=["b"]),
                ],
            )
        msg = str(exc.value).lower()
        assert "cycle" in msg

    def test_three_node_cycle_error_includes_path(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k", depends_on=["c"]),
                    StageSpec(name="b", agent_name="k", depends_on=["a"]),
                    StageSpec(name="c", agent_name="k", depends_on=["b"]),
                ],
            )
        msg = str(exc.value)
        assert "\u2192" in msg or "->" in msg
        # all three node names appear in the cycle path
        assert "a" in msg and "b" in msg and "c" in msg

    def test_cycle_via_on_gate_failure(self):
        """on_gate_failure counts in the dependency graph for cycle detection."""
        with pytest.raises(ValidationError) as exc:
            WorkflowPlan(
                name="t",
                workflow_type=WorkflowType.STANDARD,
                stages=[
                    StageSpec(name="a", agent_name="k", on_gate_failure="b"),
                    StageSpec(name="b", agent_name="k", on_gate_failure="a"),
                ],
            )
        msg = str(exc.value).lower()
        assert "cycle" in msg


# ---------------------------------------------------------------------------
# WorkflowPlan — describe()
# ---------------------------------------------------------------------------


class TestWorkflowPlanDescribe:
    def test_describe_returns_string(self):
        plan = WorkflowPlan(
            name="test",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="knight")],
        )
        out = plan.describe()
        assert isinstance(out, str)

    def test_describe_includes_name(self):
        plan = WorkflowPlan(
            name="unique-plan-name",
            workflow_type=WorkflowType.STANDARD,
            stages=[StageSpec(name="a", agent_name="knight")],
        )
        assert "unique-plan-name" in plan.describe()

    def test_describe_includes_workflow_type(self):
        plan = WorkflowPlan(
            name="t",
            workflow_type=WorkflowType.RESEARCH,
            stages=[StageSpec(name="a", agent_name="knight")],
        )
        assert "research" in plan.describe()

    def test_describe_includes_stage_names(self):
        plan = WorkflowPlan(
            name="t",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="stage-one", agent_name="knight"),
                StageSpec(name="stage-two", agent_name="warrior", depends_on=["stage-one"]),
            ],
        )
        out = plan.describe()
        assert "stage-one" in out
        assert "stage-two" in out
