"""CANONICAL RED — BON-337 (Sage-merged) — ``PipelineEngine(tool_policy=...)``.

Merged from Knight-A (adversarial) and Knight-B (conservative contract).
Mirror of the executor tool-policy tests adapted for ``PipelineEngine``.
Sibling to the pre-existing ``test_engine_pipeline.py`` — does NOT modify
that file. Its ``test_rejects_compiler_kwarg`` sentinel MUST remain green;
this file also independently re-asserts that invariant.

Sage decisions asserted (BON-337 unified Sage doc, 2026-04-18):
    D3 (from BON-334): ``compiler=`` kwarg rejected.
    D5: Constructor accepts ``tool_policy: ToolPolicy | None = None``,
        keyword-only. Stored as ``self._tool_policy``. ``PipelineEngine``
        does NOT use ``__slots__``.
    D6: Three-tier ratchet at the backend branch of ``_execute_stage``
        (pipeline.py:486-504):
            if self._tool_policy is None or not spec.role:
                role_tools: list[str] = []
            else:
                role_tools = self._tool_policy.tools_for(spec.role)
        Passed to ``DispatchOptions(..., tools=role_tools, role=spec.role)``.

Sage ambiguity locks referenced here:
    AMBIG #1 — SIBLING test file (not an append to ``test_engine_pipeline.py``).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from bonfire.dispatch.result import DispatchResult
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Envelope, ErrorDetail
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.protocols import DispatchOptions


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class _MockBackend:
    """Default-OK backend with full call capture."""

    def __init__(self, *, fail_agents: set[str] | None = None) -> None:
        self.fail_agents = fail_agents or set()
        self.calls: list[tuple[Envelope, DispatchOptions]] = []

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.calls.append((envelope, options))
        if envelope.agent_name in self.fail_agents:
            return envelope.with_error(
                ErrorDetail(error_type="agent", message=f"{envelope.agent_name} failed")
            )
        return envelope.with_result(f"{envelope.agent_name} done", cost_usd=0.01)

    async def health_check(self) -> bool:
        return True


def _single_plan(*, role: str = "", agent_name: str = "s1") -> WorkflowPlan:
    return WorkflowPlan(
        name="pipeline-tool-policy-test",
        workflow_type=WorkflowType.STANDARD,
        stages=[StageSpec(name="s1", agent_name=agent_name, role=role)],
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


class TestPipelineConstructorAcceptsToolPolicy:
    """Sage D5 — mirror of StageExecutor; additive kwarg, backward compat."""

    def test_default_tool_policy_is_none(self, bus: EventBus, config: PipelineConfig) -> None:
        """Sage D5 — no kwarg → ``self._tool_policy is None``."""
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(backend=_MockBackend(), bus=bus, config=config)
        assert engine._tool_policy is None

    def test_accepts_tool_policy_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        """Sage D5 — ``tool_policy=`` stored on ``self._tool_policy``."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        policy = DefaultToolPolicy()
        engine = PipelineEngine(
            backend=_MockBackend(), bus=bus, config=config, tool_policy=policy
        )
        assert engine._tool_policy is policy

    def test_accepts_tool_policy_none_explicit(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D5 — explicit ``tool_policy=None`` still valid."""
        from bonfire.engine.pipeline import PipelineEngine

        engine = PipelineEngine(
            backend=_MockBackend(), bus=bus, config=config, tool_policy=None
        )
        assert engine._tool_policy is None

    def test_tool_policy_kwarg_is_keyword_only(self) -> None:
        """Sage D5 — constructor is kw-only; ``tool_policy`` is kw-only."""
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.__init__)
        tp = sig.parameters.get("tool_policy")
        assert tp is not None
        assert tp.kind == inspect.Parameter.KEYWORD_ONLY

    def test_tool_policy_param_default_is_none(self) -> None:
        """Sage D5 — default value is ``None``."""
        from bonfire.engine.pipeline import PipelineEngine

        sig = inspect.signature(PipelineEngine.__init__)
        tp = sig.parameters.get("tool_policy")
        assert tp is not None
        assert tp.default is None


# ===========================================================================
# 2. D3 sentinel — ``compiler=`` still rejected on ``PipelineEngine``
# ===========================================================================


class TestPipelineCompilerSentinel:
    """Sage D3 (BON-334) — ``compiler=`` kwarg rejected after D5's additive change."""

    def test_rejects_compiler_kwarg_still_holds(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D3 — ``compiler=`` MUST still raise ``TypeError``."""
        from bonfire.engine.pipeline import PipelineEngine

        with pytest.raises(TypeError):
            PipelineEngine(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                compiler=object(),  # type: ignore[call-arg]
            )

    def test_compiler_plus_tool_policy_still_raises(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Passing BOTH still raises for ``compiler=`` — it's not absorbed."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        with pytest.raises(TypeError):
            PipelineEngine(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                tool_policy=DefaultToolPolicy(),
                compiler=object(),  # type: ignore[call-arg]
            )

    def test_unrelated_unknown_kwarg_still_rejected(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Unknown kwargs aren't absorbed by ``**kwargs``."""
        from bonfire.engine.pipeline import PipelineEngine

        with pytest.raises(TypeError):
            PipelineEngine(
                backend=_MockBackend(),
                bus=bus,
                config=config,
                not_a_real_kwarg=object(),  # type: ignore[call-arg]
            )


# ===========================================================================
# 3. Three-tier ratchet at backend branch (D6) — backend-observed
# ===========================================================================


class TestPipelineRatchetBackendObserved:
    """Sage D6 — observe ``DispatchOptions`` landed on a real backend."""

    async def test_no_policy_yields_empty_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — ``tool_policy is None`` → empty tools (backward compat)."""
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(backend=backend, bus=bus, config=config)
        result = await engine.run(_single_plan(role="warrior", agent_name="warrior-agent"))
        assert result.success is True

        _, opts = backend.calls[0]
        assert opts.tools == []
        # Sage D6 — role propagates even when policy absent.
        assert opts.role == "warrior"

    async def test_policy_plus_empty_role_yields_empty_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — policy wired + ``spec.role == ""`` → empty tools."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        result = await engine.run(_single_plan(role="", agent_name="a"))
        assert result.success is True
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == ""

    async def test_policy_plus_unmapped_role_yields_empty_tools(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — policy wired + unmapped role → empty tools (strict-by-default)."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        result = await engine.run(_single_plan(role="gardener", agent_name="a"))
        assert result.success is True
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == "gardener"

    async def test_policy_plus_mapped_role_yields_floor(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 — policy wired + mapped role → floor propagates verbatim."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        result = await engine.run(_single_plan(role="warrior", agent_name="warrior-agent"))
        assert result.success is True
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
    async def test_all_mapped_roles_pipeline(
        self,
        bus: EventBus,
        config: PipelineConfig,
        role: str,
        expected: list[str],
    ) -> None:
        """Every canonical role → its floor list at the pipeline backend branch."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(_single_plan(role=role, agent_name=f"{role}-agent"))
        _, opts = backend.calls[0]
        assert opts.tools == expected
        assert opts.role == role


# ===========================================================================
# 4. Three-tier ratchet via monkeypatched ``execute_with_retry`` (D6)
# ===========================================================================


class TestPipelineRatchetRunnerObserved:
    """Same ratchet, observed by patching ``execute_with_retry``."""

    async def test_policy_and_role_mapped_passes_floor(
        self, bus: EventBus, config: PipelineConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sage D6 — policy wired + role mapped → tools = floor at the runner seam."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        captured: dict[str, Any] = {}

        async def fake_execute_with_retry(
            backend: Any, env: Envelope, options: DispatchOptions, **kwargs: Any
        ) -> DispatchResult:
            captured["options"] = options
            return DispatchResult(
                envelope=env.with_result("ok", cost_usd=0.0),
                duration_seconds=0.0,
                retries=0,
                cost_usd=0.0,
            )

        monkeypatch.setattr(
            "bonfire.engine.pipeline.execute_with_retry", fake_execute_with_retry
        )

        engine = PipelineEngine(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            tool_policy=DefaultToolPolicy(),
        )
        result = await engine.run(_single_plan(role="warrior", agent_name="warrior-agent"))
        assert result.success is True

        opts = captured["options"]
        assert opts.tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts.role == "warrior"


# ===========================================================================
# 5. Role propagation at pipeline seam (D6)
# ===========================================================================


class TestPipelineRolePropagation:
    """Sage D6 — pipeline backend branch propagates ``spec.role`` to DispatchOptions."""

    async def test_role_propagates(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(_single_plan(role="warrior", agent_name="warrior-agent"))
        _, opts = backend.calls[0]
        assert opts.role == "warrior"

    async def test_role_propagates_when_policy_none(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Even without a policy, ``spec.role`` still reaches ``DispatchOptions.role``."""
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(backend=backend, bus=bus, config=config)
        await engine.run(_single_plan(role="warrior", agent_name="warrior-agent"))
        _, opts = backend.calls[0]
        assert opts.role == "warrior"

    async def test_empty_role_propagates_as_empty(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Default ``spec.role == ""`` → ``opts.role == ""``."""
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(backend=backend, bus=bus, config=config)
        await engine.run(_single_plan(role="", agent_name="a"))
        _, opts = backend.calls[0]
        assert opts.role == ""


# ===========================================================================
# 6. Multi-stage ratchet — each stage independently policied
# ===========================================================================


class TestMultiStageRatchet:
    """Ratchet evaluates per-stage — no cross-stage contamination."""

    async def test_each_stage_independently_policied(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """A 3-stage plan: warrior / scout / unmapped — each gets its own floor."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        plan = WorkflowPlan(
            name="multi",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="a", agent_name="a", role="warrior"),
                StageSpec(name="b", agent_name="b", role="scout", depends_on=["a"]),
                StageSpec(name="c", agent_name="c", role="gardener", depends_on=["b"]),
            ],
        )

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(plan)

        assert len(backend.calls) == 3
        opts_by_name = {env.agent_name: opts for env, opts in backend.calls}

        assert opts_by_name["a"].tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts_by_name["a"].role == "warrior"

        assert opts_by_name["b"].tools == ["Read", "Write", "Grep", "WebSearch", "WebFetch"]
        assert opts_by_name["b"].role == "scout"

        # Unmapped — strict empty list, role still propagated.
        assert opts_by_name["c"].tools == []
        assert opts_by_name["c"].role == "gardener"

    async def test_cross_stage_options_are_independent(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Cross-stage isolation — ``DispatchOptions`` are frozen + fresh lists per call."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        plan = WorkflowPlan(
            name="two-warriors",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="a", agent_name="a", role="warrior"),
                StageSpec(name="b", agent_name="b", role="warrior", depends_on=["a"]),
            ],
        )
        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(plan)

        opts_a = backend.calls[0][1]
        opts_b = backend.calls[1][1]
        assert opts_a.tools == opts_b.tools

        # Pydantic frozen guarantees this raises — adversarial probe only.
        with pytest.raises(ValidationError):
            opts_a.tools = ["Bash"]  # type: ignore[misc]


# ===========================================================================
# 7. Parallel-group stages — ratchet evaluates per-stage concurrently
# ===========================================================================


class TestParallelGroupRatchet:
    """Parallel stages each get independent policy evaluation."""

    async def test_parallel_stages_each_get_own_floor(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        plan = WorkflowPlan(
            name="parallel-roles",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(name="s1", agent_name="s1", role="scout", parallel_group="g"),
                StageSpec(name="s2", agent_name="s2", role="knight", parallel_group="g"),
            ],
        )
        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(plan)

        assert len(backend.calls) == 2
        opts_by_name = {env.agent_name: opts for env, opts in backend.calls}
        assert opts_by_name["s1"].tools == ["Read", "Write", "Grep", "WebSearch", "WebFetch"]
        assert opts_by_name["s2"].tools == ["Read", "Write", "Edit", "Grep", "Glob"]


# ===========================================================================
# 8. Custom policy injection (protocol-structural)
# ===========================================================================


class TestPipelineCustomPolicy:
    """Duck-typed policies work at the pipeline seam."""

    async def test_custom_policy_injected_via_pipeline(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        calls: list[str] = []

        class _SpyPolicy:
            def tools_for(self, role: str) -> list[str]:
                calls.append(role)
                return ["CustomTool"]

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=_SpyPolicy()
        )
        await engine.run(_single_plan(role="my-role", agent_name="x"))
        assert calls == ["my-role"]
        _, opts = backend.calls[0]
        assert opts.tools == ["CustomTool"]

    async def test_custom_policy_not_called_for_empty_role(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D6 short-circuit at pipeline level too."""
        from bonfire.engine.pipeline import PipelineEngine

        calls: list[str] = []

        class _SpyPolicy:
            def tools_for(self, role: str) -> list[str]:
                calls.append(role)
                return ["X"]

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=_SpyPolicy()
        )
        await engine.run(_single_plan(role="", agent_name="x"))
        assert calls == []


# ===========================================================================
# 9. Handler-route bypass — policy not consulted for handler-dispatched stages
# ===========================================================================


class TestPipelineHandlerRouteBypass:
    """Handler-dispatched stages bypass the policy entirely."""

    async def test_handler_stage_skips_policy(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.engine.pipeline import PipelineEngine

        spy_invocations = 0

        class _SpyPolicy:
            def tools_for(self, role: str) -> list[str]:
                nonlocal spy_invocations
                spy_invocations += 1
                return ["Read"]

        class _FakeHandler:
            async def handle(
                self, stage: StageSpec, envelope: Envelope, prior_results: dict[str, str]
            ) -> Envelope:
                return envelope.with_result("handled", cost_usd=0.0)

        plan = WorkflowPlan(
            name="handler-plan",
            workflow_type=WorkflowType.STANDARD,
            stages=[
                StageSpec(
                    name="s1",
                    agent_name="x",
                    role="warrior",
                    handler_name="h1",
                )
            ],
        )
        engine = PipelineEngine(
            backend=_MockBackend(),
            bus=bus,
            config=config,
            handlers={"h1": _FakeHandler()},  # type: ignore[dict-item]
            tool_policy=_SpyPolicy(),
        )
        result = await engine.run(plan)
        assert result.success is True
        assert spy_invocations == 0


# ===========================================================================
# 10. Never-raise discipline — bad policy doesn't crash the pipeline
# ===========================================================================


class TestPipelineNeverRaises:
    """A raising policy yields a non-raising pipeline result (C19)."""

    async def test_raising_policy_fails_gracefully(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """``pipeline.run`` NEVER raises; exploding policy surfaces via result."""
        from bonfire.engine.pipeline import PipelineEngine

        class _ExplodingPolicy:
            def tools_for(self, role: str) -> list[str]:
                raise RuntimeError("boom")

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=_ExplodingPolicy()
        )
        result = await engine.run(_single_plan(role="warrior"))
        # Either path is acceptable, but no exception must propagate.
        assert result is not None


# ===========================================================================
# 11. Adversarial role values at pipeline seam
# ===========================================================================


class TestPipelineAdversarialRoles:
    """Whitespace / unicode / tool-name-collision role values at pipeline seam."""

    async def test_whitespace_role_pipelined(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """``"   "`` is truthy so the policy IS called; returns ``[]``."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(_single_plan(role="   "))
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == "   "

    async def test_unicode_role_pipelined(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(_single_plan(role="ニンジャ"))
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert opts.role == "ニンジャ"

    async def test_adversarial_bash_role_pipelined(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """A stage whose role IS literally ``"Bash"`` MUST NOT leak Bash."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        from bonfire.engine.pipeline import PipelineEngine

        backend = _MockBackend()
        engine = PipelineEngine(
            backend=backend, bus=bus, config=config, tool_policy=DefaultToolPolicy()
        )
        await engine.run(_single_plan(role="Bash"))
        _, opts = backend.calls[0]
        assert opts.tools == []
        assert "Bash" not in opts.tools
