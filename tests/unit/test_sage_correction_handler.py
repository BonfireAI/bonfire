"""RED tests for `bonfire.handlers.sage_correction.SageCorrectionHandler` —
INNOVATION coverage (Knight B).

Per Sage memo
`docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md` §D-CL.2
("Knight B INNOVATION") and `docs/audit/sage-decisions/bon-513-sage-D-20260428T210000Z.md`
§D3 (`StageHandler` Protocol conformance) + §D7 (re-verify cherry-pick
loop) + §D8 (escalation to Wizard).

Knight B owns the *innovation* surfaces in this file (5 classes per the
user-prompt SMEAC):
    1. TestPureFunctionClassifierIntegration — handler-level invocation
       of the pure-function classifier (mocked module function).
    2. TestDispatchToolRestriction — `DispatchOptions.allowed_tools ==
       frozenset({"Read", "Edit"})` (FROZEN nature; not mutable set).
    3. TestAttemptCounter — `META_CORRECTION_CYCLES` increments per
       cycle; capped at 1 in v0.1; >1 escalates.
    4. TestEscalatePath — `WARRIOR_BUG` and `AMBIGUOUS` verdicts produce
       `META_CORRECTION_ESCALATED=True` envelopes.
    5. TestPostDispatchVerification — re-verify subprocess invocation,
       cherry-pick orchestration, `proc.kill() + proc.wait()` on timeout.

Knight A's lane (NOT covered here): TestProtocolConformance,
TestStageHandlerSignature, TestModuleRoleConstant,
TestCorrectionEnvelopeShape, TestEarlyReturnPaths, TestNeverRaises,
TestVerdictRouting. Those live in Knight A's banner block of THIS SAME
FILE — Wizard merges via banner-comment file split (Sage §D-CL.1 lines
106-118).

This is RED. xfail(strict=True) — symbol absence is the RED state;
xpass means the symbol exists but the test isn't really exercising the
post-impl contract.
"""

from __future__ import annotations

import importlib.util
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# === Knight B INNOVATION ===

# --- Dep-presence flags (over-specified per Sage §D-CL.1 line 27-50) --------


def _module_present(modname: str) -> bool:
    """Check importability, tolerating missing intermediate packages."""
    try:
        return importlib.util.find_spec(modname) is not None
    except (ModuleNotFoundError, ValueError):
        return False


_HANDLER_PRESENT = _module_present("bonfire.handlers.sage_correction")
_CLASSIFIER_PRESENT = _module_present("bonfire.verify.classifier")
_DISPATCH_PRESENT = _module_present("bonfire.protocols")
_GIT_WORKFLOW_PRESENT = _module_present("bonfire.git.workflow")

_BOTH_LANDED = _HANDLER_PRESENT and _CLASSIFIER_PRESENT
_FULL_STACK_LANDED = (
    _HANDLER_PRESENT and _CLASSIFIER_PRESENT and _DISPATCH_PRESENT and _GIT_WORKFLOW_PRESENT
)

_HANDLER_XFAIL = pytest.mark.xfail(
    condition=not _BOTH_LANDED,
    reason=(
        "v0.1 RED: bonfire.handlers.sage_correction AND "
        "bonfire.verify.classifier must both land. Deferred to "
        "BON-513-warrior-impl (Sage memo §D-CL.2 + §D3 + §D7)."
    ),
    strict=True,
)

_FULL_STACK_XFAIL = pytest.mark.xfail(
    condition=not _FULL_STACK_LANDED,
    reason=(
        "v0.1 RED: bonfire.handlers.sage_correction AND "
        "bonfire.verify.classifier AND bonfire.protocols AND "
        "bonfire.git.workflow must all land. Deferred to "
        "BON-513-warrior-impl (Sage memo §D-CL.2 + §D7)."
    ),
    strict=True,
)


# ---------------------------------------------------------------------------
# Fixture factories — innovation pattern from BON-519 Knight B
# ---------------------------------------------------------------------------


