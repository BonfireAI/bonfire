"""Verifier pipeline stage handler -- pre-merge full-suite pytest.

Runs full-suite pytest against a simulated merged tip BEFORE
``gh pr merge``. Detects cross-wave interactions between sibling PRs
(the enum-widening incident from S007).

Per Sage memo bon-519-sage-20260428T033101Z.md:
    - §A Q1 Path β (lines 16-39): module at ``bonfire.handlers.merge_preflight``
      with module-level ``ROLE: AgentRole = AgentRole.VERIFIER``. NOT in
      ``HANDLER_ROLE_MAP`` (deterministic handler bypasses gamified-display map).
    - §A Q4 (lines 79-122): 6-verdict deterministic classifier; first-match-wins
      ordering (collection-error -> green -> pre-existing-debt -> cross-wave
      -> pure-warrior-bug; merge-conflict produced by handler shell, not the
      pure classifier).
    - §A Q5 (lines 124-142): sibling-batch detection via
      ``client.list_open_prs(base, exclude=current_pr_number)``.
    - §A Q6 (lines 144-156): ratified ALLOW-WITH-ANNOTATION for pre-existing
      debt; classifier returns the verdict, handler downstream marks
      ``META_PREFLIGHT_TEST_DEBT_NOTED``.
    - §D1 (lines 196-225): module shape, public ``__all__``.
    - §D2 (lines 229-294): handler signature + ``handle()`` flow pseudocode.
    - §D4 (lines 383-470): classifier function signatures + edge case table.
    - §D5 (lines 473-522): gh client extension + sibling detection.
    - §D-CL.4 (lines 962-989): Warrior B fills the algorithmic body
      (``classify_pytest_run``, ``parse_pytest_junit_xml``,
      ``parse_pytest_stdout_fallback``, ``detect_sibling_prs``).

The module exposes ``ROLE: AgentRole = AgentRole.VERIFIER`` for generic-
vocabulary discipline. Display translation (verifier -> "Assayer") happens
in the display layer via ``ROLE_DISPLAY[ROLE].gamified``; this module
never hardcodes the gamified name in code.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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
# Public types -- enum + dataclass surface (Sage §D4 lines 390-419)
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

    Sage §D4 lines 398-405. Field shape is **load-bearing** for the
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
    classname: str = ""
    name: str = ""
    message: str = ""
    traceback_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightClassification:
    """Result of the deterministic preflight classifier.

    Sage §D4 lines 407-419. The handler embeds this dataclass as JSON
    metadata under ``META_PREFLIGHT_CLASSIFICATION`` for forensic
    inspection.
    """

    verdict: PreflightVerdict
    failing_tests: tuple[FailingTest, ...] = ()
    sibling_pr_numbers: tuple[int, ...] = ()
    sibling_detection_status: str = "ok"
    pytest_returncode: int = 0
    pytest_duration_seconds: float = 0.0
    pytest_stdout_tail: str = ""


# ---------------------------------------------------------------------------
# Module-private metadata key constants. The cross-module ``META_PREFLIGHT_*``
# constants live in ``bonfire.models.envelope``; these are handler-internal
# (mirrors BardHandler ``_META_*`` style).
# ---------------------------------------------------------------------------

_META_PREFLIGHT_VERDICT: str = "preflight_verdict"
_META_PREFLIGHT_PR_NUMBER: str = "preflight_pr_number"
_SKIP_RESULT_TEMPLATE: str = "preflight: skipped (wizard verdict not approve)"

# Maximum bytes of pytest stdout retained in the classification result for
# forensics (Sage §D-CL.7 #6: envelope-size discipline).
_PYTEST_STDOUT_TAIL_BYTES: int = 2048

# Regex extracting ``file.py:LINE`` references from JUnit XML failure text.
# Used to populate ``FailingTest.traceback_files`` so the cross-wave
# classifier (Sage §D4 step 4) can intersect traceback paths with the
# sibling-PR file set (Sage edge case row line 469).
_TRACEBACK_FILE_RE = re.compile(r"([\w./\-]+\.py):\d+")

# Regex matching ``FAILED <path>::<rest>`` lines in pytest stdout for
# the JUnit-XML fallback parser (Sage §D4 line 432).
# Captures the file path before ``::`` and the test ID after.
_FAILED_LINE_RE = re.compile(r"^FAILED\s+(\S+?\.py)::(\S+?)(?:\s|$)", re.MULTILINE)


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
# Pure-function classifier (Sage §A Q4 + §D4)
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

    Pure function. NO I/O, NO clock, NO random. Sage §D-CL.4 lines 980-986.
    First-match-wins ordering per Sage §A Q4 line 87 + §D4 lines 447-454:

        1. ``returncode != 0`` AND ``failing_tests`` empty -> PYTEST_COLLECTION_ERROR
        2. ``failing_tests`` empty AND ``returncode == 0`` -> GREEN
        3. ALL failing-test file paths in ``baseline_failures`` -> PRE_EXISTING_DEBT
           (Sage line 451: ALL, not ANY -- a single novel failure falls through.)
        4. ANY failing-test file path or any traceback_files entry intersects
           ``union(sibling_files.values())`` -> CROSS_WAVE_INTERACTION
           (only honoured when ``sibling_detection_status == "ok"``;
           Sage edge case row 468.)
        5. Otherwise -> PURE_WARRIOR_BUG

    The result round-trips ``failing_tests``, ``pytest_returncode``,
    ``pytest_duration_seconds``, ``sibling_detection_status``, and
    ``pytest_stdout_tail`` for forensic inspection downstream.
    """
    tail = pytest_stdout[-_PYTEST_STDOUT_TAIL_BYTES:] if pytest_stdout else ""

    common_kwargs: dict[str, Any] = {
        "failing_tests": failing_tests,
        "pytest_returncode": pytest_returncode,
        "pytest_duration_seconds": pytest_duration_seconds,
        "pytest_stdout_tail": tail,
        "sibling_detection_status": sibling_detection_status,
    }

    # Step 1: PYTEST_COLLECTION_ERROR -- pytest crash before collecting any
    # tests (e.g. ImportError in conftest). Sage §D4 line 448.
    if pytest_returncode != 0 and not failing_tests:
        return PreflightClassification(
            verdict=PreflightVerdict.PYTEST_COLLECTION_ERROR,
            sibling_pr_numbers=(),
            **common_kwargs,
        )

    # Step 2: GREEN -- no failures, clean exit. Sage §D4 line 449.
    if not failing_tests and pytest_returncode == 0:
        return PreflightClassification(
            verdict=PreflightVerdict.GREEN,
            sibling_pr_numbers=(),
            **common_kwargs,
        )

    # Step 3: PRE_EXISTING_DEBT -- ALL failing files present in baseline.
    # Sage §D4 line 450-451 ("NOT 'any' -- ALL").
    if failing_tests and all(
        ft.file_path in baseline_failures for ft in failing_tests
    ):
        return PreflightClassification(
            verdict=PreflightVerdict.PRE_EXISTING_DEBT,
            sibling_pr_numbers=(),
            **common_kwargs,
        )

    # Step 4: CROSS_WAVE_INTERACTION -- failing test file (or any traceback
    # file) intersects union of sibling-PR files. Sage §D4 lines 452-453.
    # Honoured only when sibling detection succeeded (Sage edge case 468).
    if sibling_detection_status == "ok":
        intersecting_prs: list[int] = []
        for pr_n, files in sibling_files.items():
            for ft in failing_tests:
                paths = (ft.file_path, *ft.traceback_files)
                if any(p in files for p in paths):
                    intersecting_prs.append(pr_n)
                    break
        if intersecting_prs:
            return PreflightClassification(
                verdict=PreflightVerdict.CROSS_WAVE_INTERACTION,
                sibling_pr_numbers=tuple(sorted(intersecting_prs)),
                **common_kwargs,
            )

    # Step 5: PURE_WARRIOR_BUG -- novel failure not in baseline and not
    # explained by a sibling diff. Sage §D4 line 454.
    return PreflightClassification(
        verdict=PreflightVerdict.PURE_WARRIOR_BUG,
        sibling_pr_numbers=(),
        **common_kwargs,
    )


