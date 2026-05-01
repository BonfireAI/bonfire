# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Synthesizer pipeline stage handler -- auto-bounce under-marked xfail to Sage.

The ``sage_correction_bounce`` stage fires after Warrior reports a verdict
and (per Sage §A Q3) before Bard publishes the PR. It owns three jobs:

1. Classify the warrior verdict + sage decision log via the pure-function
   :func:`bonfire.verify.classifier.classify_warrior_failure`.
2. On :attr:`bonfire.verify.ClassifierVerdict.SAGE_UNDER_MARKED`, dispatch
   a tool-restricted Sage-correction agent (``allowed_tools = frozenset({
   "Read", "Edit"})``) to over-specify the under-marked xfail decorators.
3. Cherry-pick the correction commit onto the warrior branch and re-verify
   pytest. On re-verify pass: ``correction_verdict="corrected"``. On
   re-verify still-failing: ``correction_verdict="escalated"`` + the
   escalation flag, and the pipeline proceeds to Wizard with the bounce
   visible.

Every error path produces a :class:`bonfire.models.envelope.Envelope`
return value -- the handler NEVER raises (StageHandler protocol contract,
mirror :class:`bonfire.handlers.wizard.WizardHandler` lines 419-426).

The module exposes ``ROLE: AgentRole = AgentRole.SYNTHESIZER`` for
generic-vocabulary discipline. Display translation
(synthesizer -> "Sage") happens in the display layer via
``ROLE_DISPLAY[ROLE].gamified``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import (
    META_CLASSIFIER_VERDICT,
    META_CORRECTION_BRANCH,
    META_CORRECTION_CYCLES,
    META_CORRECTION_ESCALATED,
    META_CORRECTION_SKIPPED_REASON,
    META_CORRECTION_VERDICT,
    META_REVIEW_VERDICT,
    ErrorDetail,
    TaskStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.SYNTHESIZER


# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

# Sage correction dispatch is scope-limited to xfail-decorator edits.
# Tools are immutable (frozen) so a regression that hands back a mutable
# ``set`` is caught at construction time. why: type-driven contract --
# wrong tool sets are unrepresentable.
_SAGE_CORRECTION_ALLOWED_TOOLS: frozenset[str] = frozenset({"Read", "Edit"})

# Maximum correction cycles per pipeline run. v0.1 ships single-cycle
# correction; multi-cycle is a follow-up.
_MAX_CORRECTION_CYCLES: int = 1

# Verdict strings the handler routes on. Mirrors the StrEnum values from
# :mod:`bonfire.verify.classifier` plus the auxiliary "green" / "skipped"
# pseudo-verdicts the handler emits.
_VERDICT_SAGE_UNDER_MARKED: str = "sage_under_marked"
_VERDICT_WARRIOR_BUG: str = "warrior_bug"
_VERDICT_AMBIGUOUS: str = "ambiguous"
_VERDICT_GREEN: str = "green"
_VERDICT_NOT_NEEDED_WARRIOR_GREEN: str = "not_needed_warrior_green"

# Warrior-was-already-green skip signals. Two spellings carry the same
# routing intent: ``"green"`` (canonical classifier output) and the legacy
# ``"not_needed_warrior_green"`` from Sage §D3 line 291. Treating them as
# a single set keeps ``_route_verdict`` symmetric and prevents the legacy
# spelling from silently falling through to the SAGE_UNDER_MARKED path.
_GREEN_VERDICTS: frozenset[str] = frozenset(
    {_VERDICT_GREEN, _VERDICT_NOT_NEEDED_WARRIOR_GREEN},
)
_KNOWN_VERDICTS: frozenset[str] = frozenset(
    {
        _VERDICT_SAGE_UNDER_MARKED,
        _VERDICT_WARRIOR_BUG,
        _VERDICT_AMBIGUOUS,
        _VERDICT_GREEN,
        _VERDICT_NOT_NEEDED_WARRIOR_GREEN,
    }
)

# Fail-safe error-type literals (never silently pass on unknowns).
_ERROR_UNKNOWN_VERDICT: str = "UnknownClassifierVerdict"
_ERROR_CHERRY_PICK_FAILED: str = "cherry_pick_failed"
_ERROR_CORRECTION_EXHAUSTED: str = "sage_correction_exhausted"

# Default re-verify pytest invocation. Tuple args -- never `shell=True`.
_DEFAULT_PYTEST_ARGS: tuple[str, ...] = ("pytest",)

# Free-text fallback for ``_extract_commit_sha`` when the backend result
# does not expose a structured ``metadata["correction_commit_sha"]`` field.
# Matches ``sha=<hex>``, ``sha: <hex>``, and ``sha <hex>`` for hex runs of
# 4-40 chars (4 to allow short SHAs in tests, 40 = full git SHA-1).
_COMMIT_SHA_FALLBACK_RE: re.Pattern[str] = re.compile(
    r"sha[=\s:]+([a-fA-F0-9]{4,40})",
)


# ---------------------------------------------------------------------------
# Frozen value types (innovation: type-driven contracts)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SageCorrectionDispatchOptions:
    """Options carried alongside the Sage-correction backend dispatch.

    Frozen so an accidental ``set(allowed_tools)`` regression cannot pass.
    The standard :class:`bonfire.protocols.DispatchOptions` carries a
    ``tools: list[str]``; this thin wrapper exposes the immutable
    ``allowed_tools: frozenset[str]`` discipline tested by the
    sage-correction contract suite.

    why: type-driven contract -- the sage-correction axiom is "Sage
    edits xfail decorators only". A frozenset of two members makes
    wrong tool sets unrepresentable (you cannot append "Bash" to a
    frozenset).
    """

    allowed_tools: frozenset[str] = field(
        default_factory=lambda: _SAGE_CORRECTION_ALLOWED_TOOLS,
    )
    role: str = AgentRole.SYNTHESIZER.value
    permission_mode: str = "dontAsk"
    correction_mode: bool = True
    missing_deps: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class _CorrectionCycleOutcome:
    """Structured result of a single correction cycle.

    Carried between :py:meth:`SageCorrectionBounceHandler._run_correction_cycle`
    and the envelope-build path. why: keeping the orchestration result
    structured (instead of inlining branches in the cycle method) makes
    every status transition addressable as a single value -- testability
    via the integration suite improves and the routing logic on the
    return path stays linear.
    """

    status: TaskStatus
    correction_verdict: str = ""
    cycles: int = 1
    escalated: bool = False
    error_type: str = ""
    error_message: str = ""
    correction_branch: str = ""


# ---------------------------------------------------------------------------
# Verdict-routing helpers (pure)
# ---------------------------------------------------------------------------


def _cycles_from_prior_results(prior_results: dict[str, Any]) -> int:
    """Read the correction-cycle counter from ``prior_results`` (string-tolerant).

    The pipeline contract types ``prior_results`` as ``dict[str, str]``
    so the counter arrives as a stringified int. Tolerant of int or str;
    parse failure -> 0.
    """
    raw = prior_results.get(META_CORRECTION_CYCLES)
    if raw is None:
        return 0
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


def _extract_verdict_from_prior(prior_results: dict[str, Any]) -> str | None:
    """Look in ``prior_results`` for an upstream classifier verdict.

    The pipeline may set either :data:`META_CLASSIFIER_VERDICT` or (for
    historical compat with sibling stages) :data:`META_CORRECTION_VERDICT`.
    Returns the first non-empty string found, or ``None`` if neither key
    is present.
    """
    for key in (META_CLASSIFIER_VERDICT, META_CORRECTION_VERDICT):
        raw = prior_results.get(key)
        if raw:
            return str(raw)
    return None


def _warrior_reports_green(prior_results: dict[str, Any]) -> bool:
    """Detect a green warrior verdict from ``prior_results`` heuristics.

    Tolerant: if ``META_REVIEW_VERDICT == "approve"`` AND the ``warrior``
    string contains "passed" with no failure indicators, treat as green.
    Mirrors :py:func:`bonfire.handlers.herald._extract_verdict` discipline.
    """
    review = str(prior_results.get(META_REVIEW_VERDICT, "")).lower()
    warrior = str(prior_results.get("warrior", "")).lower()
    has_pass = "passed" in warrior
    has_fail = "failed" in warrior or "error" in warrior
    return review == "approve" and has_pass and not has_fail


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class SageCorrectionBounceHandler:
    """Pipeline stage handler for the synthesizer role -- auto-correction bounce.

    Constructor accepts a generous set of dependency injections so the
    Knight A spine tests (4-arg constructor) and the Knight B innovation
    tests (7-arg constructor with mocked deps) both wire cleanly.

    Every dependency is optional -- the handler degrades gracefully when
    a dep is absent (skips the correction-cycle, returns COMPLETED with
    a skip reason). The full correction cycle requires ``backend``,
    ``classifier``, ``git_workflow``, and ``pytest_runner``.
    """

    def __init__(
        self,
        *,
        backend: Any = None,
        classifier: Any = None,
        sage_decision_log_loader: Callable[[], str] | None = None,
        git_workflow: Any = None,
        pytest_runner: Any = None,
        config: Any = None,
        github_client: Any = None,
        repo_path: Path | None = None,
        event_bus: Any = None,
        max_cycles: int = _MAX_CORRECTION_CYCLES,
    ) -> None:
        self._backend = backend
        self._classifier = classifier
        self._decision_log_loader = sage_decision_log_loader
        self._git_workflow = git_workflow
        self._pytest_runner = pytest_runner
        self._config = config
        self._github_client = github_client
        self._repo_path = repo_path
        self._event_bus = event_bus
        self._max_cycles = max_cycles

    # -- public Protocol surface ------------------------------------------

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Route the sage-correction-bounce stage.

        Outer try/except wraps the entire body (StageHandler protocol
        contract: never raises). Routing is verdict-driven; the four
        possible classifier verdicts (sage_under_marked, warrior_bug,
        ambiguous, green/missing) are exhaustively handled.
        """
        try:
            cycles_in = _cycles_from_prior_results(prior_results)

            # Step 1: warrior-green short-circuit (no classification needed).
            if _warrior_reports_green(prior_results):
                return self._build_skip_envelope(
                    envelope=envelope,
                    reason="warrior_green",
                    classifier_verdict=_VERDICT_NOT_NEEDED_WARRIOR_GREEN,
                    cycles=cycles_in,
                )

            # Step 2: extract / resolve the classifier verdict. We only
            # invoke the live classifier when prior_results carries an
            # actionable warrior signal (e.g. "1 failed"); otherwise an
            # empty prior_results dict is the "no input -> skip" path
            # (Sage §D-CL.1 line 77).
            verdict = _extract_verdict_from_prior(prior_results)
            if (
                verdict is None
                and self._classifier is not None
                and self._has_actionable_warrior_signal(prior_results)
            ):
                verdict = self._invoke_classifier(prior_results)

            # Step 3: missing verdict -> skip-pass (pipeline must continue).
            if verdict is None or not verdict:
                return self._build_skip_envelope(
                    envelope=envelope,
                    reason="no_classifier_verdict",
                    classifier_verdict="",
                    cycles=cycles_in,
                )

            # Step 4: route on verdict (dict-dispatch keeps the four-row
            # routing on a single screen). why: dict-dispatch is the
            # canonical "wrong states unrepresentable" pattern.
            return await self._route_verdict(
                verdict=verdict,
                stage=stage,
                envelope=envelope,
                prior_results=prior_results,
                cycles_in=cycles_in,
            )

        except asyncio.CancelledError:
            # Cancellation propagates -- the handler does NOT swallow it
            # (pipeline orchestration relies on cancellation surfacing).
            raise
        except Exception as exc:
            return envelope.model_copy(
                update={
                    "metadata": {
                        **envelope.metadata,
                    },
                    "error": ErrorDetail(
                        error_type=type(exc).__name__,
                        message=str(exc),
                        stage_name=stage.name,
                    ),
                    "status": TaskStatus.FAILED,
                },
            )

    # -- routing / cycle ---------------------------------------------------

    @staticmethod
    def _has_actionable_warrior_signal(prior_results: dict[str, Any]) -> bool:
        """True iff ``prior_results`` carries warrior data worth classifying.

        Empty ``prior_results`` -> skip-pass; the handler must NOT
        invent a classification on no input. The signal we look for is
        any non-empty ``warrior`` key OR any ``failed``/``error`` token
        in another result field.
        """
        warrior = prior_results.get("warrior")
        if warrior:
            text = str(warrior).lower()
            return "failed" in text or "error" in text or "passed" in text
        return False

    def _invoke_classifier(self, prior_results: dict[str, Any]) -> str | None:
        """Invoke the injected classifier; return its verdict string.

        The classifier may be either:
            - a plain callable (the pure function in
              ``bonfire.verify.classifier.classify_warrior_failure``),
            - an object exposing a ``.classify`` method (mock-friendly,
              and what the integration tests inject).

        Prefer ``.classify`` when present (the integration shape); fall
        back to calling the classifier itself. Errors degrade to
        ``None`` (handler returns the skip envelope).
        """
        classify = getattr(self._classifier, "classify", None)
        if classify is None:
            classify = self._classifier
        if classify is None or not callable(classify):
            return None

        decision_log_text = ""
        if self._decision_log_loader is not None:
            with contextlib.suppress(Exception):
                decision_log_text = self._decision_log_loader() or ""

        try:
            result = classify(
                warrior_failures=(),
                sage_decision_log=decision_log_text,
                junit_xml=None,
            )
        except TypeError:
            # Fallback signature: classifier expects the warrior text.
            try:
                result = classify(prior_results.get("warrior", ""))
            except Exception:
                logger.warning("sage_correction_bounce.classifier_invocation_failed")
                return None
        except Exception:
            logger.warning("sage_correction_bounce.classifier_invocation_failed")
            return None

        # Mock-tolerant verdict extraction: result.verdict could be a
        # StrEnum, a plain string, or a MagicMock-backed attribute.
        verdict_attr = getattr(result, "verdict", None)
        if verdict_attr is None:
            return None
        return str(verdict_attr)

    async def _route_verdict(
        self,
        *,
        verdict: str,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, Any],
        cycles_in: int,
    ) -> Envelope:
        """Dispatch on the classifier verdict.

        why: dict-dispatch keeps the routing matrix to one screen. An
        if/elif chain spreads the four cases across 25+ lines and makes
        the "unknown verdict" fail-safe easy to drop on a future edit.
        """
        if verdict not in _KNOWN_VERDICTS:
            return envelope.model_copy(
                update={
                    "metadata": {
                        **envelope.metadata,
                        META_CLASSIFIER_VERDICT: verdict,
                    },
                    "error": ErrorDetail(
                        error_type=_ERROR_UNKNOWN_VERDICT,
                        message=f"Unknown classifier verdict: {verdict!r}",
                        stage_name=stage.name,
                    ),
                    "status": TaskStatus.FAILED,
                },
            )

        if verdict in _GREEN_VERDICTS:
            return self._build_skip_envelope(
                envelope=envelope,
                reason="warrior_green",
                classifier_verdict=verdict,
                cycles=cycles_in,
            )

        if verdict == _VERDICT_WARRIOR_BUG:
            return self._build_escalation_envelope(
                envelope=envelope,
                stage=stage,
                classifier_verdict=verdict,
                cycles=cycles_in,
            )

        if verdict == _VERDICT_AMBIGUOUS:
            # Ambiguous: handler marks the envelope so the gate can read
            # it and block the pipeline; no dispatch (Sage cannot fix
            # what the classifier cannot decisively name).
            return envelope.model_copy(
                update={
                    "metadata": {
                        **envelope.metadata,
                        META_CLASSIFIER_VERDICT: verdict,
                        META_CORRECTION_VERDICT: verdict,
                        META_CORRECTION_CYCLES: str(cycles_in),
                    },
                    "status": TaskStatus.COMPLETED,
                    "result": "sage_correction_bounce: ambiguous (gate blocks)",
                },
            )

        # SAGE_UNDER_MARKED: full correction cycle.
        # Cycle cap: if the upstream cycles >= max, escalate without dispatch.
        if cycles_in >= self._max_cycles:
            return self._build_escalation_envelope(
                envelope=envelope,
                stage=stage,
                classifier_verdict=verdict,
                cycles=cycles_in,
                reason="max_cycles_exhausted",
            )

        outcome = await self._run_correction_cycle(
            stage=stage,
            envelope=envelope,
            prior_results=prior_results,
            cycles_in=cycles_in,
        )
        return self._build_envelope_from_cycle_outcome(
            envelope=envelope,
            stage=stage,
            outcome=outcome,
            classifier_verdict=verdict,
        )

    async def _run_correction_cycle(
        self,
        *,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, Any],
        cycles_in: int,
    ) -> _CorrectionCycleOutcome:
        """Drive one Sage-correction cycle: dispatch -> cherry-pick -> re-verify.

        Returns a structured :class:`_CorrectionCycleOutcome` so the
        envelope-build path stays linear. The cycle increments the
        counter regardless of the outcome (one pipeline run, one cycle
        billed).
        """
        cycles_out = cycles_in + 1

        # Step 1: dispatch backend (if available).
        if self._backend is None:
            return _CorrectionCycleOutcome(
                status=TaskStatus.COMPLETED,
                correction_verdict="escalated",
                cycles=cycles_out,
                escalated=True,
                error_message="sage_correction_bounce: backend unavailable",
            )

        del prior_results  # not yet consumed in cycle body; reserved for future
        dispatch_options = SageCorrectionDispatchOptions(
            allowed_tools=_SAGE_CORRECTION_ALLOWED_TOOLS,
            role=AgentRole.SYNTHESIZER.value,
            permission_mode="dontAsk",
            correction_mode=True,
        )

        try:
            backend_result = await self._call_backend_execute(
                envelope=envelope,
                options=dispatch_options,
            )
        except asyncio.CancelledError:
            # Async cancellation propagates; do not silently swallow
            # (the parent pipeline relies on cancellation reaching it).
            raise
        except Exception as exc:
            return _CorrectionCycleOutcome(
                status=TaskStatus.FAILED,
                correction_verdict="escalated",
                cycles=cycles_out,
                escalated=True,
                error_type=type(exc).__name__,
                error_message=f"sage_correction dispatch failed: {exc}",
            )

        # Step 2: cherry-pick the correction commit.
        commit_sha = self._extract_commit_sha(backend_result)
        if commit_sha and self._git_workflow is not None:
            try:
                cherry_pick_result = self._git_workflow.cherry_pick(commit_sha)
                if asyncio.iscoroutine(cherry_pick_result):
                    await cherry_pick_result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Cherry-pick failure -> abort + return FAILED. No re-verify.
                self._safe_cherry_pick_abort()
                return _CorrectionCycleOutcome(
                    status=TaskStatus.FAILED,
                    correction_verdict="escalated",
                    cycles=cycles_out,
                    escalated=True,
                    error_type=_ERROR_CHERRY_PICK_FAILED,
                    error_message=(f"cherry-pick of {commit_sha[:12]} failed: {exc}"),
                    correction_branch=commit_sha,
                )

        # Step 3: re-verify pytest. why: pull pytest args from prior
        # warrior result if structured; else fall back to the bare
        # invocation. NEVER `shell=True`, ALWAYS tuple args.
        if self._pytest_runner is None:
            # No re-verify possible -> escalate (we cannot confirm correction).
            return _CorrectionCycleOutcome(
                status=TaskStatus.COMPLETED,
                correction_verdict="escalated",
                cycles=cycles_out,
                escalated=True,
                correction_branch=commit_sha,
            )

        try:
            reverify_result = await self._call_pytest_runner(_DEFAULT_PYTEST_ARGS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _CorrectionCycleOutcome(
                status=TaskStatus.FAILED,
                correction_verdict="escalated",
                cycles=cycles_out,
                escalated=True,
                error_type=type(exc).__name__,
                error_message=f"re-verify pytest failed: {exc}",
                correction_branch=commit_sha,
            )

        returncode = self._extract_returncode(reverify_result)
        if returncode == 0:
            return _CorrectionCycleOutcome(
                status=TaskStatus.COMPLETED,
                correction_verdict="corrected",
                cycles=cycles_out,
                escalated=False,
                correction_branch=commit_sha,
            )

        return _CorrectionCycleOutcome(
            status=TaskStatus.COMPLETED,
            correction_verdict="escalated",
            cycles=cycles_out,
            escalated=True,
            correction_branch=commit_sha,
        )

    # -- backend / runner adapters ----------------------------------------

    async def _call_backend_execute(
        self,
        *,
        envelope: Envelope,
        options: SageCorrectionDispatchOptions,
    ) -> Any:
        """Invoke ``backend.execute`` or ``backend.dispatch`` (mock-tolerant).

        The protocol-conformant backend exposes ``async execute(envelope,
        *, options)``. Tests inject ``AsyncMock`` whose ``.execute`` and
        ``.dispatch`` are both AsyncMock attributes; we prefer ``execute``
        and fall back to ``dispatch``.
        """
        execute = getattr(self._backend, "execute", None)
        if execute is not None:
            result = execute(envelope, options=options)
            if asyncio.iscoroutine(result):
                return await result
            return result
        dispatch = getattr(self._backend, "dispatch", None)
        if dispatch is not None:
            result = dispatch(envelope, options=options)
            if asyncio.iscoroutine(result):
                return await result
            return result
        raise RuntimeError("backend has neither .execute nor .dispatch")

    async def _call_pytest_runner(self, args: tuple[str, ...]) -> Any:
        """Invoke the pytest runner with sequence-of-str args (never shell).

        The test mock signature is ``pytest_runner.run(...)``. Args are
        passed positionally as a tuple. NEVER `shell=True`.
        """
        run = getattr(self._pytest_runner, "run", None)
        if run is None:
            raise RuntimeError("pytest_runner has no .run method")
        result = run(args)
        if asyncio.iscoroutine(result):
            return await result
        return result

    @staticmethod
    def _extract_commit_sha(backend_result: Any) -> str:
        """Pull a commit SHA out of the backend result (mock-tolerant).

        Two-tier extraction:
          1. Structured first: ``metadata["correction_commit_sha"]`` --
             this is the protocol-conformant backend's contract.
          2. Free-text fallback: ``sha=<hex>`` regex against
             ``backend_result.result`` -- catches backends that return a
             plain string blob without metadata (tolerant to backends that
             do not yet implement the structured envelope).

        Returns ``""`` when no SHA is recoverable.
        """
        # Tier 1: structured metadata (protocol-conformant backend).
        metadata = getattr(backend_result, "metadata", None)
        if isinstance(metadata, dict):
            sha = metadata.get("correction_commit_sha", "")
            if isinstance(sha, str) and sha:
                return sha
        # Tier 2: free-text fallback. Match ``sha=<hex>`` (also tolerates
        # ``sha: <hex>`` and ``sha <hex>``) against the result blob.
        result_text = getattr(backend_result, "result", "") or ""
        if isinstance(result_text, str) and result_text:
            match = _COMMIT_SHA_FALLBACK_RE.search(result_text)
            if match is not None:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_returncode(reverify_result: Any) -> int:
        """Pull a returncode out of the pytest-runner result (mock-tolerant).

        Returns ``0`` on green, ``1`` on red, or ``-1`` on shape mismatch.
        Mock-tolerant: ``MagicMock.returncode`` is itself a MagicMock; we
        coerce via ``int(...)`` and degrade to ``-1`` on failure.
        """
        rc = getattr(reverify_result, "returncode", None)
        if rc is None:
            return -1
        try:
            return int(rc)
        except (ValueError, TypeError):
            return -1

    def _safe_cherry_pick_abort(self) -> None:
        """Best-effort ``git cherry-pick --abort`` on failure path.

        Idempotency mitigation (Sage §D-CL.7 #7): a failed cherry-pick
        leaves the working tree in MERGING state. Abort BEFORE returning
        FAILED so the next pipeline run starts clean.
        """
        if self._git_workflow is None:
            return
        abort = getattr(self._git_workflow, "cherry_pick_abort", None)
        if abort is None:
            return
        with contextlib.suppress(Exception):
            result = abort()
            if asyncio.iscoroutine(result):
                # Schedule + forget; we are in the failure path so we
                # cannot await without changing this fn's signature.
                # The composition root wires a synchronous helper.
                logger.debug("sage_correction_bounce.abort_returned_coroutine")

    # -- envelope builders -------------------------------------------------

    def _build_skip_envelope(
        self,
        *,
        envelope: Envelope,
        reason: str,
        classifier_verdict: str,
        cycles: int,
    ) -> Envelope:
        """Build a COMPLETED envelope on the skip path (Bardo-style merge).

        Preserves all upstream metadata; adds the skip-reason +
        classifier verdict so downstream stages can read why the bounce
        was skipped.
        """
        new_metadata: dict[str, Any] = {
            **envelope.metadata,
            META_CORRECTION_SKIPPED_REASON: reason,
            META_CORRECTION_CYCLES: str(cycles),
        }
        if classifier_verdict:
            new_metadata[META_CLASSIFIER_VERDICT] = classifier_verdict
            new_metadata[META_CORRECTION_VERDICT] = classifier_verdict
        return envelope.model_copy(
            update={
                "metadata": new_metadata,
                "status": TaskStatus.COMPLETED,
                "result": f"sage_correction_bounce: skipped ({reason})",
            },
        )

    def _build_escalation_envelope(
        self,
        *,
        envelope: Envelope,
        stage: StageSpec,
        classifier_verdict: str,
        cycles: int,
        reason: str = "warrior_bug_or_max_cycles",
    ) -> Envelope:
        """Build a COMPLETED escalation envelope (Wizard sees the bounce).

        Escalation is a successful pipeline outcome (the Wizard reviews
        the warrior failure as-is). Preserves upstream metadata; sets
        :data:`META_CORRECTION_ESCALATED` so the gate routes to warning
        severity.
        """
        del reason  # reserved for future structured logging
        new_metadata: dict[str, Any] = {
            **envelope.metadata,
            META_CLASSIFIER_VERDICT: classifier_verdict,
            META_CORRECTION_VERDICT: classifier_verdict,
            META_CORRECTION_ESCALATED: True,
            META_CORRECTION_CYCLES: str(cycles),
        }
        return envelope.model_copy(
            update={
                "metadata": new_metadata,
                "status": TaskStatus.COMPLETED,
                "result": (
                    f"sage_correction_bounce: escalated to Wizard (verdict={classifier_verdict})"
                ),
            },
        )

    def _build_envelope_from_cycle_outcome(
        self,
        *,
        envelope: Envelope,
        stage: StageSpec,
        outcome: _CorrectionCycleOutcome,
        classifier_verdict: str,
    ) -> Envelope:
        """Translate a :class:`_CorrectionCycleOutcome` into an Envelope."""
        new_metadata: dict[str, Any] = {
            **envelope.metadata,
            META_CLASSIFIER_VERDICT: classifier_verdict,
            META_CORRECTION_VERDICT: outcome.correction_verdict,
            META_CORRECTION_CYCLES: str(outcome.cycles),
        }
        if outcome.escalated:
            new_metadata[META_CORRECTION_ESCALATED] = True
        if outcome.correction_branch:
            new_metadata[META_CORRECTION_BRANCH] = outcome.correction_branch

        if outcome.status == TaskStatus.FAILED:
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "error": ErrorDetail(
                        error_type=outcome.error_type or _ERROR_CORRECTION_EXHAUSTED,
                        message=(
                            outcome.error_message
                            or "sage_correction_bounce: correction cycle failed"
                        ),
                        stage_name=stage.name,
                    ),
                    "status": TaskStatus.FAILED,
                },
            )

        result_text = (
            f"sage_correction_bounce: {outcome.correction_verdict} (cycles={outcome.cycles})"
        )
        return envelope.model_copy(
            update={
                "metadata": new_metadata,
                "status": TaskStatus.COMPLETED,
                "result": result_text,
            },
        )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


__all__ = [
    "ROLE",
    "SageCorrectionBounceHandler",
    "SageCorrectionDispatchOptions",
]