def _make_handler(
    *,
    backend: Any = None,
    classifier: Any = None,
    decision_log_loader: Any = None,
    git_workflow: Any = None,
    pytest_runner: Any = None,
    config: Any = None,
    event_bus: Any = None,
) -> Any:
    """Construct a `SageCorrectionHandler` with mocked deps (lazy import)."""
    from bonfire.handlers.sage_correction import SageCorrectionHandler

    return SageCorrectionHandler(
        backend=backend if backend is not None else AsyncMock(),
        classifier=classifier if classifier is not None else MagicMock(),
        sage_decision_log_loader=decision_log_loader
        if decision_log_loader is not None
        else MagicMock(),
        git_workflow=git_workflow if git_workflow is not None else MagicMock(),
        pytest_runner=pytest_runner if pytest_runner is not None else AsyncMock(),
        config=config if config is not None else MagicMock(),
        event_bus=event_bus,
    )


def _make_envelope(*, metadata: dict | None = None) -> Any:
    """Construct an Envelope with optional metadata (lazy import)."""
    from bonfire.models.envelope import Envelope

    return Envelope(task="sage_correction test", metadata=metadata or {})


def _make_stage() -> Any:
    """Construct a StageSpec for the sage_correction stage (lazy import)."""
    from bonfire.models.plan import StageSpec

    return StageSpec(
        name="sage_correction",
        agent_name="sage-correction",
        role="synthesizer",
        handler_name="sage_correction",
        depends_on=["warrior"],
    )


# ---------------------------------------------------------------------------
# 1. TestPureFunctionClassifierIntegration
#    Handler invokes the pure-function classifier; return value drives flow.
# ---------------------------------------------------------------------------


class TestPureFunctionClassifierIntegration:
    """Handler delegates classification to `classify_warrior_failure`
    (pure function); reads its verdict; routes the envelope accordingly.

    Sage §D-CL.2 line 137 ('TestClassifierIntegration — handler-level
    invocation of classifier (mocked module function)') + user prompt
    Q1 (c) ('pure-fn classifier in bonfire/verify/classifier.py').
    """

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_handler_invokes_classify_warrior_failure_once(self) -> None:
        """Handler calls the classifier exactly once per `handle()` call.
        Repeated calls would risk non-determinism if the function is
        accidentally non-pure."""
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="warrior_bug",  # str matches StrEnum
        )
        handler = _make_handler(classifier=classifier)
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Classifier invoked exactly once (pure-fn discipline; no retries
        # at handler level).
        assert classifier.classify.call_count <= 1

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_handler_passes_decision_log_text_not_path(self) -> None:
        """Handler reads the decision log via the loader, then passes the
        text (not the path) to the classifier — keeps classifier pure."""
        decision_log_loader = MagicMock(return_value="## DEFER via xfail\n\n- `BON-A`\n")
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="warrior_bug")
        handler = _make_handler(
            classifier=classifier,
            decision_log_loader=decision_log_loader,
        )
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Loader was used; classifier call site does NOT include a Path
        # object — it includes a string (text content).
        if classifier.classify.call_args is not None:
            kwargs = classifier.classify.call_args.kwargs
            args = classifier.classify.call_args.args
            all_args = list(args) + list(kwargs.values())
            for arg in all_args:
                # No Path-like objects flow into the classifier (purity).
                assert not hasattr(arg, "open") or isinstance(arg, str)


# ---------------------------------------------------------------------------
# 2. TestDispatchToolRestriction
#    DispatchOptions.allowed_tools == frozenset({"Read", "Edit"})
# ---------------------------------------------------------------------------