# ---------------------------------------------------------------------------
# JUnit XML parser (Sage §D-CL.4 line 981; §D-CL.2 lines 884-888)
# ---------------------------------------------------------------------------


def parse_pytest_junit_xml(path: Path) -> tuple[FailingTest, ...]:
    """Parse pytest JUnit XML into a tuple of :class:`FailingTest`.

    Uses ``xml.etree.ElementTree`` from stdlib (no new deps). Extracts
    each ``testcase`` element bearing a ``<failure>`` or ``<error>``
    child; populates:
        - ``file_path``  from the ``@file`` attribute
        - ``classname`` from the ``@classname`` attribute
        - ``name``      from the ``@name`` attribute
        - ``message``   from the failure/error ``@message`` attribute
        - ``traceback_files`` -- file paths matched by
          :py:data:`_TRACEBACK_FILE_RE` inside the failure/error text.

    Fail-safe per Sage §D-CL.2 lines 887-888:
        - missing file -> ``()``
        - malformed XML -> ``()``
        - well-formed but no failures -> ``()``

    NEVER fail-open into GREEN -- caller treats empty + ``rc != 0`` as
    PYTEST_COLLECTION_ERROR.
    """
    try:
        tree = ET.parse(str(path))
    except (FileNotFoundError, OSError):
        return ()
    except ET.ParseError:
        return ()
    except Exception:  # pragma: no cover - belt-and-suspenders
        return ()

    root = tree.getroot()
    failing: list[FailingTest] = []
    for testcase in root.iter("testcase"):
        # Find any failure/error child; skipped/passing tests have neither.
        problem = testcase.find("failure")
        if problem is None:
            problem = testcase.find("error")
        if problem is None:
            continue

        file_path = testcase.attrib.get("file", "")
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        message = problem.attrib.get("message", "")

        # Pull file paths out of the traceback text for cross-wave
        # detection (Sage §D4 step 4 "or traceback_files entry").
        text_parts: list[str] = []
        if problem.text:
            text_parts.append(problem.text)
        if problem.tail:
            text_parts.append(problem.tail)
        traceback_blob = "\n".join(text_parts)
        traceback_files = tuple(
            sorted({m.group(1) for m in _TRACEBACK_FILE_RE.finditer(traceback_blob)})
        )

        failing.append(
            FailingTest(
                file_path=file_path,
                classname=classname,
                name=name,
                message=message,
                traceback_files=traceback_files,
            ),
        )

    return tuple(failing)


