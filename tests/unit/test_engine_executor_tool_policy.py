"""CANONICAL RED — BON-337 (Sage-merged) — ``StageExecutor(tool_policy=...)``.

Merged from Knight-A (adversarial) and Knight-B (conservative contract).
Sibling to the pre-existing ``test_engine_executor.py`` — does NOT modify
that file. The existing ``test_rejects_compiler_kwarg`` sentinel in
``test_engine_executor.py`` MUST remain green; this file also independently
re-asserts that invariant with the new ``tool_policy=`` kwarg in play.

Sage decisions asserted (BON-337 unified Sage doc, 2026-04-18):
    D3 (from BON-334): ``compiler=`` kwarg rejected.
    D5: Constructor accepts ``tool_policy: ToolPolicy | None = None``,
        keyword-only. Stored as ``self._tool_policy``. ``__slots__``
        gains ``"_tool_policy"`` alphabetically (between ``_project_root``
        and ``_vault_advisor``).
    D6: Three-tier ratchet at ``_dispatch_backend`` (executor.py:255-271):
            if self._tool_policy is None or not stage.role:
                role_tools: list[str] = []
            else:
                role_tools = self._tool_policy.tools_for(stage.role)
        Passed to ``DispatchOptions(..., tools=role_tools, role=stage.role)``.

Sage ambiguity locks referenced here:
    AMBIG #1 — This is a SIBLING test file (not an append to
               ``test_engine_executor.py``). Cleaner diff, easier revert.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from bonfire.dispatch.result import DispatchResult
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions


# ---------------------------------------------------------------------------
# Mocks — aligned with test_engine_executor.py style
# ---------------------------------------------------------------------------


class _MockBackend:
    """Default-OK backend with call recording."""

    def __init__(self, *, fail_agents: set[str] | None = None) -> None:
        self.fail_agents = fail_agents or set()
        self.calls: list[tuple[Envelope, DispatchOptions]] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append((envelope, options))
        if envelope.agent_name in self.fail_agents:
            return envelope.with_error(
                ErrorDetail(error_type="agent", message=f"{envelope.agent_name} failed")
            )
        return envelope.with_result(f"result from {envelope.agent_name}", cost_usd=0.01)

    async def health_check(self) -> bool:
        return True


def _stage(
    name: str = "s",
    agent_name: str | None = None,
    *,
    role: str = "",
    handler_name: str | None = None,
    max_iterations: int = 1,
) -> StageSpec:
    return StageSpec(
        name=name,
        agent_name=agent_name if agent_name is not None else f"{name}-agent",
        role=role,
        handler_name=handler_name,
        max_iterations=max_iterations,
    )


def _plan(*stages: StageSpec, budget: float = 10.0) -> WorkflowPlan:
    return WorkflowPlan(
        name="executor-tool-policy-test",
        workflow_type=WorkflowType.STANDARD,
        stages=list(stages),
        budget_usd=budget,
    )


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def config() -> PipelineConfig:
    return PipelineConfig()


# ===========================================================================
# 1. Constructor — kwarg acceptance, None default, attribute storage (D5)
# ===========================================================================


class TestConstructorAcceptsToolPolicy:
    """Sage D5 — additive kwarg; ``None`` default preserves every existing caller."""

    def test_default_tool_policy_is_none(self, bus: EventBus, config: PipelineConfig) -> None:
        """Sage D5 — no kwarg → ``self._tool_policy is None``."""
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        assert ex._tool_policy is None

    def test_accepts_tool_policy_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        """Sage D5 — ``tool_policy=`` kwarg accepted; stored on ``self._tool_policy``."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        policy = DefaultToolPolicy()
        ex = StageExecutor(
            backend=_MockBackend(), bus=bus, config=config, tool_policy=policy
        )
        assert ex._tool_policy is policy

    def test_accepts_tool_policy_none_explicit(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D5 — explicit ``tool_policy=None`` still valid."""
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, tool_policy=None)
        assert ex._tool_policy is None

    def test_tool_policy_kwarg_is_keyword_only(self) -> None:
        """Sage D5 — constructor is kw-only; ``tool_policy`` must follow suit."""
        from bonfire.engine.executor import StageExecutor

        sig = inspect.signature(StageExecutor.__init__)
        tp = sig.parameters.get("tool_policy")
        assert tp is not None
        assert tp.kind == inspect.Parameter.KEYWORD_ONLY

    def test_tool_policy_param_default_is_none(self) -> None:
        """Sage D5 — default value is ``None``."""
        from bonfire.engine.executor import StageExecutor

        sig = inspect.signature(StageExecutor.__init__)
        tp = sig.parameters.get("tool_policy")
        assert tp is not None
        assert tp.default is None


class TestSlotsEntry:
    """Sage D5 — ``__slots__`` gains ``"_tool_policy"`` alphabetically."""

    def test_tool_policy_in_slots(self) -> None:
        """Sage D5 lockdown — ``"_tool_policy"`` is in ``__slots__``."""
        from bonfire.engine.executor import StageExecutor

        assert "_tool_policy" in StageExecutor.__slots__

    def test_slots_ordering_alphabetical(self) -> None:
        """Sage D5 — ``_tool_policy`` sits alphabetically between
        ``_project_root`` and ``_vault_advisor``."""
        from bonfire.engine.executor import StageExecutor

        slots = list(StageExecutor.__slots__)
        assert "_project_root" in slots
        assert "_tool_policy" in slots
        assert "_vault_advisor" in slots
        tp_idx = slots.index("_tool_policy")
        pr_idx = slots.index("_project_root")
        va_idx = slots.index("_vault_advisor")
        assert pr_idx < tp_idx < va_idx

    def test_cannot_set_extra_attributes_under_slots(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """``__slots__`` enforcement: extra attributes raise ``AttributeError``."""
        from bonfire.engine.executor import StageExecutor

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        with pytest.raises(AttributeError):
            ex._not_a_slot = "x"  # type: ignore[attr-defined]


# ===========================================================================
# 2. D3 sentinel — ``compiler=`` still rejected (BON-334 lockdown)
# ===========================================================================


class TestCompilerKwargStillRejected:
    """Sage D3 lockdown from BON-334 must survive BON-337's additive change."""

    def test_rejects_compiler_kwarg_still_holds(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D3 — ``compiler=`` MUST still raise ``TypeError``."""
        from bonfire.engine.executor import StageExecutor

        with pytest.raises(TypeError):
            StageExecutor(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                compiler=object(),  # type: ignore[call-arg]
            )

    def test_compiler_plus_tool_policy_still_raises(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Passing BOTH ``tool_policy`` AND ``compiler`` MUST still raise.

        ``tool_policy`` is accepted; ``compiler`` is not. The presence of the
        new accepted kwarg must not silently swallow the old rejected one.
        """
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        with pytest.raises(TypeError):
            StageExecutor(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                tool_policy=DefaultToolPolicy(),
                compiler=object(),  # type: ignore[call-arg]
            )

    def test_unrelated_unknown_kwarg_still_raises(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Random unknown kwargs remain rejected — not absorbed by ``**kwargs``."""
        from bonfire.engine.executor import StageExecutor

        with pytest.raises(TypeError):
            StageExecutor(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                not_a_real_kwarg=object(),  # type: ignore[call-arg]
            )


# ===========================================================================
# 3. Three-tier ratchet at ``_dispatch_backend`` (D6) — backend-observed
# ===========================================================================


class TestThreeTierRatchetBackendObserved:
    """Sage D6 — observe ``DispatchOptions`` landed on a real backend.

    Uses the concrete ``_MockBackend`` (no monkeypatch) — the envelope and
    options the backend receives are the source of truth.
    """

    async def test_no_policy_yields_empty_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — ``tool_policy is None`` → ``opts.tools == []`` (permissive)."""
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config)  # no tool_policy
        stage = _stage(name="s1", agent_name="warrior-agent", role="warrior")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        assert backend.calls
        _, opts = backend.calls[0]
        assert opts.tools == []
        # Sage D6 — role still propagates even when policy absent.
        assert opts.role == "warrior"

    async def test_policy_plus_empty_role_yields_empty_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — policy wired + ``stage.role == ""`` → ``tools == []``."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name="anyone", role="")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == ""

    async def test_policy_plus_unmapped_role_yields_empty_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — policy wired + unmapped role → ``tools == []`` (strict-by-default)."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name="x", role="gardener")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == []
        # Sage D6 — role propagates even when it's unmapped.
        assert opts.role == "gardener"

    async def test_policy_plus_mapped_role_yields_floor_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — policy wired + mapped role → floor list passed verbatim."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name="warrior-agent", role="warrior")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts.role == "warrior"

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            ("scout", ["Read", "Write", "Grep", "WebSearch", "WebFetch"]),
            ("knight", ["Read", "Write", "Edit", "Grep", "Glob"]),
            ("prover", ["Read", "Bash", "Grep", "Glob"]),
            ("sage", ["Read", "Write", "Grep"]),
            ("bard", ["Read", "Write", "Grep", "Glob"]),
            ("wizard", ["Read", "Grep", "Glob"]),
            ("herald", ["Read", "Grep"]),
        ],
    )
    async def test_all_mapped_roles_yield_floor_tools(
        self,
        bus: EventBus,
        config: PipelineConfig,
        role: str,
        expected: list[str],
    ) -> None:
        """Every canonical role → its floor list at the dispatch seam."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name=f"{role}-agent", role=role)
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == expected
        assert opts.role == role


# ===========================================================================
# 4. Three-tier ratchet via monkeypatched ``execute_with_retry`` (D6)
# ===========================================================================


class TestThreeTierRatchetRunnerObserved:
    """Same ratchet, observed by patching ``execute_with_retry`` — verifies
    the options object reaches the dispatch runner unaltered (D6)."""

    async def test_policy_and_role_mapped_passes_floor(
        self, bus: EventBus, config: PipelineConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sage D6 — policy wired + role mapped → ``DispatchOptions.tools`` is floor."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        captured: dict[str, Any] = {}

        async def fake_execute_with_retry(
            backend: Any, env: Envelope, options: DispatchOptions, **kwargs: Any
        ) -> DispatchResult:
            captured["options"] = options
            return DispatchResult(
                envelope=env.with_result(result="ok", cost_usd=0.0),
                duration_seconds=0.0,
                retries=0,
                cost_usd=0.0,
            )

        monkeypatch.setattr(
            "bonfire.engine.executor.execute_with_retry", fake_execute_with_retry
        )

        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            tool_policy=DefaultToolPolicy(),
        )
        stage = _stage(name="s", agent_name="warrior-agent", role="warrior")
        plan = _plan(stage)
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="sid"
        )

        opts = captured["options"]
        assert opts.tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts.role == "warrior"

    async def test_policy_wired_role_scout_passes_scout_floor(
        self, bus: EventBus, config: PipelineConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sage D3 + D6 — scout role → scout floor reaches the runner."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        captured: dict[str, Any] = {}

        async def fake_execute_with_retry(
            backend: Any, env: Envelope, options: DispatchOptions, **kwargs: Any
        ) -> DispatchResult:
            captured["options"] = options
            return DispatchResult(
                envelope=env.with_result(result="ok", cost_usd=0.0),
                duration_seconds=0.0,
                retries=0,
                cost_usd=0.0,
            )

        monkeypatch.setattr(
            "bonfire.engine.executor.execute_with_retry", fake_execute_with_retry
        )

        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            tool_policy=DefaultToolPolicy(),
        )
        stage = _stage(name="s", agent_name="scout-agent", role="scout")
        plan = _plan(stage)
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="sid"
        )

        assert captured["options"].tools == [
            "Read", "Write", "Grep", "WebSearch", "WebFetch",
        ]
        assert captured["options"].role == "scout"


# ===========================================================================
# 5. Custom ``ToolPolicy`` (protocol-structural) is honored at dispatch (D5)
# ===========================================================================


class TestCustomToolPolicyImpl:
    """Sage D2 — ``ToolPolicy`` is structural; custom impls are honored."""

    async def test_custom_policy_returns_custom_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """User-defined policies can override the floor."""
        from bonfire.engine.executor import StageExecutor

        class _CustomPolicy:
            def tools_for(self, role: str) -> list[str]:
                return ["OnlyRead"] if role == "warrior" else []

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=_CustomPolicy()
        )
        stage = _stage(name="s1", agent_name="w", role="warrior")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == ["OnlyRead"]

    async def test_custom_policy_receiving_role_verbatim(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D5 + D6 — executor passes ``stage.role`` verbatim to ``policy.tools_for``."""
        from bonfire.engine.executor import StageExecutor

        seen_roles: list[str] = []

        class _SpyPolicy:
            def tools_for(self, role: str) -> list[str]:
                seen_roles.append(role)
                return ["Read"]

        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config, tool_policy=_SpyPolicy())
        stage = _stage(name="s1", agent_name="x", role="custom-role-42")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        assert seen_roles == ["custom-role-42"]

    async def test_custom_policy_not_called_when_role_empty(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 short-circuit — ``not stage.role`` → policy is NOT called."""
        from bonfire.engine.executor import StageExecutor

        call_count = 0

        class _CountingPolicy:
            def tools_for(self, role: str) -> list[str]:
                nonlocal call_count
                call_count += 1
                return ["Read"]

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=_CountingPolicy()
        )
        stage = _stage(name="s1", agent_name="x", role="")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        assert call_count == 0


# ===========================================================================
# 6. Handler-dispatch path bypasses ``tool_policy`` (D6)
# ===========================================================================


class TestToolPolicyIrrelevantForHandler:
    """Handler-routed stages bypass the backend; tool policy is NOT consulted."""

    async def test_handler_stage_does_not_consult_policy(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """When ``stage.handler_name`` is set, the policy is never touched."""
        from bonfire.engine.executor import StageExecutor

        class _SpyPolicy:
            def __init__(self) -> None:
                self.invocations = 0

            def tools_for(self, role: str) -> list[str]:
                self.invocations += 1
                return ["Read"]

        class _FakeHandler:
            async def handle(
                self, stage: StageSpec, envelope: Envelope, prior_results: dict[str, str]
            ) -> Envelope:
                return envelope.with_result("handled", cost_usd=0.0)

        spy = _SpyPolicy()
        ex = StageExecutor(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            handlers={"h1": _FakeHandler()},  # type: ignore[dict-item]
            tool_policy=spy,
        )
        stage = _stage(name="s1", agent_name="x", role="warrior", handler_name="h1")
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        assert result.status == TaskStatus.COMPLETED
        assert spy.invocations == 0


# ===========================================================================
# 7. Policy exception handling — never-raise discipline (C19)
# ===========================================================================


class TestPolicyNeverRaises:
    """If a custom policy raises, executor's C19 discipline catches it."""

    async def test_raising_policy_does_not_leak_exception(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """A buggy ``ToolPolicy.tools_for`` raising MUST NOT crash the executor."""
        from bonfire.engine.executor import StageExecutor

        class _ExplodingPolicy:
            def tools_for(self, role: str) -> list[str]:
                raise RuntimeError("policy exploded")

        ex = StageExecutor(
            backend=_MockBackend(), bus=bus, config=config, tool_policy=_ExplodingPolicy()
        )
        stage = _stage(name="s1", agent_name="w", role="warrior")
        result = await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        assert isinstance(result, Envelope)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None


# ===========================================================================
# 8. Adversarial stage.role values travel through faithfully (D6)
# ===========================================================================


class TestAdversarialStageRoleAtExecutor:
    """At the executor seam, adversarial role values travel through faithfully."""

    async def test_whitespace_role_hits_policy_via_truthy_string(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — ``"   "`` is truthy → policy IS called, returns ``[]``."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name="x", role="   ")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == "   "  # propagated verbatim

    async def test_trailing_whitespace_role_unmapped_tools_empty(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """``"knight "`` (trailing space) is truthy but unmapped — empty tools."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name="x", role="knight ")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == "knight "

    async def test_unicode_role_propagates_and_is_unmapped(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Unicode ``stage.role`` hits policy, returns ``[]``, propagates verbatim."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        stage = _stage(name="s1", agent_name="x", role="ニンジャ")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == "ニンジャ"


# ===========================================================================
# 9. DispatchOptions type contract at the seam
# ===========================================================================


class TestDispatchOptionsContract:
    """The executor builds a ``DispatchOptions`` with all fields populated correctly."""

    async def test_dispatch_options_type_is_dispatch_options(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """The options object handed to ``backend.execute`` is ``DispatchOptions``."""
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage(name="s1", agent_name="x", role="warrior")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        assert isinstance(opts, DispatchOptions)

    async def test_dispatch_options_is_frozen(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """The options object is frozen — mutation attempts raise."""
        from bonfire.engine.executor import StageExecutor

        backend = _MockBackend()
        ex = StageExecutor(backend=backend, bus=bus, config=config)
        stage = _stage(name="s1", agent_name="x", role="warrior")
        await ex.execute_single(
            stage=stage, prior_results={}, total_cost=0.0, plan=_plan(stage), session_id="sid"
        )
        _, opts = backend.calls[0]
        with pytest.raises(ValidationError):
            opts.tools = ["Bash"]  # type: ignore[misc]