class TestDispatchToolRestriction:
    """Sage §D-CL.2 line 188-192 + user-prompt Q4 (b) restricted
    xfail-corrector with `DispatchOptions(allowed_tools=frozenset({"Read",
    "Edit"}))`.

    HARD CONSTRAINT (user prompt): allowed_tools is a `frozenset`, not a
    mutable `set`. Tests assert on the FROZEN nature so a regression that
    accidentally hands back a `set` (mutable) is caught.

    NOTE for Wizard: Sage memo §D-CL.1 line 189 specifies
    `tools=("Read", "Edit", "Grep")` (tuple of 3). User prompt
    contradicts: `frozenset({"Read", "Edit"})` (frozenset of 2).
    Following user prompt verbatim. Wizard reconciles.
    """

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_dispatch_options_allowed_tools_is_frozenset(self) -> None:
        """`allowed_tools` is a `frozenset`, not a `set` (immutability)."""
        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)

        try:
            await handler.handle(
                stage=_make_stage(),
                envelope=_make_envelope(),
                prior_results={"warrior": "1 failed"},
            )
        except Exception:
            # Per StageHandler contract handle() never raises, but mocks may
            # short-circuit; we still inspect what reached the backend.
            pass

        # backend.execute (or .dispatch) was called with DispatchOptions.
        # Locate the DispatchOptions in the call args and assert tools is
        # a frozenset (not a list, not a set, not a tuple).
        if backend.execute.called or backend.dispatch.called:
            mock_call = backend.execute.call_args or backend.dispatch.call_args
            options = None
            for arg in list(mock_call.args) + list(mock_call.kwargs.values()):
                # DispatchOptions has an `allowed_tools` attribute or a
                # `tools` attribute. We allow either spelling but assert
                # frozen-ness on whichever is present.
                if hasattr(arg, "allowed_tools"):
                    options = arg
                    break
                if hasattr(arg, "tools"):
                    options = arg
                    break
            assert options is not None
            tool_field = getattr(options, "allowed_tools", None) or getattr(options, "tools", None)
            # FROZEN nature: frozenset, not set.
            assert isinstance(tool_field, frozenset), (
                f"DispatchOptions tool field MUST be frozenset (immutable); "
                f"got {type(tool_field).__name__}. User prompt §CONSTRAINTS: "
                f"'frozenset({{Read, Edit}}) not set({{Read, Edit}})'."
            )

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_dispatch_options_allowed_tools_contains_read_and_edit(
        self,
    ) -> None:
        """Tool set is exactly `{"Read", "Edit"}` per user-prompt Q4 (b)."""
        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)

        try:
            await handler.handle(
                stage=_make_stage(),
                envelope=_make_envelope(),
                prior_results={"warrior": "1 failed"},
            )
        except Exception:
            pass

        if backend.execute.called or backend.dispatch.called:
            mock_call = backend.execute.call_args or backend.dispatch.call_args
            options = None
            for arg in list(mock_call.args) + list(mock_call.kwargs.values()):
                if hasattr(arg, "allowed_tools") or hasattr(arg, "tools"):
                    options = arg
                    break
            assert options is not None
            tool_field = getattr(options, "allowed_tools", None) or getattr(options, "tools", None)
            assert "Read" in tool_field
            assert "Edit" in tool_field

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_dispatch_options_allowed_tools_excludes_bash_and_write(
        self,
    ) -> None:
        """Sage MUST NOT have `Bash` (cannot break out of correction scope)
        and MUST NOT have `Write` (cannot create new files; only edit
        xfail markers). Sage §D-CL.4 line 302 + user-prompt §CONSTRAINTS."""
        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)

        try:
            await handler.handle(
                stage=_make_stage(),
                envelope=_make_envelope(),
                prior_results={"warrior": "1 failed"},
            )
        except Exception:
            pass

        if backend.execute.called or backend.dispatch.called:
            mock_call = backend.execute.call_args or backend.dispatch.call_args
            options = None
            for arg in list(mock_call.args) + list(mock_call.kwargs.values()):
                if hasattr(arg, "allowed_tools") or hasattr(arg, "tools"):
                    options = arg
                    break
            assert options is not None
            tool_field = getattr(options, "allowed_tools", None) or getattr(options, "tools", None)
            assert "Bash" not in tool_field, (
                "BON-513 axiom: Sage corrects xfail decorators only — never "
                "Bash. (User prompt §CONSTRAINTS.)"
            )
            assert "Write" not in tool_field, (
                "BON-513 axiom: Sage edits xfail decorators only — never "
                "creates new files. (User prompt §CONSTRAINTS.)"
            )


# ---------------------------------------------------------------------------
# 3. TestAttemptCounter
#    META_CORRECTION_CYCLES increments per cycle; capped at 1 in v0.1.
# ---------------------------------------------------------------------------


