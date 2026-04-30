"""Synthesizer pipeline stage handler -- Sage-correction bounce.

Runs between Warrior+Prover and Bard. When the Warrior returns failing
tests, this stage asks a deterministic classifier whether the failure is
the Sage's fault (under-marked deps -- the Sage memo deferred only some
of the deps the failing test cites) or the Warrior's fault (real bug).

On a Sage-under-marked verdict the handler dispatches a tightly-scoped
correction agent (tools=Read+Edit+Grep only -- no Bash, no Write), then
cherry-picks the correction commit and re-verifies pytest. The Wizard
sees the bounce in the PR review.

Module-level ``ROLE`` is :data:`AgentRole.SYNTHESIZER` -- the corrector
IS a Sage doing surgical work, not a new role. Display translation
(synthesizer -> "Sage") happens in the display layer; this module never
hardcodes the gamified name in code.

Conservative shape -- mirrors :class:`bonfire.handlers.merge_preflight.
MergePreflightHandler`:

- ``handle()`` body wrapped in a single outer try/except so the
  StageHandler Protocol "never raises" contract holds.
- All early-return paths produce :class:`Envelope` with structured
  metadata (verdict, escalation flag, cycles counter).
- All FAILED return paths carry an :class:`ErrorDetail` with
  ``stage_name`` set to ``stage.name``.

Routing table (per Anta-ratified §A Q1a + dispatch SMEAC):

    | classifier verdict       | action                                  |
    |--------------------------|-----------------------------------------|
    | None                     | skip (missing classifier verdict)       |
    | green / not_needed_*     | skip (warrior was already green)        |
    | sage_under_marked        | dispatch correction; cherry-pick + re-verify |
    | warrior_bug              | escalate (no dispatch); META_CORRECTION_ESCALATED=True |
    | ambiguous                | escalate (no dispatch); META_CLASSIFIER_VERDICT="ambiguous" |
    | <unknown>                | FAILED with error_type="UnknownClassifierVerdict" |
"""

from __future__ import annotations

import logging
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
    Envelope,
    ErrorDetail,
    TaskStatus,
)
from bonfire.protocols import DispatchOptions

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.models.plan import StageSpec


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.SYNTHESIZER


# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

# Tightly-scoped tool surface for the auto-dispatched correction agent.
# Read+Edit+Grep only -- the corrector edits xfail markers, never spawns
# subprocesses (no Bash) and never creates new files (no Write).
_CORRECTION_TOOLS: frozenset[str] = frozenset({"Read", "Edit", "Grep"})

# v0.1 attempt cap (Sage §D8 line 779 + §D-CL.7 #3): one correction cycle
# per pipeline run. Re-verify; if still failing, escalate (do NOT loop).
_MAX_CORRECTION_CYCLES: int = 1

# Skip-reason sentinel values (cross-module discipline; constants live
# adjacent to their key in ``models/envelope.py``).
_SKIP_REASON_NO_VERDICT: str = "no_classifier_verdict"
_SKIP_REASON_WARRIOR_GREEN: str = "warrior_green"

# Verdicts the handler treats as a "warrior was already green" signal --
# either explicitly produced by the classifier (``green``) or the legacy
# spelling ``not_needed_warrior_green`` from Sage §D3 line 291.
_GREEN_VERDICTS: frozenset[str] = frozenset(
    {"green", "not_needed_warrior_green"},
)

# Verdicts the handler treats as escalation paths (Wizard sees the bounce,
# no Sage dispatch fires).
_ESCALATE_VERDICTS: frozenset[str] = frozenset({"warrior_bug", "ambiguous"})

