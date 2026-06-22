# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pure pytest-parsing + classification layer for merge preflight.

Leaf module: the cohesive cluster of public types, the deterministic
6-verdict classifier, the JUnit-XML / stdout parsers, and the
prior-results extraction helpers used by
:mod:`bonfire.handlers.merge_preflight`. Holds NO I/O, NO clock, NO
random, and -- critically -- never imports from ``merge_preflight``
(the import edge points the other way), so it stays a dependency leaf.

Sage references retained verbatim from the original colocated code:
    - Public types -- §D4 lines 390-419
    - PR-number / verdict extraction -- §D-CL.1 lines 820-821
    - Pure classifier -- §A Q4 + §D4
    - JUnit XML parser -- §D-CL.4 line 981; §D-CL.2 lines 884-888
    - Stdout fallback parser -- §D-CL.4 line 982; §D-CL.2 lines 890-892
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_REVIEW_VERDICT,
)

if TYPE_CHECKING:
    from pathlib import Path


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


@dataclass(frozen=True)
class _PytestResult:
    """Internal record of a single pytest invocation in a scratch worktree.

    Carried between
    :py:meth:`~bonfire.handlers.merge_preflight.MergePreflightHandler._run_pytest_in_worktree`
    and
    :py:meth:`~bonfire.handlers.merge_preflight.MergePreflightHandler._classify_preflight_run`.
    Field shape mirrors what :py:func:`classify_pytest_run` consumes plus
    the JUnit XML path for the parser. Sage §D2 lines 279-280.
    """

    returncode: int
    duration_seconds: float
    stdout_tail: str
    junit_xml_path: Path


# ---------------------------------------------------------------------------
# Module-private constants referenced by the parsing/classification cluster.
# The cross-module ``META_PREFLIGHT_*`` constants live in
# ``bonfire.models.envelope``; these are parser-internal.
# ---------------------------------------------------------------------------

# Maximum bytes of pytest stdout retained in the classification result for
# forensics (Sage §D-CL.7 #6: envelope-size discipline). Also imported by
# the handler shell in ``merge_preflight`` for its own tail-truncation.
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
# PR-number extraction (Steward-mirror chain, Sage §D-CL.1 lines 820-821)
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

    Mirrors :py:func:`bonfire.handlers.steward._extract_verdict`.
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
    if failing_tests and all(ft.file_path in baseline_failures for ft in failing_tests):
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
        tree = ET.parse(str(path))  # noqa: S314
    except (FileNotFoundError, OSError):
        return ()
    except ET.ParseError:
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


__all__ = [
    "FailingTest",
    "PreflightClassification",
    "PreflightVerdict",
    "classify_pytest_run",
    "parse_pytest_junit_xml",
    "parse_pytest_stdout_fallback",
]