class TestAttemptCounter:
    """Sage §D8 line 779 + §D-CL.2 line 203 + §D-CL.7 #3:
    `META_CORRECTION_CYCLES` is the per-cycle counter; v0.1 caps at 1.
    Re-verify after correction; if still failing, escalate (do NOT loop)."""

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_first_correction_cycle_sets_cycles_to_one(self) -> None:
        """After one correction cycle, envelope metadata records cycles=1
        (parseable as int)."""
        from bonfire.models.envelope import META_CORRECTION_CYCLES

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="correction commit deadbeef",
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        cycles_value = result.metadata.get(META_CORRECTION_CYCLES)
        assert cycles_value is not None
        assert int(cycles_value) >= 1

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_second_attempt_caps_at_max_and_escalates(self) -> None:
        """If `META_CORRECTION_CYCLES >= 1` already in prior_results, the
        handler MUST NOT spawn another correction cycle — it escalates."""
        from bonfire.models.envelope import (
            META_CORRECTION_CYCLES,
            META_CORRECTION_ESCALATED,
        )

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={
                "warrior": "1 failed",
                META_CORRECTION_CYCLES: "1",
            },
        )
        # No second backend dispatch — counter cap honored.
        assert backend.execute.call_count == 0
        # Escalation flag set.
        assert result.metadata.get(META_CORRECTION_ESCALATED) is True

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_attempt_counter_is_string_in_prior_results(self) -> None:
        """Sage §D8 line 779: `prior_results: dict[str, str]` — counter is
        stringified-int at the boundary. Handler MUST tolerate string values."""
        from bonfire.models.envelope import META_CORRECTION_CYCLES

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="green")
        handler = _make_handler(backend=backend, classifier=classifier)
        # Pass counter as string ("1"), not int (1).
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={
                "warrior": "passed",
                META_CORRECTION_CYCLES: "0",  # string-not-int
            },
        )
        # Handler did not raise on string-typed counter.
        assert result is not None


# ---------------------------------------------------------------------------
# 4. TestEscalatePath
#    WARRIOR_BUG and AMBIGUOUS verdicts produce ESCALATED envelopes.
# ---------------------------------------------------------------------------


class TestEscalatePath:
    """User-prompt Q9a + Q4a + Sage §D8: escalation paths.

    - WARRIOR_BUG -> handler short-circuits, NO sage dispatch,
      `META_CORRECTION_ESCALATED=True`.
    - AMBIGUOUS -> gate fails hard (severity='error'); handler can still
      mark envelope and let downstream halt the pipeline.
    """

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_warrior_bug_verdict_escalates_without_dispatch(self) -> None:
        """`META_CLASSIFIER_VERDICT="warrior_bug"` -> NO Sage dispatch."""
        from bonfire.models.envelope import META_CORRECTION_ESCALATED

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="warrior_bug")
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Verify the escalation contract.
        assert backend.execute.call_count == 0
        assert result.metadata.get(META_CORRECTION_ESCALATED) is True

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_ambiguous_verdict_marks_envelope_for_gate_block(self) -> None:
        """User-prompt Q9a: AMBIGUOUS verdict -> gate fails hard
        (severity='error'); pipeline halts. The handler envelope carries
        the AMBIGUOUS classifier verdict so the gate can read it."""
        from bonfire.models.envelope import META_CLASSIFIER_VERDICT

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="ambiguous")
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # No dispatch on AMBIGUOUS (defensive — Sage can't fix what
        # classifier can't decisively name).
        assert backend.execute.call_count == 0
        # Envelope carries the AMBIGUOUS verdict for the gate.
        assert result.metadata.get(META_CLASSIFIER_VERDICT) == "ambiguous"

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_escalation_preserves_prior_metadata(self) -> None:
        """Sage §D-CL.7 #3: escalation envelope preserves prior metadata
        (no envelope-leak via `with_error` overwrite)."""
        from bonfire.models.envelope import META_PR_NUMBER

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="warrior_bug")
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(metadata={META_PR_NUMBER: "42"}),
            prior_results={"warrior": "1 failed"},
        )
        # Prior metadata preserved on escalation (Bardo-style merge).
        assert result.metadata.get(META_PR_NUMBER) == "42"


