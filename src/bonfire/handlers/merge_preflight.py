"""Verifier pipeline stage handler -- pre-merge full-suite pytest.

Runs full-suite pytest against a simulated merged tip BEFORE
``gh pr merge``. Detects cross-wave interactions between sibling PRs
(the enum-widening incident from S007).

Per Sage memo bon-519-sage-20260428T033101Z.md:
    - §A Q1 Path β (lines 16-39): module at ``bonfire.handlers.merge_preflight``
      with module-level ``ROLE: AgentRole = AgentRole.VERIFIER``. NOT in
      ``HANDLER_ROLE_MAP`` (deterministic handler bypasses gamified-display map).
    - §D1 (lines 196-225): module shape, public ``__all__``.
    - §D2 (lines 229-294): handler signature + ``handle()`` flow pseudocode.
    - §D-CL.3 (lines 936-958): Warrior A scaffold scope.
    - §D-CL.4 (lines 962-989): Warrior B fills the algorithmic body
      (``classify_pytest_run``, ``parse_pytest_junit_xml``,
      ``parse_pytest_stdout_fallback``, ``detect_sibling_prs``, real
      ``handle()`` body steps 5-10).

This is the **WARRIOR A SCAFFOLD**. The handler is constructible,
protocol-compliant, and routes the early gates (PR-extraction,
Wizard verdict). The classifier and pytest invocation logic are stubs
that produce a happy-path GREEN classification so Knight A's spine
tests can flip GREEN. Warrior B replaces the stubs with the algorithmic
bodies in a follow-up commit on the same branch.

The module exposes ``ROLE: AgentRole = AgentRole.VERIFIER`` for generic-
vocabulary discipline. Display translation (verifier -> "Assayer") happens
in the display layer via ``ROLE_DISPLAY[ROLE].gamified``; this module
never hardcodes the gamified name in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_PREFLIGHT_CLASSIFICATION,
    META_PREFLIGHT_TEST_DEBT_NOTED,
    META_REVIEW_VERDICT,
    ErrorDetail,
    TaskStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.git.scratch import ScratchWorktreeFactory
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec


# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.VERIFIER


# ---------------------------------------------------------------------------
# Public types -- enum + dataclass scaffolds (Warrior B fills algorithm)
# ---------------------------------------------------------------------------


class PreflightVerdict(StrEnum):
    """Six deterministic verdicts emitted by the preflight classifier.

    Sage §D4 lines 390-396 + §D-CL.5 PR body table. ``MERGE_CONFLICT`` is
    produced by the handler shell when ``git apply --3way`` fails (not by
    the classifier itself), but the enum exposes it for envelope
    construction.
    """

    GREEN = "green"
    PRE_EXISTING_DEBT = "pre_existing_debt"
    CROSS_WAVE_INTERACTION = "cross_wave_interaction"
    PURE_WARRIOR_BUG = "pure_warrior_bug"
    PYTEST_COLLECTION_ERROR = "pytest_collection_error"
    MERGE_CONFLICT = "merge_conflict"


@dataclass(frozen=True)
class FailingTest:
    """Single failing test, parsed from JUnit XML or pytest stdout.

    Sage §D4 lines 398-405. Field shape is **load-bearing** for Knight B's
    classifier and parser tests:
        - ``file_path`` (repo-relative, forward-slash) -- intersected with
          baseline + sibling file sets.
        - ``classname`` -- pytest classname (dotted module path).
        - ``name`` -- testcase name (parametrize suffix preserved here).
        - ``message`` -- failure message (top line of pytest output).
        - ``traceback_files`` -- additional files mentioned in the
          traceback; intersected with sibling files for cross-wave detection
          even when the test file itself is not in a sibling diff.
    """

    file_path: str
    classname: str
    name: str
    message: str = ""
    traceback_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightClassification:
    """Result of the deterministic preflight classifier.

    Sage §D4 lines 113-122 (memo) / §D4 lines 407-419 (full type). The
    handler embeds this dataclass as JSON metadata under
    ``META_PREFLIGHT_CLASSIFICATION`` for forensic inspection.
    """

    verdict: PreflightVerdict
    failing_tests: tuple[FailingTest, ...] = ()
    sibling_pr_numbers: tuple[int, ...] = ()
    sibling_detection_status: str = "ok"
    pytest_returncode: int = 0
    pytest_duration_seconds: float = 0.0
    pytest_stdout_tail: str = ""


# ---------------------------------------------------------------------------
# Module-private metadata key constants (handler-internal idiom -- mirrors
# BardHandler ``_META_*`` style; the cross-module ``META_PREFLIGHT_*``
# constants live in ``bonfire.models.envelope``).
# ---------------------------------------------------------------------------

_META_PREFLIGHT_VERDICT: str = "preflight_verdict"
_META_PREFLIGHT_PR_NUMBER: str = "preflight_pr_number"
_SKIP_RESULT_TEMPLATE: str = "preflight: skipped (wizard verdict not approve)"


# ---------------------------------------------------------------------------
# PR-number extraction (Herald-mirror chain, Sage §D-CL.1 lines 820-821)
# ---------------------------------------------------------------------------


def _extract_pr_number(
    prior_results: dict[str, Any],
    envelope: Any,
) -> int | None:
    """Extract PR number from prior_results or envelope metadata.

    Mirrors :py:func:`bonfire.handlers.wizard._extract_pr_number` exactly:
        1. ``prior_results[META_PR_NUMBER]`` direct
        2. ``prior_results["bard"]`` URL fallback (regex ``/pull/(\\d+)``)
        3. ``envelope.metadata[META_PR_NUMBER]`` final fallback

    Returns ``None`` if no PR number is recoverable.
    """
    raw = prior_results.get(META_PR_NUMBER)
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass

    bard_val = prior_results.get("bard", "")
    if bard_val:
        m = re.search(r"/pull/(\d+)", str(bard_val))
        if m:
            return int(m.group(1))

    meta_val = envelope.metadata.get(META_PR_NUMBER)
    if meta_val is not None:
        try:
            return int(meta_val)
        except (ValueError, TypeError):
            pass

    return None


def _extract_verdict(prior_results: dict[str, Any]) -> str:
    """Extract review verdict from prior_results (case-insensitive).

    Mirrors :py:func:`bonfire.handlers.herald._extract_verdict`.
    """
    verdict = prior_results.get(META_REVIEW_VERDICT, "")
    if verdict:
        return str(verdict).lower()
    wizard_val = prior_results.get("wizard", "")
    if wizard_val:
        return str(wizard_val).lower()
    return ""


# ---------------------------------------------------------------------------
# Algorithm placeholders -- Warrior B replaces these.
# ---------------------------------------------------------------------------


def classify_pytest_run(
    *,
    pytest_returncode: int,
    pytest_duration_seconds: float,
    pytest_stdout: str,
    failing_tests: tuple[FailingTest, ...],
    sibling_files: dict[int, frozenset[str]],
    baseline_failures: frozenset[str],
    sibling_detection_status: str,
) -> PreflightClassification:
    """Deterministic 6-verdict pytest-run classifier.

    **WARRIOR A STUB.** Returns ``GREEN`` with the input data round-tripped
    so happy-path tests in Knight A's spine can pass. Warrior B replaces
    this body with the full §D4 algorithm (first-match-wins ordering:
    collection-error -> green -> pre-existing-debt -> cross-wave -> pure-
    warrior-bug).

    Sage §D-CL.4 lines 980-986: pure function, no I/O.
    """
    # Stub does not consume sibling_files / baseline_failures; Warrior B does.
    del sibling_files, baseline_failures
    # Truncate stdout tail for envelope-size discipline (§D-CL.7 #6).
    tail = pytest_stdout[-2048:] if pytest_stdout else ""
    return PreflightClassification(
        verdict=PreflightVerdict.GREEN,
        failing_tests=failing_tests,
        sibling_pr_numbers=(),
        sibling_detection_status=sibling_detection_status,
        pytest_returncode=pytest_returncode,
        pytest_duration_seconds=pytest_duration_seconds,
        pytest_stdout_tail=tail,
    )


def parse_pytest_junit_xml(path: Any) -> tuple[FailingTest, ...]:
    """Parse pytest JUnit XML into a tuple of :class:`FailingTest`.

    **WARRIOR A STUB.** Returns ``()`` unconditionally. Warrior B replaces
    with ``xml.etree.ElementTree`` parsing per Sage §D-CL.2 lines 884-888.
    """
    del path
    return ()


def parse_pytest_stdout_fallback(stdout: str) -> tuple[FailingTest, ...]:
    """Regex-extract ``FAILED <path>::...`` lines from pytest stdout.

    **WARRIOR A STUB.** Returns ``()`` unconditionally. Warrior B replaces
    with the regex parser per Sage §D-CL.2 lines 890-892.
    """
    del stdout
    return ()


async def detect_sibling_prs(
    client: Any,
    base: str,
    *,
    current_pr_number: int,
) -> tuple[dict[int, frozenset[str]], str]:
    """Detect open sibling PRs targeting ``base``, excluding ``current``.

    **WARRIOR A STUB.** Returns ``({}, "skipped")`` unconditionally. Warrior
    B replaces with the §D5 algorithm (calls ``client.list_open_prs`` and
    catches ``RuntimeError`` -> status="error").
    """
    del client, base, current_pr_number  # unused in stub
    return ({}, "skipped")


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class MergePreflightHandler:
    """Pipeline stage handler for the verifier role -- pre-merge pytest.

    Runs between Wizard approve and Herald merge. Creates a scratch
    worktree at ``origin/<base>``, applies the PR diff (and any open
    sibling PR diffs), runs pytest, classifies failures deterministically,
    and blocks merge on cross-wave interaction or pure-warrior-bug.

    NEVER raises -- :class:`StageHandler` Protocol contract
    (``protocols.py:195``). All exceptions in the handler body produce a
    FAILED envelope with structured :class:`ErrorDetail`.

    **Warrior A scaffold:** ``handle()`` routes the early gates
    (PR-extraction, Wizard verdict) and acquires the scratch worktree to
    exercise the factory. The classifier call returns a stub GREEN
    verdict so Knight A's spine tests pass. Warrior B fills in the
    sibling-detection / pytest-invocation / parser / classifier steps.
    """

    def __init__(
        self,
        *,
        github_client: Any,
        scratch_worktree_factory: ScratchWorktreeFactory | Any,
        repo_path: Path,
        base_branch: str = "master",
        pytest_command: tuple[str, ...] = ("pytest", "tests/"),
        pytest_timeout_seconds: int | None = 600,
        sibling_detection: bool = True,
        baseline_cache: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._github_client = github_client
        self._scratch_factory = scratch_worktree_factory
        self._repo_path = repo_path
        self._base_branch = base_branch
        self._pytest_command = pytest_command
        self._pytest_timeout_seconds = pytest_timeout_seconds
        self._sibling_detection = sibling_detection
        self._baseline_cache = baseline_cache if baseline_cache is not None else {}

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Route the pre-merge full-suite pytest stage.

        Outer try/except wraps the entire body (mirror BardHandler line 254).
        Any uncaught exception returns a FAILED envelope.
        """
        try:
            # Step 1: PR-number extraction (Herald-mirror chain).
            pr_number = _extract_pr_number(prior_results, envelope)
            if pr_number is None:
                return envelope.with_error(
                    ErrorDetail(
                        error_type="ValueError",
                        message=(
                            "No PR number found in prior_results or "
                            "envelope metadata"
                        ),
                        stage_name=stage.name,
                    ),
                )

            # Step 2: Wizard verdict gate (mirror Wizard's verdict handling).
            verdict = _extract_verdict(prior_results)
            if verdict != "approve":
                return envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            _META_PREFLIGHT_PR_NUMBER: str(pr_number),
                        },
                        "status": TaskStatus.COMPLETED,
                        "result": _SKIP_RESULT_TEMPLATE,
                    },
                )

            # Step 3: Acquire scratch worktree (try/finally guarantee
            # via async-with). Sage §D2 line 273.
            ctx = self._scratch_factory.acquire(
                self._base_branch,
                pr_number=pr_number,
            )
            async with ctx as info:
                # Step 4: PLACEHOLDER for classifier logic.
                # Warrior B replaces ``_classify_preflight_run`` and
                # ``_build_result_envelope`` with the §D2 lines 273-291
                # algorithm (apply diff, sibling-batch, pytest, parse,
                # classify, build envelope).
                classification = self._classify_preflight_run(
                    envelope=envelope,
                    info=info,
                    prior_results=prior_results,
                    pr_number=pr_number,
                )
                return self._build_result_envelope(
                    envelope=envelope,
                    classification=classification,
                    stage=stage,
                    pr_number=pr_number,
                )

        except Exception as exc:
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    stage_name=stage.name,
                ),
            )

    # -- Warrior B fills in below ------------------------------------------

    def _classify_preflight_run(
        self,
        *,
        envelope: Envelope,
        info: Any,
        prior_results: dict[str, str],
        pr_number: int,
    ) -> PreflightClassification:
        """Run pytest, parse, classify.

        **WARRIOR A STUB.** Returns a GREEN classification so the happy-path
        early-gate tests can pass. Warrior B replaces with:
            - apply PR N diff via ``gh pr diff`` + ``git apply --3way``
            - apply sibling diffs in PR-number-ascending order
            - run pytest with ``--junit-xml`` flag
            - parse JUnit XML (fallback to stdout regex)
            - resolve baseline failures (cached per base SHA)
            - call :py:func:`classify_pytest_run`
        """
        del envelope, info, prior_results, pr_number  # unused in stub
        return PreflightClassification(verdict=PreflightVerdict.GREEN)

    def _build_result_envelope(
        self,
        *,
        envelope: Envelope,
        classification: PreflightClassification,
        stage: StageSpec,
        pr_number: int,
    ) -> Envelope:
        """Convert a :class:`PreflightClassification` into a result envelope.

        **WARRIOR A STUB.** Handles the GREEN happy path only. Warrior B
        extends to all 6 verdicts per Sage §D2 lines 285-291:
            - GREEN -> COMPLETED, result="preflight: PASSED ..."
            - PRE_EXISTING_DEBT -> COMPLETED + ``META_PREFLIGHT_TEST_DEBT_NOTED``
            - CROSS_WAVE_INTERACTION -> FAILED ErrorDetail(cross_wave_interaction)
            - PURE_WARRIOR_BUG -> FAILED ErrorDetail(pure_warrior_bug)
            - PYTEST_COLLECTION_ERROR / MERGE_CONFLICT -> FAILED with verbatim type
        """
        verdict = classification.verdict
        new_metadata: dict[str, Any] = {
            **envelope.metadata,
            _META_PREFLIGHT_PR_NUMBER: str(pr_number),
            _META_PREFLIGHT_VERDICT: verdict.value,
        }

        if verdict == PreflightVerdict.GREEN:
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": (
                        f"preflight: PASSED "
                        f"({len(classification.failing_tests)} failing, "
                        f"{classification.pytest_duration_seconds:.2f}s)"
                    ),
                },
            )

        # Warrior B will route the other verdicts. The scaffold currently
        # only emits GREEN, so this fallback is defensive: any non-GREEN
        # verdict produces a FAILED envelope with the verdict's value as
        # the error_type. Warrior B replaces this with verdict-specific
        # branches (Q6 ALLOW-WITH-ANNOTATION for PRE_EXISTING_DEBT etc.).
        if verdict == PreflightVerdict.PRE_EXISTING_DEBT:
            new_metadata[META_PREFLIGHT_TEST_DEBT_NOTED] = True
            new_metadata[META_PREFLIGHT_CLASSIFICATION] = verdict.value
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": (
                        f"preflight: PASSED with debt "
                        f"({len(classification.failing_tests)} pre-existing failures)"
                    ),
                },
            )

        new_metadata[META_PREFLIGHT_CLASSIFICATION] = verdict.value
        return envelope.model_copy(
            update={
                "metadata": new_metadata,
                "error": ErrorDetail(
                    error_type=verdict.value,
                    message=f"preflight: {verdict.value}",
                    stage_name=stage.name,
                ),
                "status": TaskStatus.FAILED,
            },
        )


# ---------------------------------------------------------------------------
# Public exports (Sage §D1 lines 200-208)
# ---------------------------------------------------------------------------


__all__ = [
    "FailingTest",
    "MergePreflightHandler",
    "PreflightClassification",
    "PreflightVerdict",
    "ROLE",
    # Algorithmic surface (Knight B fills; exposed for test imports).
    "classify_pytest_run",
    "detect_sibling_prs",
    "parse_pytest_junit_xml",
    "parse_pytest_stdout_fallback",
]