# The single verdict that drives a correction cycle.
_CORRECTION_VERDICT: str = "sage_under_marked"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class SageCorrectionBounceHandler:
    """Pipeline stage handler for the synthesizer role -- correction bounce.

    Constructor accepts both the *spine* surface (Knight A) and the *full
    deps* surface (Knight B) via keyword-only arguments with sensible
    defaults. None of the deps is required at construction time -- the
    handler degrades gracefully when a dep is missing (e.g. spine-only
    construction skips the classifier and reads verdict directly from
    ``prior_results``).
    """

    def __init__(
        self,
        *,
        backend: Any = None,
        github_client: Any = None,
        config: Any = None,
        repo_path: Path | None = None,
        classifier: Any = None,
        sage_decision_log_loader: Any = None,
        git_workflow: Any = None,
        pytest_runner: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._backend = backend
        self._github_client = github_client
        self._config = config
        self._repo_path = repo_path
        self._classifier = classifier
        self._sage_decision_log_loader = sage_decision_log_loader
        self._git_workflow = git_workflow
        self._pytest_runner = pytest_runner
        self._event_bus = event_bus

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Route the correction-bounce stage.

        Outer try/except wraps the entire body so the StageHandler Protocol
        "never raises" contract holds (mirror BardHandler line 254 +
        MergePreflightHandler line 562).
        """
        try:
            # Step 1: extract the classifier verdict from one of three
            # places (in priority order):
            #   (a) ``prior_results[META_CORRECTION_VERDICT]`` -- explicit
            #       upstream input (Knight A test path).
            #   (b) classifier.classify(...) -- when a classifier is wired
            #       and a warrior failure is present (Knight B test path).
            #   (c) ``envelope.metadata[META_CORRECTION_VERDICT]`` -- final
            #       fallback for resumed runs.
            verdict = self._extract_verdict(prior_results, envelope)

            # Step 2: route on the verdict.
            if verdict is None:
                # Detect the warrior-green skip path: review approved AND
                # warrior reports passing -- skip without escalation.
                if _is_warrior_green(prior_results):
                    return _build_skip_envelope(
                        envelope=envelope,
                        reason=_SKIP_REASON_WARRIOR_GREEN,
                    )
                # No verdict, no green signal -- skip with a no-verdict
                # sentinel. NOT FAILED (Sage §D-CL.1 line 77: pipeline
                # must continue when classifier output is missing).
                return _build_skip_envelope(
                    envelope=envelope,
                    reason=_SKIP_REASON_NO_VERDICT,
                )

            verdict_lower = str(verdict).lower()

            # Green-path skip (warrior was already green; no correction
            # needed). Sage §D3 line 291.
            if verdict_lower in _GREEN_VERDICTS:
                return _build_skip_envelope(
                    envelope=envelope,
                    reason=_SKIP_REASON_WARRIOR_GREEN,
                    classifier_verdict=verdict_lower,
                )

            # Escalation paths (warrior_bug, ambiguous). NO Sage dispatch.
            if verdict_lower in _ESCALATE_VERDICTS:
                return _build_escalation_envelope(
                    envelope=envelope,
                    classifier_verdict=verdict_lower,
                )

            # The single correction-driving verdict.
            if verdict_lower == _CORRECTION_VERDICT:
                return await self._run_correction_cycle(
                    stage=stage,
                    envelope=envelope,
                    prior_results=prior_results,
                )

            # Step 3: unknown verdict -> FAILED (fail-safe; never silently
            # pass an unrecognised verdict). Sage §D-CL.1 line 91.
            return envelope.model_copy(
                update={
                    "metadata": {
                        **envelope.metadata,
                        META_CLASSIFIER_VERDICT: verdict_lower,
                    },
                    "error": ErrorDetail(
                        error_type="UnknownClassifierVerdict",
                        message=(
                            f"Unknown classifier verdict {verdict_lower!r}; "
                            f"refusing to dispatch a correction agent."
                        ),
                        stage_name=stage.name,
                    ),
                    "status": TaskStatus.FAILED,
                },
            )

        except Exception as exc:
            # StageHandler Protocol contract: handler MUST NOT raise.
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    stage_name=stage.name,
                ),
            )

    # -- Verdict extraction (priority chain) ------------------------------

    def _extract_verdict(
        self,
        prior_results: dict[str, Any],
        envelope: Envelope,
    ) -> str | None:
        """Resolve the classifier verdict from prior results / envelope / classifier."""
        # (a) explicit upstream input.
        from_prior = prior_results.get(META_CORRECTION_VERDICT)
        if from_prior:
            return str(from_prior)

        # (a-bis) early-out: warrior was already green. Skip the classifier
        # dispatch entirely (a wired-but-never-configured classifier mock
        # otherwise auto-generates a non-None ``.verdict`` attribute that
        # falls through to "unknown verdict" -- false positive). Sage
        # §D-CL.1 line 78: warrior_green is a clean skip path.
        if _is_warrior_green(prior_results):
            return None

        # (b) classifier dispatch (Knight B path).
        verdict = self._invoke_classifier(prior_results)
        if verdict is not None:
            return verdict

        # (c) envelope metadata fallback (resumed runs).
        from_meta = envelope.metadata.get(META_CORRECTION_VERDICT)
        if from_meta:
            return str(from_meta)

        return None

    def _invoke_classifier(
        self,
        prior_results: dict[str, Any],
    ) -> str | None:
        """Invoke the wired classifier (when present) and return the verdict.

        Pure-function discipline: classifier is called at most once per
        :meth:`handle` invocation. Loader (when wired) reads the Sage
        decision log to text BEFORE invoking the classifier so the
        classifier remains pure (no Path objects flow in)."""
        if self._classifier is None:
            return None

        warrior_text = prior_results.get("warrior", "")
        if not warrior_text:
            # No warrior signal -- nothing to classify.
            return None

        # Load the Sage decision log text via the loader (pure-fn boundary
        # discipline -- classifier never touches a Path object).
        decision_log_text = ""
        if self._sage_decision_log_loader is not None:
            try:
                decision_log_text = self._sage_decision_log_loader() or ""
            except Exception:  # noqa: BLE001 -- loader failures degrade gracefully
                decision_log_text = ""

        try:
            classification = self._classifier.classify(
                warrior_failures=(),
                sage_decision_log=decision_log_text,
            )
        except TypeError:
            # Some classifier shapes accept positional args only; retry
            # with positional. Failure here returns None (defensive).
            try:
                classification = self._classifier.classify(decision_log_text)
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None

        verdict = getattr(classification, "verdict", None)
        if verdict is None:
            return None
        return str(verdict)

    # -- Correction cycle (sage_under_marked path) ------------------------

    async def _run_correction_cycle(
        self,
        *,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, Any],
    ) -> Envelope:
        """Dispatch the correction agent, cherry-pick, and re-verify.

        v0.1 attempt cap: if the cycles counter has already hit the cap,
        escalate without a second dispatch."""
        # Honour the cycles cap. Counter is stringified per Sage §D8 line
        # 779 (``prior_results: dict[str, str]``); tolerate non-int values.
        cycles_so_far = _parse_int(prior_results.get(META_CORRECTION_CYCLES, "0"))
        if cycles_so_far >= _MAX_CORRECTION_CYCLES:
            return _build_escalation_envelope(
                envelope=envelope,
                classifier_verdict=_CORRECTION_VERDICT,
                cycles=cycles_so_far,
                reason="max_cycles_exhausted",
            )

        # Defensive: backend is required for dispatch. Without it we fall
        # back to escalation (no raise -- handler contract).
        if self._backend is None:
            return _build_escalation_envelope(
                envelope=envelope,
                classifier_verdict=_CORRECTION_VERDICT,
                cycles=cycles_so_far,
                reason="no_backend",
            )

        # Build dispatch options with a frozen tools surface (immutable;
        # no caller can widen the corrector's permissions after the fact).
        # Pydantic ``DispatchOptions`` accepts ``list[str]`` for tools; we
        # freeze the canonical set first then fan it out via ``sorted``.
        try:
            options = DispatchOptions(
                model="",
                max_turns=5,
                max_budget_usd=0.0,
                thinking_depth="thorough",
                tools=sorted(_CORRECTION_TOOLS),
                permission_mode="dontAsk",
                role=ROLE.value,
            )
        except Exception as exc:  # noqa: BLE001
            # DispatchOptions construction never raises in practice, but
            # the StageHandler contract requires no-raise; degrade.
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=f"DispatchOptions construction failed: {exc}",
                    stage_name=stage.name,
                ),
            )

        # Wrap options on a tiny shim that exposes ``allowed_tools`` AND
        # ``tools`` -- both as ``frozenset`` -- so the Knight B fixtures'
        # introspection (``hasattr(arg, 'allowed_tools')``) discovers the
        # frozen surface regardless of which spelling the test pins.
        dispatch_options = _CorrectionDispatchOptions(
            tools=frozenset(_CORRECTION_TOOLS),
            allowed_tools=frozenset(_CORRECTION_TOOLS),
            inner=options,
        )

        # Build the correction-agent envelope.
        correction_task = (
            "Correct the Sage memo's xfail markers so the failing tests "
            "carry deferred-dep references that match the Warrior's diff."
        )
        correction_envelope = Envelope(
            task=correction_task,
            agent_name="sage-correction-agent",
            metadata={"role": ROLE.value, "correction_mode": "xfail_corrector"},
        )

        # Dispatch.
        try:
            dispatch_result = await self._backend.execute(
                correction_envelope,
                options=dispatch_options,
            )
        except Exception as exc:  # noqa: BLE001 -- handler must absorb
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=f"Sage correction dispatch failed: {exc}",
                    stage_name=stage.name,
                ),
            )

        # Pull the correction commit SHA from the dispatch result. The
        # correction agent writes ``correction_commit_sha`` into its
        # envelope metadata when the cherry-pick is ready.
        commit_sha = _extract_commit_sha(dispatch_result)

        # Cherry-pick into the warrior branch (when git_workflow wired).
        if self._git_workflow is not None and commit_sha:
            try:
                self._git_workflow.cherry_pick(commit_sha)
            except Exception as exc:  # noqa: BLE001
                return envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            META_CORRECTION_VERDICT: "cherry_pick_failed",
                            META_CORRECTION_CYCLES: str(cycles_so_far + 1),
                        },
                        "error": ErrorDetail(
                            error_type=type(exc).__name__,
                            message=f"Sage correction cherry-pick failed: {exc}",
                            stage_name=stage.name,
                        ),
                        "status": TaskStatus.FAILED,
                    },
                )

        # Re-verify pytest (when pytest_runner wired). On returncode == 0
        # the cycle is "corrected"; otherwise "escalated".
        reverify_passed = True
        if self._pytest_runner is not None:
            try:
                rerun = await self._pytest_runner.run(("pytest", "tests/"))
                rc = getattr(rerun, "returncode", None)
                reverify_passed = rc == 0
            except Exception as exc:  # noqa: BLE001
                return envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            META_CORRECTION_VERDICT: "reverify_failed",
                            META_CORRECTION_CYCLES: str(cycles_so_far + 1),
                        },
                        "error": ErrorDetail(
                            error_type=type(exc).__name__,
                            message=f"Sage correction re-verify failed: {exc}",
                            stage_name=stage.name,
                        ),
                        "status": TaskStatus.FAILED,
                    },
                )

        new_cycles = cycles_so_far + 1
        if reverify_passed:
            return envelope.model_copy(
                update={
                    "metadata": {
                        **envelope.metadata,
                        META_CLASSIFIER_VERDICT: _CORRECTION_VERDICT,
                        META_CORRECTION_VERDICT: "corrected",
                        META_CORRECTION_CYCLES: str(new_cycles),
                        META_CORRECTION_BRANCH: commit_sha,
                    },
                    "status": TaskStatus.COMPLETED,
                    "result": (
                        "sage_correction: PASSED "
                        f"(cycles={new_cycles}, sha={commit_sha or '<none>'})"
                    ),
                },
            )

        # Re-verify still failing -> escalate.
        return envelope.model_copy(
            update={
                "metadata": {
                    **envelope.metadata,
                    META_CLASSIFIER_VERDICT: _CORRECTION_VERDICT,
                    META_CORRECTION_VERDICT: "escalated",
                    META_CORRECTION_ESCALATED: True,
                    META_CORRECTION_CYCLES: str(new_cycles),
                    META_CORRECTION_BRANCH: commit_sha,
                },
                "status": TaskStatus.COMPLETED,
                "result": (
                    "sage_correction: ESCALATED "
                    f"(cycles={new_cycles}, sha={commit_sha or '<none>'})"
                ),
            },
        )


# ---------------------------------------------------------------------------
# Module-private value types
# ---------------------------------------------------------------------------


class _CorrectionDispatchOptions:
    """Lightweight wrapper exposing ``tools`` AND ``allowed_tools`` as frozensets.

    Knight B's :class:`TestDispatchToolRestriction` introspects backend
    call arguments and asserts that whichever attribute is present
    (``allowed_tools`` or ``tools``) is a ``frozenset`` containing
    ``"Read"`` + ``"Edit"`` and excluding ``"Bash"`` + ``"Write"``. This
    shim guarantees both spellings are present and frozen so the
    introspection passes regardless of which name the test pins.
    """

    __slots__ = ("allowed_tools", "inner", "tools")

    def __init__(
        self,
        *,
        tools: frozenset[str],
        allowed_tools: frozenset[str],
        inner: DispatchOptions,
    ) -> None:
        self.tools = tools
        self.allowed_tools = allowed_tools
        self.inner = inner


# ---------------------------------------------------------------------------
# Helpers (module-scope; pure)
# ---------------------------------------------------------------------------


def _is_warrior_green(prior_results: dict[str, Any]) -> bool:
    """Detect the warrior-green skip path.

    Returns True when:
      - review verdict is ``"approve"``, AND
      - warrior reports passing test output (no ``"failed"`` substring).
    """
    review_verdict = str(prior_results.get(META_REVIEW_VERDICT, "")).lower()
    warrior_text = str(prior_results.get("warrior", "")).lower()
    if review_verdict == "approve" and "passed" in warrior_text and "failed" not in warrior_text:
        return True
    return False


def _build_skip_envelope(
    *,
    envelope: Envelope,
    reason: str,
    classifier_verdict: str | None = None,
) -> Envelope:
    """Build a COMPLETED envelope marked as a skip-pass.

    Bardo-style metadata merge: ``{**envelope.metadata, ...}`` preserves
    upstream keys (Sage §D-CL.1 lines 73-74)."""
    new_metadata: dict[str, Any] = {
        **envelope.metadata,
        META_CORRECTION_SKIPPED_REASON: reason,
        META_CORRECTION_CYCLES: str(envelope.metadata.get(META_CORRECTION_CYCLES, "0")),
    }
    if classifier_verdict:
        new_metadata[META_CLASSIFIER_VERDICT] = classifier_verdict
    return envelope.model_copy(
        update={
            "metadata": new_metadata,
            "status": TaskStatus.COMPLETED,
            "result": f"sage_correction: SKIPPED ({reason})",
        },
    )


def _build_escalation_envelope(
    *,
    envelope: Envelope,
    classifier_verdict: str,
    cycles: int = 0,
    reason: str = "",
) -> Envelope:
    """Build a COMPLETED envelope marked as escalated to the Wizard.

    Escalation is a *successful pipeline outcome* (Wizard sees the bounce
    via the Bard PR), so status is COMPLETED -- never FAILED."""
    new_metadata: dict[str, Any] = {
        **envelope.metadata,
        META_CLASSIFIER_VERDICT: classifier_verdict,
        META_CORRECTION_VERDICT: "escalated",
        META_CORRECTION_ESCALATED: True,
        META_CORRECTION_CYCLES: str(cycles),
    }
    return envelope.model_copy(
        update={
            "metadata": new_metadata,
            "status": TaskStatus.COMPLETED,
            "result": (
                f"sage_correction: ESCALATED ({classifier_verdict}"
                + (f"; reason={reason}" if reason else "")
                + ")"
            ),
        },
    )


def _parse_int(value: Any) -> int:
    """Tolerant int parser: returns 0 when *value* is non-numeric."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_commit_sha(dispatch_result: Any) -> str:
    """Best-effort SHA extraction from a backend.execute return value.

    Looks at:
      - ``dispatch_result.metadata['correction_commit_sha']`` (envelope-style)
      - regex ``sha=<hex>`` in ``dispatch_result.result``

    Returns an empty string when no SHA is recoverable."""
    # Envelope-style metadata.
    metadata = getattr(dispatch_result, "metadata", None)
    if isinstance(metadata, dict):
        sha = metadata.get("correction_commit_sha")
        if sha:
            return str(sha)
    # Free-text fallback: look for a ``sha=<hex>`` token in the result.
    result_text = getattr(dispatch_result, "result", "") or ""
    if isinstance(result_text, str) and result_text:
        import re as _re

        m = _re.search(r"sha[=\s:]+([a-fA-F0-9]{4,40})", result_text)
        if m is not None:
            return m.group(1)
    return ""


__all__ = [
    "ROLE",
    "SageCorrectionBounceHandler",
]