# ---------------------------------------------------------------------------
# Stdout fallback parser (Sage §D-CL.4 line 982; §D-CL.2 lines 890-892)
# ---------------------------------------------------------------------------


def parse_pytest_stdout_fallback(stdout: str) -> tuple[FailingTest, ...]:
    """Regex-extract ``FAILED <path>::...`` lines from pytest stdout.

    Used when the JUnit XML is missing or malformed. Pattern matches
    ``FAILED <file.py>::<rest>`` lines (Sage §D4 line 432). Parametrize
    suffixes are preserved on ``name`` but stripped from ``file_path``
    (Sage §D-CL.2 line 892: ``FAILED tests/x.py::test_z[param-1]`` ->
    ``file_path = "tests/x.py"``).

    Returns ``()`` when no FAILED lines are present.
    """
    if not stdout:
        return ()

    failing: list[FailingTest] = []
    for match in _FAILED_LINE_RE.finditer(stdout):
        file_path = match.group(1)
        rest = match.group(2)
        # Test ID may be ``ClassName::test_method[params]`` or
        # ``test_function[params]``. We surface ``rest`` as the test
        # name; the classifier only looks at file_path / traceback_files.
        failing.append(
            FailingTest(
                file_path=file_path,
                classname="",
                name=rest,
                message="",
                traceback_files=(),
            ),
        )
    return tuple(failing)


# ---------------------------------------------------------------------------
# Sibling-batch detection (Sage §D5 lines 510-522)
# ---------------------------------------------------------------------------


async def detect_sibling_prs(
    client: Any,
    base: str,
    *,
    current_pr_number: int,
    sibling_detection: bool = True,
) -> tuple[dict[int, frozenset[str]], str]:
    """Detect open sibling PRs targeting ``base``, excluding ``current``.

    Calls ``client.list_open_prs(base, exclude=current_pr_number)`` and
    folds the response into ``{pr_number: frozenset(file_paths)}``. Sage
    §A Q5 lines 128-136 + §D5 lines 510-522.

    Status semantics (Sage §A Q4 line 105):
        - ``"skipped"`` -- caller passed ``sibling_detection=False`` at
          handler init (no API call made)
        - ``"ok"``      -- API returned a list (possibly empty)
        - ``"error"``   -- API raised RuntimeError or other Exception
                           (graceful degradation, classifier ignores
                           sibling data when status != "ok")
    """
    if not sibling_detection:
        return ({}, "skipped")

    try:
        prs = await client.list_open_prs(base, exclude=current_pr_number)
    except RuntimeError:
        return ({}, "error")
    except Exception:  # pragma: no cover - defensive
        return ({}, "error")

    files_by_pr: dict[int, frozenset[str]] = {}
    for pr in prs:
        # PRSummary or compatible duck-type with .number + .file_paths.
        files_by_pr[pr.number] = frozenset(pr.file_paths)
    return (files_by_pr, "ok")


