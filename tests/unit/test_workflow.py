"""Tests for bonfire.workflow — factories, registry, dependency constraints.

Contract mirrored from the hardened v1 workflow package. Public v0.1 ships
FIVE built-in factories (standard_build, debug, dual_scout, triple_scout,
spike) plus a named WorkflowRegistry. The private ``project_strategist``
factory is deferred — it depends on the Strategist handler, which is not
part of this transfer.

Every factory returns a frozen, DAG-validated WorkflowPlan. The package
depends on ``bonfire.models`` alone — no engine, dispatch, handler, event,
or CLI imports (constraint C9).

The target is ``bonfire.workflow`` (singular per ADR-001 line 50).
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# RED-phase import shim: the implementation does not exist yet. Tests still
# reference real names; each test fails via the autouse fixture while the
# ImportError is captured. Collection succeeds because the error is swallowed.
# ---------------------------------------------------------------------------

try:
    from bonfire.workflow import (
        WorkflowRegistry,
        debug,
        dual_scout,
        get_default_registry,
        spike,
        standard_build,
        triple_scout,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    WorkflowRegistry = None  # type: ignore[assignment,misc]
    debug = dual_scout = get_default_registry = None  # type: ignore[assignment]
    spike = standard_build = triple_scout = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    """Fail every test with the import error while bonfire.workflow is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.workflow not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_PUBLIC_FACTORIES: list[tuple[str, str]] = [
    ("standard_build", "STANDARD"),
    ("debug", "DEBUG"),
    ("dual_scout", "RESEARCH"),
    ("triple_scout", "RESEARCH"),
    ("spike", "RESEARCH"),
]


def _call(factory_name: str) -> WorkflowPlan:
    """Resolve and call a public factory by name through the package surface."""
    import bonfire.workflow as pkg

    factory: Callable[..., WorkflowPlan] = getattr(pkg, factory_name)
    return factory()


def _dummy_plan(name: str = "dummy") -> WorkflowPlan:
    return WorkflowPlan(
        name=name,
        workflow_type=WorkflowType.CUSTOM,
        stages=[StageSpec(name="only", agent_name="only", role="scout")],
    )


def _dummy_factory() -> WorkflowPlan:
    return _dummy_plan()


# ---------------------------------------------------------------------------
# 1. Package surface & import discipline
# ---------------------------------------------------------------------------


class TestPackageSurface:
    """Public surface of bonfire.workflow — names, callability, identity."""

    def test_target_is_singular_workflow(self) -> None:
        """Contract: the package is ``bonfire.workflow`` (singular per ADR-001)."""
        mod = importlib.import_module("bonfire.workflow")
        assert mod.__name__ == "bonfire.workflow"

    def test_import_standard_build(self) -> None:
        from bonfire.workflow import standard_build  # noqa: F401

    def test_import_debug(self) -> None:
        from bonfire.workflow import debug  # noqa: F401

    def test_import_dual_scout(self) -> None:
        from bonfire.workflow import dual_scout  # noqa: F401

    def test_import_triple_scout(self) -> None:
        from bonfire.workflow import triple_scout  # noqa: F401

    def test_import_spike(self) -> None:
        from bonfire.workflow import spike  # noqa: F401

    def test_import_get_default_registry(self) -> None:
        from bonfire.workflow import get_default_registry  # noqa: F401

    def test_import_workflow_registry(self) -> None:
        from bonfire.workflow import WorkflowRegistry  # noqa: F401

    def test_all_exports_present_in_dir(self) -> None:
        import bonfire.workflow as pkg

        expected = {
            "WorkflowRegistry",
            "debug",
            "dual_scout",
            "get_default_registry",
            "spike",
            "standard_build",
            "triple_scout",
        }
        assert expected.issubset(set(dir(pkg)))

    def test_dunder_all_is_complete(self) -> None:
        import bonfire.workflow as pkg

        assert hasattr(pkg, "__all__")
        assert set(pkg.__all__) >= {
            "WorkflowRegistry",
            "debug",
            "dual_scout",
            "get_default_registry",
            "spike",
            "standard_build",
            "triple_scout",
        }

    def test_all_public_factories_are_callable(self) -> None:
        import bonfire.workflow as pkg

        for name in ("standard_build", "debug", "dual_scout", "triple_scout", "spike"):
            assert callable(getattr(pkg, name)), f"bonfire.workflow.{name} is not callable"


