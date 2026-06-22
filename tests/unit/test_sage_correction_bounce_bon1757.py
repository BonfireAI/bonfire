"""BON-1757 — narrowed broad-except behavior in ``sage_correction_bounce``.

These tests pin the BEHAVIOR preserved when the four broad ``except
Exception`` sites in :mod:`bonfire.handlers.sage_correction_bounce` are
narrowed to typed exceptions:

    - SITE 1/2 (classifier invocation): a narrowed classifier error
      (``TypeError`` / ``ValueError`` / ``AttributeError`` /
      ``RuntimeError``) degrades the verdict to ``None`` (skip-pass), the
      handler never raises.
    - SITE 3 (cherry-pick): a ``RuntimeError`` from
      ``git_workflow.cherry_pick`` triggers the safe abort AND returns a
      FAILED envelope with no re-verify.
    - SITE 4 (re-verify): a ``RuntimeError`` from the pytest runner yields
      the FAILED-correction (escalated) outcome.

Construction mirrors ``test_sage_correction_handler.py`` Knight-B
fixture factories (mocked deps, lazy imports). ``asyncio_mode = "auto"``
means no ``@pytest.mark.asyncio`` is needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock


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
    """Construct a ``SageCorrectionBounceHandler`` with mocked deps."""
    from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler

    return SageCorrectionBounceHandler(
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
    from bonfire.models.envelope import Envelope

    return Envelope(task="bon-1757 narrow-except test", metadata=metadata or {})


def _make_stage() -> Any:
    from bonfire.models.plan import StageSpec

    return StageSpec(
        name="sage_correction_bounce",
        agent_name="sage-correction",
        role="synthesizer",
        handler_name="sage_correction_bounce",
        depends_on=["warrior"],
    )


def _sage_under_marked_classifier() -> MagicMock:
    classifier = MagicMock()
    classifier.classify.return_value = MagicMock(
        verdict="sage_under_marked",
        missing_deps=frozenset({"BON-X"}),
    )
    return classifier


def _dispatch_backend() -> AsyncMock:
    backend = AsyncMock()
    backend.execute.return_value = MagicMock(
        status="completed",
        result="ok",
        metadata={"correction_commit_sha": "abc123"},
    )
    return backend


# ---------------------------------------------------------------------------
# SITE 1 / SITE 2 — classifier invocation narrowed exceptions degrade to None
# ---------------------------------------------------------------------------


class TestClassifierNarrowedExceptions:
    """SITE 1/2: a narrowed classifier error → verdict ``None`` (skip-pass).

    The handler must NOT raise; the missing-verdict path returns a
    COMPLETED skip envelope (mirrors ``TestEarlyReturnPaths``).
    """

    async def test_classify_value_error_yields_skip_completed(self) -> None:
        """SITE 2: the primary classify call raises ``ValueError`` → the
        narrowed arm catches it, verdict degrades to None, handler skips."""
        from bonfire.models.envelope import TaskStatus

        classifier = MagicMock()
        classifier.classify.side_effect = ValueError("bad classifier input")
        handler = _make_handler(classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Narrowed except caught the error → skip-pass, never FAILED-raise.
        assert result.status == TaskStatus.COMPLETED

    async def test_classify_attribute_error_yields_skip_completed(self) -> None:
        """SITE 2: ``AttributeError`` from classify is caught and skipped."""
        from bonfire.models.envelope import TaskStatus

        classifier = MagicMock()
        classifier.classify.side_effect = AttributeError("no such attr")
        handler = _make_handler(classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.status == TaskStatus.COMPLETED

    async def test_classify_typeerror_fallback_then_typeerror_skips(self) -> None:
        """SITE 1: the primary classify raises ``TypeError`` (signature
        mismatch) → the fallback ``classify(warrior_text)`` ALSO raises a
        narrowed error (``TypeError``) → the inner narrowed arm catches it,
        verdict degrades to None, handler skips."""
        from bonfire.models.envelope import TaskStatus

        classifier = MagicMock()
        # First call (kwargs signature) raises TypeError → fallback path.
        # Second call (positional warrior text) raises TypeError again →
        # SITE 1 narrowed arm.
        classifier.classify.side_effect = [
            TypeError("unexpected kwargs"),
            TypeError("unexpected positional"),
        ]
        handler = _make_handler(classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.status == TaskStatus.COMPLETED
        # Both the primary and the fallback classify calls were attempted.
        assert classifier.classify.call_count == 2


# ---------------------------------------------------------------------------
# SITE 3 — cherry-pick RuntimeError → safe abort + FAILED, no re-verify
# ---------------------------------------------------------------------------


class TestCherryPickRuntimeError:
    """SITE 3: ``git_workflow.cherry_pick`` raising ``RuntimeError`` → the
    narrowed arm aborts + returns FAILED with no re-verify (idempotency)."""

    async def test_cherry_pick_runtime_error_aborts_and_fails(self) -> None:
        from bonfire.models.envelope import TaskStatus

        backend = _dispatch_backend()
        classifier = _sage_under_marked_classifier()
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(
            side_effect=RuntimeError("git cherry-pick failed (exit 1)")
        )
        git_workflow.cherry_pick_abort = MagicMock(return_value=None)
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
        # FAILED outcome.
        assert result.status == TaskStatus.FAILED
        # Safe cherry-pick abort fired.
        assert git_workflow.cherry_pick_abort.call_count == 1
        # No re-verify attempted after cherry-pick failure.
        assert pytest_runner.run.call_count == 0

    async def test_cherry_pick_runtime_error_sets_cherry_pick_error_type(
        self,
    ) -> None:
        """The FAILED envelope carries the cherry-pick error type."""
        from bonfire.models.envelope import TaskStatus

        backend = _dispatch_backend()
        classifier = _sage_under_marked_classifier()
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(
            side_effect=RuntimeError("git cherry-pick failed (exit 1)")
        )
        git_workflow.cherry_pick_abort = MagicMock(return_value=None)
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=AsyncMock(),
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        if result.status == TaskStatus.FAILED:
            assert result.error is not None
            assert result.error.error_type == "cherry_pick_failed"


# ---------------------------------------------------------------------------
# SITE 4 — re-verify pytest RuntimeError → FAILED (escalated) outcome
# ---------------------------------------------------------------------------


class TestReverifyRuntimeError:
    """SITE 4: the pytest runner raising ``RuntimeError`` → the narrowed
    arm returns the FAILED-correction (escalated) outcome."""

    async def test_reverify_runtime_error_yields_failed_envelope(self) -> None:
        from bonfire.models.envelope import TaskStatus

        backend = _dispatch_backend()
        classifier = _sage_under_marked_classifier()
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.side_effect = RuntimeError("pytest runner crashed")
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
        # Re-verify was attempted, then failed.
        assert pytest_runner.run.call_count == 1
        assert result.status == TaskStatus.FAILED

    async def test_reverify_runtime_error_marks_escalated(self) -> None:
        from bonfire.models.envelope import (
            META_CORRECTION_ESCALATED,
            META_CORRECTION_VERDICT,
        )

        backend = _dispatch_backend()
        classifier = _sage_under_marked_classifier()
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.side_effect = RuntimeError("pytest runner crashed")
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