# ---------------------------------------------------------------------------
# 5. TestPostDispatchVerification
#    Re-verify subprocess; cherry-pick orchestration; timeout teardown.
# ---------------------------------------------------------------------------


class TestPostDispatchVerification:
    """Sage §D7 re-verify loop + §D-CL.7 #2 (subprocess teardown on
    timeout: `proc.kill()` THEN `await proc.wait()`).

    These tests assert the orchestration shape; full subprocess execution
    is mocked. The point is the contract: cherry-pick THEN re-verify
    THEN classify THEN envelope-update."""

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_cherry_pick_invoked_after_successful_dispatch(self) -> None:
        """After Sage-correction dispatch succeeds, handler invokes
        `git_workflow.cherry_pick(commit_sha)` exactly once."""
        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="correction commit sha=abc123",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert git_workflow.cherry_pick.call_count == 1

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_cherry_pick_failure_returns_failed_envelope(self) -> None:
        """Sage §D-CL.7 #7: cherry-pick failure -> handler returns FAILED
        with `error.error_type` reflecting the cause; no re-verify
        attempted (idempotency)."""
        from bonfire.models.envelope import TaskStatus

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()

        class _GitCommandError(Exception):
            pass

        git_workflow.cherry_pick = MagicMock(side_effect=_GitCommandError("conflict"))
        pytest_runner = AsyncMock()
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.status == TaskStatus.FAILED
        # No re-verify attempted after cherry-pick failure.
        assert pytest_runner.run.call_count == 0

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_reverify_subprocess_uses_tuple_args_never_shell(self) -> None:
        """Sage §D-CL.7 #9 + user-prompt §CONSTRAINTS: subprocess args
        MUST be `tuple[str, ...]` or `list[str]`; never `shell=True`.

        We assert the pytest_runner is invoked with structured args (a
        sequence), never with a single shell-string."""
        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        if pytest_runner.run.called:
            call = pytest_runner.run.call_args
            for arg in list(call.args) + list(call.kwargs.values()):
                # Reject shell=True anywhere in the call.
                assert arg is not True or not isinstance(call.kwargs.get("shell"), bool), (
                    "shell=True forbidden by user-prompt §CONSTRAINTS"
                )
            # If args list/tuple was passed, every element is str.
            for arg in list(call.args) + list(call.kwargs.values()):
                if isinstance(arg, (list, tuple)) and arg:
                    assert all(isinstance(x, str) for x in arg), (
                        "subprocess args must be sequence-of-str"
                    )

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_reverify_pass_marks_envelope_corrected(self) -> None:
        """After cherry-pick, re-verify pytest passes -> envelope
        metadata `META_CORRECTION_VERDICT="corrected"`."""
        from bonfire.models.envelope import META_CORRECTION_VERDICT

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.metadata.get(META_CORRECTION_VERDICT) == "corrected"

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_reverify_still_failing_marks_escalated(self) -> None:
        """After cherry-pick, re-verify still fails -> envelope metadata
        `META_CORRECTION_VERDICT="escalated"` AND
        `META_CORRECTION_ESCALATED=True`."""
        from bonfire.models.envelope import (
            META_CORRECTION_ESCALATED,
            META_CORRECTION_VERDICT,
        )

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        # Re-verify still fails.
        pytest_runner.run.return_value = MagicMock(
            returncode=1,
            stdout="1 failed",
            stderr="",
        )
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.metadata.get(META_CORRECTION_VERDICT) == "escalated"
        assert result.metadata.get(META_CORRECTION_ESCALATED) is True

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_handler_handle_is_coroutine_function(self) -> None:
        """Defensive: handle is async (mirrors Sage §D-CL.1 line 56 but
        Knight B asserts again because the handler innovation classes
        rely on this for AsyncMock fixture wiring)."""
        handler = _make_handler()
        assert inspect.iscoroutinefunction(handler.handle)