# ---------------------------------------------------------------------------
# 2. Cross-cutting factory invariants — shared across every factory
# ---------------------------------------------------------------------------


class TestFactoryInvariants:
    """Every factory produces a valid, frozen, DAG-clean WorkflowPlan.

    Each test iterates across every public factory — one assertion per
    invariant, N factories deep. A single failure pinpoints both the
    invariant and the violating factory.
    """

    def test_returns_workflow_plan(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            assert isinstance(plan, WorkflowPlan), f"{factory_name} did not return a WorkflowPlan"

    def test_plan_is_frozen(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            with pytest.raises(ValidationError):
                plan.name = "mutated"  # type: ignore[misc]

    def test_stages_non_empty(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            assert len(plan.stages) >= 1, f"{factory_name} returned an empty stages list"

    def test_stage_names_unique(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            names = [s.name for s in plan.stages]
            assert len(names) == len(set(names)), (
                f"{factory_name} has duplicate stage names: {names}"
            )

    def test_no_self_bounce_depends_on(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            for stage in plan.stages:
                assert stage.name not in stage.depends_on, (
                    f"{factory_name}: stage {stage.name!r} depends on itself"
                )

    def test_no_self_bounce_on_gate_failure(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            for stage in plan.stages:
                assert stage.on_gate_failure != stage.name, (
                    f"{factory_name}: stage {stage.name!r} on_gate_failure points to itself"
                )

    def test_no_dangling_depends_on(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            names = {s.name for s in plan.stages}
            for stage in plan.stages:
                for dep in stage.depends_on:
                    assert dep in names, (
                        f"{factory_name}: {stage.name!r} depends_on unknown stage {dep!r}"
                    )

    def test_no_dangling_on_gate_failure(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            names = {s.name for s in plan.stages}
            for stage in plan.stages:
                if stage.on_gate_failure is not None:
                    assert stage.on_gate_failure in names, (
                        f"{factory_name}: {stage.name!r} on_gate_failure -> unknown "
                        f"{stage.on_gate_failure!r}"
                    )

    def test_workflow_type_matches_enum(self) -> None:
        for factory_name, wf_type in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            expected = getattr(WorkflowType, wf_type)
            assert plan.workflow_type == expected, (
                f"{factory_name}: workflow_type {plan.workflow_type!r} != {expected!r}"
            )

    def test_stages_are_stage_spec(self) -> None:
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            for stage in plan.stages:
                assert isinstance(stage, StageSpec), (
                    f"{factory_name}: stage {stage!r} is not a StageSpec"
                )

    def test_factory_name_matches_plan_name(self) -> None:
        """The default registry keys factories by plan name. Alignment matters."""
        for factory_name, _ in _PUBLIC_FACTORIES:
            plan = _call(factory_name)
            assert plan.name == factory_name, (
                f"factory {factory_name!r} produced plan named {plan.name!r}"
            )

    def test_factory_returns_fresh_instance(self) -> None:
        """Two calls must return equivalent but independent plans (no shared mutable state)."""
        for factory_name, _ in _PUBLIC_FACTORIES:
            first = _call(factory_name)
            second = _call(factory_name)
            assert [s.name for s in first.stages] == [s.name for s in second.stages], (
                f"{factory_name}: repeated calls produced divergent plans"
            )
            assert first is not second, (
                f"{factory_name}: factory appears to cache — builders must not be singletons"
            )


# ---------------------------------------------------------------------------
# 3. standard_build — reference 8-stage pipeline (per-stage assertions)
# ---------------------------------------------------------------------------


class TestStandardBuild:
    """standard_build() returns a valid 9-stage STANDARD WorkflowPlan.

    Flow: scout -> knight -> warrior -> prover -> sage_correction_bounce ->
    bard -> wizard -> merge_preflight -> herald.
    Knight writes RED, Warrior makes GREEN (max 3 iterations, no self-bounce).
    Prover bounces to Warrior on gate failure; on prover pass, the
    sage_correction_bounce stage runs (synthesizer-correction handler) and
    on gate failure also bounces to Warrior. Bard publishes, Wizard reviews
    (bounces to Warrior on rejection), MergePreflight runs full-suite
    pytest against the simulated merged tip, and Herald announces.
    """

    @pytest.fixture()
    def plan(self) -> WorkflowPlan:
        return _call("standard_build")

    def test_returns_workflow_plan(self, plan: WorkflowPlan) -> None:
        assert isinstance(plan, WorkflowPlan)

    def test_workflow_type_is_standard(self, plan: WorkflowPlan) -> None:
        assert plan.workflow_type == WorkflowType.STANDARD

    def test_has_nine_stages(self, plan: WorkflowPlan) -> None:
        assert len(plan.stages) == 9

    def test_stage_names_in_order(self, plan: WorkflowPlan) -> None:
        names = [s.name for s in plan.stages]
        assert names == [
            "scout",
            "knight",
            "warrior",
            "prover",
            "sage_correction_bounce",
            "bard",
            "wizard",
            "merge_preflight",
            "herald",
        ]

    def test_scout_role(self, plan: WorkflowPlan) -> None:
        scout = plan.stages[0]
        assert scout.role == "scout"

    def test_knight_role(self, plan: WorkflowPlan) -> None:
        knight = plan.stages[1]
        assert knight.role == "knight"

    def test_knight_has_completion_gate(self, plan: WorkflowPlan) -> None:
        knight = plan.stages[1]
        assert "completion" in knight.gates

    def test_warrior_role(self, plan: WorkflowPlan) -> None:
        warrior = plan.stages[2]
        assert warrior.role == "warrior"

    def test_warrior_has_test_pass_gate(self, plan: WorkflowPlan) -> None:
        warrior = plan.stages[2]
        assert "test_pass" in warrior.gates

    def test_warrior_max_iterations_is_three(self, plan: WorkflowPlan) -> None:
        warrior = plan.stages[2]
        assert warrior.max_iterations == 3

    def test_warrior_no_on_gate_failure(self, plan: WorkflowPlan) -> None:
        """Regression guard: warrior must NOT carry on_gate_failure to itself."""
        warrior = plan.stages[2]
        assert warrior.on_gate_failure is None

    def test_warrior_depends_on_knight(self, plan: WorkflowPlan) -> None:
        warrior = plan.stages[2]
        assert "knight" in warrior.depends_on

    def test_prover_role(self, plan: WorkflowPlan) -> None:
        prover = plan.stages[3]
        assert prover.role == "prover"

    def test_prover_has_verification_gate(self, plan: WorkflowPlan) -> None:
        prover = plan.stages[3]
        assert "verification" in prover.gates

    def test_prover_bounces_to_warrior(self, plan: WorkflowPlan) -> None:
        prover = plan.stages[3]
        assert prover.on_gate_failure == "warrior"

    def test_prover_depends_on_warrior(self, plan: WorkflowPlan) -> None:
        prover = plan.stages[3]
        assert "warrior" in prover.depends_on

    def test_sage_correction_bounce_name(self, plan: WorkflowPlan) -> None:
        stage = plan.stages[4]
        assert stage.name == "sage_correction_bounce"

    def test_sage_correction_bounce_role(self, plan: WorkflowPlan) -> None:
        """The synthesizer-correction stage carries the synthesizer role."""
        stage = plan.stages[4]
        assert stage.role == "synthesizer"

    def test_sage_correction_bounce_handler_name(self, plan: WorkflowPlan) -> None:
        stage = plan.stages[4]
        assert stage.handler_name == "sage_correction_bounce"

    def test_sage_correction_bounce_has_resolved_gate(self, plan: WorkflowPlan) -> None:
        stage = plan.stages[4]
        assert "sage_correction_resolved" in stage.gates

    def test_sage_correction_bounce_bounces_to_warrior(self, plan: WorkflowPlan) -> None:
        """On gate failure the synthesizer-correction stage bounces to
        Warrior, mirroring the prover bounce pattern."""
        stage = plan.stages[4]
        assert stage.on_gate_failure == "warrior"

    def test_sage_correction_bounce_depends_on_prover(self, plan: WorkflowPlan) -> None:
        stage = plan.stages[4]
        assert "prover" in stage.depends_on

    def test_bard_role(self, plan: WorkflowPlan) -> None:
        bard = plan.stages[5]
        assert bard.role == "bard"

    def test_bard_handler_name(self, plan: WorkflowPlan) -> None:
        bard = plan.stages[5]
        assert bard.handler_name == "bard"

    def test_bard_depends_on_sage_correction_bounce(self, plan: WorkflowPlan) -> None:
        """Bard's upstream dependency moves from prover to the
        synthesizer-correction stage once the latter is wired."""
        bard = plan.stages[5]
        assert "sage_correction_bounce" in bard.depends_on
        assert "prover" not in bard.depends_on

    def test_wizard_role(self, plan: WorkflowPlan) -> None:
        wizard = plan.stages[6]
        assert wizard.role == "wizard"

    def test_wizard_handler_name(self, plan: WorkflowPlan) -> None:
        wizard = plan.stages[6]
        assert wizard.handler_name == "wizard"

    def test_wizard_has_review_approval_gate(self, plan: WorkflowPlan) -> None:
        wizard = plan.stages[6]
        assert "review_approval" in wizard.gates

    def test_wizard_bounces_to_warrior(self, plan: WorkflowPlan) -> None:
        wizard = plan.stages[6]
        assert wizard.on_gate_failure == "warrior"

    def test_wizard_depends_on_bard(self, plan: WorkflowPlan) -> None:
        wizard = plan.stages[6]
        assert "bard" in wizard.depends_on

    def test_merge_preflight_role(self, plan: WorkflowPlan) -> None:
        preflight = plan.stages[7]
        assert preflight.role == "verifier"

    def test_merge_preflight_handler_name(self, plan: WorkflowPlan) -> None:
        preflight = plan.stages[7]
        assert preflight.handler_name == "merge_preflight"

    def test_merge_preflight_depends_on_wizard(self, plan: WorkflowPlan) -> None:
        preflight = plan.stages[7]
        assert "wizard" in preflight.depends_on

    def test_herald_role(self, plan: WorkflowPlan) -> None:
        herald = plan.stages[8]
        assert herald.role == "herald"

    def test_herald_handler_name(self, plan: WorkflowPlan) -> None:
        herald = plan.stages[8]
        assert herald.handler_name == "herald"

    def test_herald_depends_on_merge_preflight(self, plan: WorkflowPlan) -> None:
        """herald.depends_on stays rewired to ['merge_preflight']."""
        herald = plan.stages[8]
        assert "merge_preflight" in herald.depends_on

    def test_plan_is_frozen(self, plan: WorkflowPlan) -> None:
        with pytest.raises(ValidationError):
            plan.name = "mutated"  # type: ignore[misc]

    def test_dag_validation_passes(self) -> None:
        """Construction itself must not raise — the DAG is valid."""
        plan = _call("standard_build")
        assert plan is not None

    def test_no_parallel_groups(self, plan: WorkflowPlan) -> None:
        """standard_build is a linear pipeline — no stages run in parallel."""
        groups = {s.parallel_group for s in plan.stages if s.parallel_group is not None}
        assert groups == set()


# ---------------------------------------------------------------------------
# 4. debug — minimal 2-stage workflow
# ---------------------------------------------------------------------------


class TestDebug:
    """debug() returns a minimal scout -> warrior plan with no gates."""

    @pytest.fixture()
    def plan(self) -> WorkflowPlan:
        return _call("debug")

    def test_returns_workflow_plan(self, plan: WorkflowPlan) -> None:
        assert isinstance(plan, WorkflowPlan)

    def test_workflow_type_is_debug(self, plan: WorkflowPlan) -> None:
        assert plan.workflow_type == WorkflowType.DEBUG

    def test_has_two_stages(self, plan: WorkflowPlan) -> None:
        assert len(plan.stages) == 2

    def test_stage_names(self, plan: WorkflowPlan) -> None:
        names = [s.name for s in plan.stages]
        assert "scout" in names
        assert "warrior" in names

    def test_no_gates(self, plan: WorkflowPlan) -> None:
        for stage in plan.stages:
            assert stage.gates == []

    def test_no_bounce_back(self, plan: WorkflowPlan) -> None:
        for stage in plan.stages:
            assert stage.on_gate_failure is None

    def test_warrior_depends_on_scout(self, plan: WorkflowPlan) -> None:
        warrior = next(s for s in plan.stages if s.role == "warrior")
        scout = next(s for s in plan.stages if s.role == "scout")
        assert scout.name in warrior.depends_on


# ---------------------------------------------------------------------------
# 5. dual_scout — 2 parallel scouts + sage
# ---------------------------------------------------------------------------


class TestDualScout:
    """dual_scout() returns a research plan with 2 scouts and a sage."""

    @pytest.fixture()
    def plan(self) -> WorkflowPlan:
        return _call("dual_scout")

    def test_returns_workflow_plan(self, plan: WorkflowPlan) -> None:
        assert isinstance(plan, WorkflowPlan)

    def test_workflow_type_is_research(self, plan: WorkflowPlan) -> None:
        assert plan.workflow_type == WorkflowType.RESEARCH

    def test_has_two_scouts(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        assert len(scouts) == 2

    def test_scouts_share_parallel_group(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        groups = {s.parallel_group for s in scouts}
        assert len(groups) == 1
        assert None not in groups

    def test_has_sage_stage(self, plan: WorkflowPlan) -> None:
        sages = [s for s in plan.stages if s.role == "sage"]
        assert len(sages) == 1

    def test_sage_depends_on_both_scouts(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        sage = next(s for s in plan.stages if s.role == "sage")
        scout_names = {s.name for s in scouts}
        assert set(sage.depends_on) == scout_names


# ---------------------------------------------------------------------------
# 6. triple_scout — 3 parallel scouts + sage
# ---------------------------------------------------------------------------


class TestTripleScout:
    """triple_scout() returns a research plan with 3 scouts and a sage."""

    @pytest.fixture()
    def plan(self) -> WorkflowPlan:
        return _call("triple_scout")

    def test_returns_workflow_plan(self, plan: WorkflowPlan) -> None:
        assert isinstance(plan, WorkflowPlan)

    def test_workflow_type_is_research(self, plan: WorkflowPlan) -> None:
        assert plan.workflow_type == WorkflowType.RESEARCH

    def test_has_three_scouts(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        assert len(scouts) == 3

    def test_scouts_share_parallel_group(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        groups = {s.parallel_group for s in scouts}
        assert len(groups) == 1
        assert None not in groups

    def test_has_sage_stage(self, plan: WorkflowPlan) -> None:
        sages = [s for s in plan.stages if s.role == "sage"]
        assert len(sages) == 1

    def test_sage_depends_on_all_three_scouts(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        sage = next(s for s in plan.stages if s.role == "sage")
        scout_names = {s.name for s in scouts}
        assert len(scout_names) == 3
        assert set(sage.depends_on) == scout_names


# ---------------------------------------------------------------------------
# 7. spike — research plan, no implementation
# ---------------------------------------------------------------------------


class TestSpike:
    """spike() returns a valid research plan with no implementation stages."""

    @pytest.fixture()
    def plan(self) -> WorkflowPlan:
        return _call("spike")

    def test_returns_workflow_plan(self, plan: WorkflowPlan) -> None:
        assert isinstance(plan, WorkflowPlan)

    def test_workflow_type_is_research(self, plan: WorkflowPlan) -> None:
        assert plan.workflow_type == WorkflowType.RESEARCH

    def test_has_scouts(self, plan: WorkflowPlan) -> None:
        scouts = [s for s in plan.stages if s.role == "scout"]
        assert len(scouts) >= 2

    def test_no_warrior_stage(self, plan: WorkflowPlan) -> None:
        """Spike is research only — no implementation stages."""
        warriors = [s for s in plan.stages if s.role == "warrior"]
        assert len(warriors) == 0

    def test_no_knight_stage(self, plan: WorkflowPlan) -> None:
        """Spike is research only — no TDD stages."""
        knights = [s for s in plan.stages if s.role == "knight"]
        assert len(knights) == 0


# ---------------------------------------------------------------------------
# 8. Parallel-scout topology — shared across research factories
# ---------------------------------------------------------------------------


class TestParallelScoutTopology:
    """Each research factory shares its scouts in a single parallel group."""

    @pytest.mark.parametrize("factory_name", ["dual_scout", "triple_scout", "spike"])
    def test_scouts_share_single_parallel_group(self, factory_name: str) -> None:
        plan = _call(factory_name)
        scouts = [s for s in plan.stages if s.role == "scout"]
        groups = {s.parallel_group for s in scouts}
        assert len(groups) == 1
        assert None not in groups

    @pytest.mark.parametrize("factory_name", ["dual_scout", "triple_scout", "spike"])
    def test_sage_depends_on_every_scout(self, factory_name: str) -> None:
        plan = _call(factory_name)
        scouts = [s for s in plan.stages if s.role == "scout"]
        sages = [s for s in plan.stages if s.role == "sage"]
        assert len(sages) == 1
        scout_names = {s.name for s in scouts}
        assert set(sages[0].depends_on) == scout_names

    @pytest.mark.parametrize("factory_name", ["dual_scout", "triple_scout", "spike"])
    def test_sage_is_not_in_parallel_group(self, factory_name: str) -> None:
        plan = _call(factory_name)
        sage = next(s for s in plan.stages if s.role == "sage")
        assert sage.parallel_group is None


# ---------------------------------------------------------------------------
# 9. WorkflowRegistry semantics
# ---------------------------------------------------------------------------


class TestWorkflowRegistry:
    """WorkflowRegistry: register, get, list, membership, len, repr, errors."""

    def test_register_then_get_roundtrip(self) -> None:
        reg = WorkflowRegistry()
        reg.register("alpha", _dummy_factory)
        assert reg.get("alpha") is _dummy_factory

    def test_duplicate_register_raises_value_error(self) -> None:
        reg = WorkflowRegistry()
        reg.register("beta", _dummy_factory)
        with pytest.raises(ValueError, match="beta"):
            reg.register("beta", _dummy_factory)

    def test_get_missing_raises_key_error(self) -> None:
        reg = WorkflowRegistry()
        with pytest.raises(KeyError):
            reg.get("nope")

    def test_key_error_message_lists_available(self) -> None:
        reg = WorkflowRegistry()
        reg.register("zeta", _dummy_factory)
        with pytest.raises(KeyError) as exc:
            reg.get("missing")
        assert "zeta" in str(exc.value)

    def test_list_names_empty_by_default(self) -> None:
        reg = WorkflowRegistry()
        assert reg.list_names() == []

    def test_list_names_reflects_registration(self) -> None:
        reg = WorkflowRegistry()
        reg.register("a", _dummy_factory)
        reg.register("b", _dummy_factory)
        assert sorted(reg.list_names()) == ["a", "b"]

    def test_contains_membership(self) -> None:
        reg = WorkflowRegistry()
        reg.register("gamma", _dummy_factory)
        assert "gamma" in reg
        assert "delta" not in reg

    def test_len_tracks_registrations(self) -> None:
        reg = WorkflowRegistry()
        assert len(reg) == 0
        reg.register("one", _dummy_factory)
        assert len(reg) == 1
        reg.register("two", _dummy_factory)
        assert len(reg) == 2

    def test_repr_includes_class_name(self) -> None:
        reg = WorkflowRegistry()
        reg.register("x", _dummy_factory)
        assert "WorkflowRegistry" in repr(reg)

    def test_registered_factory_is_invokable(self) -> None:
        reg = WorkflowRegistry()
        reg.register("callable", _dummy_factory)
        plan = reg.get("callable")()
        assert isinstance(plan, WorkflowPlan)

    def test_registry_accepts_lambdas(self) -> None:
        reg = WorkflowRegistry()
        reg.register("lam", lambda: _dummy_plan("lam"))
        plan = reg.get("lam")()
        assert plan.name == "lam"

    def test_duplicate_rejected_even_across_factories(self) -> None:
        """Duplicate names are rejected regardless of whether the factory object matches."""
        reg = WorkflowRegistry()
        reg.register("dup", _dummy_factory)

        def _other_factory() -> WorkflowPlan:
            return _dummy_plan("other")

        with pytest.raises(ValueError):
            reg.register("dup", _other_factory)


# ---------------------------------------------------------------------------
# 10. get_default_registry — exactly five built-in factories, isolated instances
# ---------------------------------------------------------------------------


class TestGetDefaultRegistry:
    """get_default_registry() returns a populated WorkflowRegistry instance.

    Public v0.1 registers EXACTLY five factories: standard_build, debug,
    dual_scout, triple_scout, spike. The private ``project_strategist`` is
    deferred — it depends on the Strategist handler, not in scope here.
    """

    def test_returns_workflow_registry(self) -> None:
        reg = get_default_registry()
        assert isinstance(reg, WorkflowRegistry)

    def test_has_standard_build(self) -> None:
        reg = get_default_registry()
        assert callable(reg.get("standard_build"))

    def test_has_debug(self) -> None:
        reg = get_default_registry()
        assert callable(reg.get("debug"))

    def test_has_dual_scout(self) -> None:
        reg = get_default_registry()
        assert callable(reg.get("dual_scout"))

    def test_has_triple_scout(self) -> None:
        reg = get_default_registry()
        assert callable(reg.get("triple_scout"))

    def test_has_spike(self) -> None:
        reg = get_default_registry()
        assert callable(reg.get("spike"))

    def test_exactly_five_registered(self) -> None:
        reg = get_default_registry()
        assert len(reg.list_names()) == 5

    def test_registered_names_exact_set(self) -> None:
        """Public v0.1 registers exactly these five factories — no more, no less."""
        reg = get_default_registry()
        assert set(reg.list_names()) == {
            "standard_build",
            "debug",
            "dual_scout",
            "triple_scout",
            "spike",
        }

    def test_project_strategist_not_registered(self) -> None:
        """project_strategist is deferred and MUST NOT appear in the default registry."""
        reg = get_default_registry()
        assert "project_strategist" not in reg

    def test_each_default_factory_returns_valid_plan(self) -> None:
        reg = get_default_registry()
        for name in reg.list_names():
            plan = reg.get(name)()
            assert isinstance(plan, WorkflowPlan)

    def test_fresh_instance_per_call(self) -> None:
        """Mutation of one default registry must not leak into the next call."""
        first = get_default_registry()
        second = get_default_registry()
        assert first is not second

    def test_mutation_does_not_leak(self) -> None:
        first = get_default_registry()
        first.register("_probe", _dummy_factory)
        second = get_default_registry()
        assert "_probe" not in second

    def test_default_factories_round_trip_through_registry(self) -> None:
        """registry.get(name)() must build the same plan as calling the factory directly."""
        reg = get_default_registry()
        for name in ("standard_build", "debug", "dual_scout", "triple_scout", "spike"):
            from_registry = reg.get(name)()
            direct = _call(name)
            assert from_registry.name == direct.name
            assert from_registry.workflow_type == direct.workflow_type
            assert [s.name for s in from_registry.stages] == [s.name for s in direct.stages]


# ---------------------------------------------------------------------------
# 11. Registry smoke — every default plan is DAG-clean
# ---------------------------------------------------------------------------


class TestRegistryEndToEnd:
    """Smoke tests proving registry -> factory -> plan holds for every default entry."""

    def test_every_default_plan_has_unique_stage_names(self) -> None:
        reg = get_default_registry()
        for name in reg.list_names():
            plan = reg.get(name)()
            stage_names = [s.name for s in plan.stages]
            assert len(stage_names) == len(set(stage_names)), (
                f"default factory {name!r} produced duplicate stage names"
            )

    def test_every_default_plan_has_valid_workflow_type(self) -> None:
        reg = get_default_registry()
        for name in reg.list_names():
            plan = reg.get(name)()
            assert plan.workflow_type in set(WorkflowType)


# ---------------------------------------------------------------------------
# 12. Dependency constraints — C9: workflow/ depends ONLY on bonfire.models
# ---------------------------------------------------------------------------


class TestDependencyConstraints:
    """Verify workflow/ depends ONLY on bonfire.models.

    Mirrors the private-side C9 constraint: workflow factories are pure
    data producers. They must never pull in engine, dispatch, handlers,
    events, or cli.
    """

    FORBIDDEN_IMPORTS = [
        "bonfire.engine",
        "bonfire.dispatch",
        "bonfire.handlers",
        "bonfire.events",
        "bonfire.cli",
    ]

    @pytest.fixture(autouse=True)
    def _load_workflow_package(self) -> None:
        """Force-load workflow and its submodules so imports are resolved."""
        import contextlib

        import bonfire.workflow  # noqa: F401

        for submod in ("registry", "standard", "research"):
            with contextlib.suppress(ImportError):
                importlib.import_module(f"bonfire.workflow.{submod}")

    @pytest.mark.parametrize("forbidden", FORBIDDEN_IMPORTS)
    def test_workflow_does_not_import_forbidden(self, forbidden: str) -> None:
        """workflow/ must not depend on engine, dispatch, handlers, events, cli."""
        workflow_modules = {
            name: mod
            for name, mod in sys.modules.items()
            if name.startswith("bonfire.workflow") and mod is not None
        }
        for mod_name, mod in workflow_modules.items():
            for attr_val in vars(mod).values():
                origin = getattr(attr_val, "__module__", None)
                if origin and origin.startswith(forbidden):
                    pytest.fail(
                        f"{mod_name} binds {attr_val!r} from {origin} "
                        f"(forbidden prefix {forbidden!r}, violates C9)"
                    )
