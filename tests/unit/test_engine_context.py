"""Canonical RED — ``bonfire.engine.context.ContextBuilder``.

Synthesized from Knight-A orchestration + Knight-B contract fidelity.

ContextBuilder is where stage output accumulates into the next stage's input.
Priority-based truncation is the core contract: task and bounce_context MUST
survive; prior results and budget info may be dropped under pressure. The
builder is stateless — two calls with different priors stay isolated.

Sage D2: V1's ``PathGuard.contains_absolute_paths()`` check on ``task`` and
``bounce_context`` is NOT ported in this ticket (``bonfire.git.path_guard``
does not exist in public v0.1). Canonical tests do not assert path-guard
behavior. Follow-up ticket can re-add if/when ``bonfire.git`` lands.

Contract locked:
    1. ``ContextBuilder(*, max_context_tokens: int = 8000)`` — kw-only int.
    2. ``build()`` is async; every param is kw-only.
    3. Documented kw set: stage, prior_results, budget_remaining_usd, task,
       bounce_context, known_issues.
    4. build() returns str, always.
    5. Empty inputs return str (no raise).
    6. Task (priority 100) survives truncation.
    7. Bounce context (priority 90) survives truncation.
    8. known_issues included when non-empty.
    9. Prior results included when budget allows.
   10. Budget info included when > 0 remaining; omitted at 0.
   11. Priority ordering: task > bounce > known_issues > priors > budget.
   12. max_context_tokens caps output size (~4 chars/token heuristic).
   13. ContextBuilder is stateless — no leakage between calls.
"""

from __future__ import annotations

import inspect

import pytest  # noqa: F401 — pytest-asyncio auto mode picks up bare `async def`

from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.models.plan import StageSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stage(name: str = "stage-x") -> StageSpec:
    return StageSpec(name=name, agent_name=name)


def _env(agent_name: str, result: str) -> Envelope:
    return Envelope(
        task="t",
        agent_name=agent_name,
        status=TaskStatus.COMPLETED,
        result=result,
    )


# ===========================================================================
# 1. Imports
# ===========================================================================


class TestImports:
    """ContextBuilder is importable from both canonical paths."""

    def test_import_from_module(self) -> None:
        from bonfire.engine.context import ContextBuilder

        assert ContextBuilder is not None

    def test_import_from_engine_package(self) -> None:
        from bonfire.engine import ContextBuilder

        assert ContextBuilder is not None


# ===========================================================================
# 2. Constructor signature
# ===========================================================================


class TestConstructor:
    """``ContextBuilder(*, max_context_tokens: int = 8000)`` — kw-only (V1 line 23)."""

    def test_default_construction_works(self) -> None:
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder()
        assert builder is not None

    def test_accepts_custom_max_tokens(self) -> None:
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder(max_context_tokens=1000)
        assert builder is not None

    def test_max_context_tokens_is_keyword_only(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.__init__)
        param = sig.parameters.get("max_context_tokens")
        assert param is not None
        assert param.kind == inspect.Parameter.KEYWORD_ONLY


# ===========================================================================
# 3. build() signature
# ===========================================================================