# ---------------------------------------------------------------------------
# Handler (Sage §D2)
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

    The v0.1 ``handle()`` body covers the spine (PR-number extraction,
    Wizard verdict gate, scratch acquisition, classifier dispatch, result
    envelope construction). The full git-apply / pytest-invocation /
    JUnit-parse pipeline lives in :py:meth:`_classify_preflight_run` and
    is exercised end-to-end in :file:`tests/integration/
    test_merge_preflight_pipeline.py` via canned handlers; the unit-level
    classifier surface is exercised in
    :file:`tests/unit/test_merge_preflight_handler.py` directly against
    :py:func:`classify_pytest_run` (pure function).
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
                # Step 4-8: Run pytest in scratch worktree, parse output,
                # classify deterministically. v0.1 returns a stub GREEN
                # classification here; the algorithmic body (apply diff,
                # sibling-batch, pytest, parse) is exercised via the
                # canned-handler integration tests + the pure classifier
                # tests on :py:func:`classify_pytest_run`. The full
                # subprocess invocation is a Wave-3 follow-up flagged
                # as a D-FT in the Sage memo §B line 184.
                classification = await self._classify_preflight_run(
                    envelope=envelope,
                    info=info,
                    prior_results=prior_results,
                    pr_number=pr_number,
                )

                # Step 9: Build result envelope per the verdict.
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

    # -- algorithm-body steps (private; canned in v0.1) --------------------

    async def _classify_preflight_run(
        self,
        *,
        envelope: Envelope,
        info: Any,
        prior_results: dict[str, str],
        pr_number: int,
    ) -> PreflightClassification:
        """Default v0.1 classifier path: GREEN-on-acquisition.

        The canned-handler integration tests (:file:`tests/integration/
        test_merge_preflight_pipeline.py`) drive each verdict shape via
        their own mode-toggling handler so the pipeline can verify halt
        / proceed semantics for all six verdicts without standing up a
        live git-apply / pytest invocation.

        The pure classifier itself (and JUnit / stdout parsers) is unit-
        tested directly against :py:func:`classify_pytest_run`. This
        method becomes the wiring layer once the live subprocess body
        ships (Sage §B line 184 D-FT).
        """
        del envelope, info, prior_results, pr_number  # unused in v0.1 stub
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

        Routes all six verdicts per Sage §D2 lines 285-291 + §A Q6
        ALLOW-WITH-ANNOTATION (line 156, ratified):

            - GREEN
                -> COMPLETED, ``result="preflight: PASSED ..."``,
                   metadata[META_PREFLIGHT_CLASSIFICATION]=verdict-value
            - PRE_EXISTING_DEBT
                -> COMPLETED with ``META_PREFLIGHT_TEST_DEBT_NOTED=True``
                   + ``META_PREFLIGHT_CLASSIFICATION``; pipeline proceeds
                   to Herald (Q6 ALLOW-WITH-ANNOTATION)
            - CROSS_WAVE_INTERACTION
                -> FAILED, ErrorDetail(error_type="cross_wave_interaction")
            - PURE_WARRIOR_BUG
                -> FAILED, ErrorDetail(error_type="pure_warrior_bug")
            - PYTEST_COLLECTION_ERROR
                -> FAILED, ErrorDetail(error_type="pytest_collection_error")
            - MERGE_CONFLICT
                -> FAILED, ErrorDetail(error_type="merge_conflict")
        """
        verdict = classification.verdict
        new_metadata: dict[str, Any] = {
            **envelope.metadata,
            _META_PREFLIGHT_PR_NUMBER: str(pr_number),
            _META_PREFLIGHT_VERDICT: verdict.value,
            META_PREFLIGHT_CLASSIFICATION: verdict.value,
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

        if verdict == PreflightVerdict.PRE_EXISTING_DEBT:
            new_metadata[META_PREFLIGHT_TEST_DEBT_NOTED] = True
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

        # All four blocking verdicts share the same FAILED envelope shape;
        # the error_type literal differs per Sage §D2 lines 287-289.
        message_map: dict[PreflightVerdict, str] = {
            PreflightVerdict.CROSS_WAVE_INTERACTION: (
                "Cross-wave interaction detected with "
                f"PRs {classification.sibling_pr_numbers}. "
                "Run reconciliation lane or close one PR + re-run."
            ),
            PreflightVerdict.PURE_WARRIOR_BUG: (
                "preflight blocks merge: pure-Warrior bug; re-run Warrior cycle"
            ),
            PreflightVerdict.PYTEST_COLLECTION_ERROR: (
                "preflight blocks merge: pytest collection error "
                f"(rc={classification.pytest_returncode})"
            ),
            PreflightVerdict.MERGE_CONFLICT: (
                "preflight blocks merge: PR diff did not apply cleanly to base"
            ),
        }
        message = message_map.get(verdict, f"preflight: {verdict.value}")

        return envelope.model_copy(
            update={
                "metadata": new_metadata,
                "error": ErrorDetail(
                    error_type=verdict.value,
                    message=message,
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
    # Algorithmic surface (Knight B tests imports).
    "classify_pytest_run",
    "detect_sibling_prs",
    "parse_pytest_junit_xml",
    "parse_pytest_stdout_fallback",
]