class TestBuildSignature:
    """build() is async with every parameter kw-only (V1 lines 26-35)."""

    def test_build_is_async(self) -> None:
        from bonfire.engine.context import ContextBuilder

        assert inspect.iscoroutinefunction(ContextBuilder.build)

    def test_build_params_are_keyword_only(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        params = list(sig.parameters.values())[1:]  # skip self
        assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in params)

    def test_build_has_stage_param(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        assert "stage" in sig.parameters

    def test_build_has_prior_results_param(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        assert "prior_results" in sig.parameters

    def test_build_has_budget_remaining_usd_param(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        assert "budget_remaining_usd" in sig.parameters

    def test_build_has_task_param(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        assert "task" in sig.parameters

    def test_build_has_bounce_context_param(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        assert "bounce_context" in sig.parameters

    def test_build_has_known_issues_param(self) -> None:
        from bonfire.engine.context import ContextBuilder

        sig = inspect.signature(ContextBuilder.build)
        assert "known_issues" in sig.parameters


# ===========================================================================
# 4. Empty inputs — graceful handling
# ===========================================================================


class TestEmptyInputs:
    """build() handles empty/missing inputs without crashing."""

    async def test_no_prior_no_task_returns_str(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
        )
        assert isinstance(result, str)

    async def test_all_empty_returns_str(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            task="",
            bounce_context="",
            known_issues="",
            budget_remaining_usd=0.0,
        )
        assert isinstance(result, str)


# ===========================================================================
# 5. Task + bounce + known_issues inclusion
# ===========================================================================


class TestTaskAndBounceAndIssues:
    """Task, bounce_context, and known_issues are first-class citizens in output."""

    async def test_task_included(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            task="Implement the widget factory",
        )
        assert "Implement the widget factory" in result

    async def test_bounce_context_included(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            bounce_context="Gate failed: quality too low",
        )
        assert "Gate failed: quality too low" in result

    async def test_known_issues_included(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            known_issues="## Known Issues\n- flaky subprocess",
        )
        assert "flaky subprocess" in result

    async def test_empty_known_issues_omitted(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            known_issues="",
        )
        assert "Known Issues" not in result or result == ""


# ===========================================================================
# 6. Prior-results composition
# ===========================================================================


class TestPriorResults:
    """Prior stage results flow into downstream context."""

    async def test_single_prior_included(self) -> None:
        from bonfire.engine.context import ContextBuilder

        prior = {"scout": _env("scout", "found 3 bugs")}
        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results=prior,
        )
        assert "found 3 bugs" in result

    async def test_multiple_priors_all_present(self) -> None:
        from bonfire.engine.context import ContextBuilder

        prior = {
            "scout": _env("scout", "recon"),
            "knight": _env("knight", "red suite ready"),
        }
        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results=prior,
        )
        assert "recon" in result
        assert "red suite ready" in result

    async def test_no_leakage_between_two_calls(self) -> None:
        """ContextBuilder is stateless — two calls with different priors stay isolated."""
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder()
        a = await builder.build(
            stage=_stage("a"),
            prior_results={"p": _env("p", "A-ONLY")},
        )
        b = await builder.build(
            stage=_stage("b"),
            prior_results={"q": _env("q", "B-ONLY")},
        )
        assert "A-ONLY" in a
        assert "A-ONLY" not in b
        assert "B-ONLY" in b


# ===========================================================================
# 7. Budget info — inclusion + zero-clamp omission
# ===========================================================================


class TestBudgetInfo:
    """Remaining budget surfaced when > 0; omitted at 0 (V1 line 71)."""

    async def test_budget_included_when_positive(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            budget_remaining_usd=3.50,
        )
        assert "3.5" in result or "3.50" in result

    async def test_budget_omitted_when_zero(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            budget_remaining_usd=0.0,
        )
        assert "Budget Remaining" not in result


# ===========================================================================
# 8. Priority ordering — higher priority appears first
# ===========================================================================


class TestPriorityOrdering:
    """Higher-priority sections appear before lower-priority sections."""

    async def test_task_before_prior_results(self) -> None:
        """Priority 100 > 70 — task appears before prior results."""
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={"scout": _env("scout", "LOW_PRIO_DATA")},
            task="HIGH_PRIO_TASK",
        )
        assert result.index("HIGH_PRIO_TASK") < result.index("LOW_PRIO_DATA")

    async def test_task_before_bounce_context(self) -> None:
        """Task (100) appears before bounce_context (90)."""
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            task="TASK_TEXT",
            bounce_context="BOUNCE_TEXT",
        )
        assert result.index("TASK_TEXT") < result.index("BOUNCE_TEXT")

    async def test_bounce_before_known_issues(self) -> None:
        """Bounce (90) appears before known_issues (80)."""
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={},
            bounce_context="BOUNCE_TEXT",
            known_issues="ISSUES_TEXT",
        )
        assert result.index("BOUNCE_TEXT") < result.index("ISSUES_TEXT")

    async def test_bounce_before_prior_results(self) -> None:
        """Priority 90 > 70 — bounce_context appears before prior results."""
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder().build(
            stage=_stage(),
            prior_results={"scout": _env("scout", "SCOUT-Z")},
            bounce_context="BOUNCE-A",
        )
        assert result.index("BOUNCE-A") < result.index("SCOUT-Z")


# ===========================================================================
# 9. Truncation — priority-based, task/bounce survive
# ===========================================================================


class TestTruncation:
    """max_context_tokens bounds the output (~4 chars/token heuristic)."""

    async def test_huge_prior_results_are_truncated(self) -> None:
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder(max_context_tokens=200)
        huge = "word " * 2000  # ~10_000 chars
        prior = {"scout": _env("scout", huge)}

        result = await builder.build(
            stage=_stage(),
            prior_results=prior,
        )
        # 200 tokens ~ 800 chars; be generous.
        assert len(result) < 2000

    async def test_small_inputs_are_not_truncated(self) -> None:
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder(max_context_tokens=8000)
        small = {"scout": _env("scout", "tiny")}
        result = await builder.build(stage=_stage(), prior_results=small, task="go")
        assert "tiny" in result
        assert "go" in result

    async def test_task_survives_truncation(self) -> None:
        """Task (priority 100) survives even when the budget is tight."""
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder(max_context_tokens=80)
        long_prior = {"scout": _env("scout", "x" * 5000)}
        result = await builder.build(
            stage=_stage(),
            prior_results=long_prior,
            task="CRITICAL_TASK_MARKER",
        )
        assert "CRITICAL_TASK_MARKER" in result

    async def test_bounce_context_survives_truncation(self) -> None:
        """Bounce context (priority 90) survives tight budgets."""
        from bonfire.engine.context import ContextBuilder

        builder = ContextBuilder(max_context_tokens=80)
        long_prior = {"scout": _env("scout", "y" * 5000)}
        result = await builder.build(
            stage=_stage(),
            prior_results=long_prior,
            bounce_context="URGENT_BOUNCE_MARKER",
        )
        assert "URGENT_BOUNCE_MARKER" in result


# ===========================================================================
# 10. Composition — every provided input appears
# ===========================================================================


class TestComposition:
    """Every provided input appears somewhere in the output under normal budgets."""

    async def test_all_sections_present(self) -> None:
        from bonfire.engine.context import ContextBuilder

        result = await ContextBuilder(max_context_tokens=8000).build(
            stage=_stage(),
            prior_results={"scout": _env("scout", "SCOUT_OUT")},
            task="TASK_TEXT",
            bounce_context="BOUNCE_TEXT",
            known_issues="KNOWN_ISSUES",
            budget_remaining_usd=2.50,
        )
        assert "TASK_TEXT" in result
        assert "BOUNCE_TEXT" in result
        assert "KNOWN_ISSUES" in result
        assert "SCOUT_OUT" in result
        assert "2.5" in result
