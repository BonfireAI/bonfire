# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Deterministic classifier for warrior-failure / sage-decision-log pairs.

Pure-function classifier of the (warrior verdict, sage decision log) pair.
Three verdicts:

- :attr:`ClassifierVerdict.SAGE_UNDER_MARKED` -- failing tests cite deps the
  Sage decision log did not enumerate. Auto-bounce candidate.
- :attr:`ClassifierVerdict.WARRIOR_BUG` -- failing tests do not blame Sage
  (raw assertion failures, or all cited deps are specified). Escalate
  for human review.
- :attr:`ClassifierVerdict.AMBIGUOUS` -- partial signals; conservative
  default to Wizard inspection rather than auto-bouncing.

The classifier is pure: no I/O, no clock, no randomness. Every set-shape
field on :class:`BounceClassification` is a ``frozenset[str]`` so callers
cannot accidentally mutate a result.

Decision-log schema (hybrid front-matter + canonical-heading prose):

1. HTML-comment YAML front-matter::

       <!-- bonfire:defers
       defers:
         - BON-A
         - BON-B
       -->

   When present, the front-matter wins (precedence over prose).

2. Canonical heading prose::

       ## DEFER via xfail

       - `BON-X`
       - `BON-Y`

   Heading literal is case-sensitive (``## DEFER via xfail``).

3. Absent -- no front-matter and no canonical heading.

The parser returns a :class:`ParsedDecisionLog` carrying both the deps
(``frozenset[str]``) and the ``parse_source`` literal so callers can
distinguish an empty memo from one whose canonical section is malformed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Public StrEnum / dataclass surface
# ---------------------------------------------------------------------------


class ClassifierVerdict(StrEnum):
    """Three deterministic verdicts emitted by :func:`classify_warrior_failure`.

    The string value is the canonical wire form -- used as envelope
    metadata, gate names, and grep targets. Never translate.
    """

    SAGE_UNDER_MARKED = "sage_under_marked"
    WARRIOR_BUG = "warrior_bug"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FailingTest:
    """Single warrior-failure record.

    Field shape mirrors what the classifier consumes -- ``xfail_reason``
    drives the cited-deps regex; ``failure_kind`` lets the classifier
    distinguish raw failures (``real_failure``) from xfail-tripped paths.
    """

    file_path: str
    classname: str = ""
    name: str = ""
    message: str = ""
    xfail_reason: str = ""
    failure_kind: str = "real_failure"


@dataclass(frozen=True)
class DeferRecord:
    """Single deferred dep parsed from a Sage decision log.

    Today the dep id is the only payload; future fields (rationale,
    target ticket, expected merge wave) can land additively. Frozen so
    callers cannot mutate a parser result.
    """

    dep_id: str
    parse_source: Literal["front_matter", "prose", "absent"] = "absent"


@dataclass(frozen=True)
class ParsedDecisionLog:
    """Result of :func:`parse_sage_decision_log`.

    ``deps`` is a ``frozenset[str]`` of dep ids the memo enumerates;
    ``parse_source`` is the source the parser used. ``front_matter``
    wins when both are present.

    ``records`` is a ``tuple[DeferRecord, ...]`` of per-bullet provenance
    entries -- one record per parsed dep, tagged with the
    ``parse_source`` it came from. Additive: production callers today
    consume ``deps`` only; the records carry forward provenance so future
    error messages can cite the source of each defer ("decision log: dep
    dep-X parsed from prose section but not in failing-test xfail
    reasons").
    """

    deps: frozenset[str] = field(default_factory=frozenset)
    parse_source: Literal["front_matter", "prose", "absent"] = "absent"
    records: tuple[DeferRecord, ...] = ()


@dataclass(frozen=True)
class BounceClassification:
    """Output of :func:`classify_warrior_failure`.

    Every set-shape field is a ``frozenset[str]`` (mitigation for the
    classifier-non-determinism failure shape -- a returned ``set`` would
    iterate in dict-order and produce flaky tests across Python versions).
    """

    verdict: ClassifierVerdict
    failing_tests: tuple[FailingTest, ...] = ()
    under_marked_tests: tuple[FailingTest, ...] = ()
    cited_deps: frozenset[str] = field(default_factory=frozenset)
    sage_specified_deps: frozenset[str] = field(default_factory=frozenset)
    missing_deps: frozenset[str] = field(default_factory=frozenset)
    parse_source: Literal["front_matter", "prose", "absent"] = "absent"


# ---------------------------------------------------------------------------
# Decision-log parser
# ---------------------------------------------------------------------------

# Strict canonical heading literal -- case-sensitive so ``## Defer via XFail``
# does NOT match (per-prompt Q6a).
_DEFER_SECTION_RE = re.compile(
    r"^##\s+DEFER\s+via\s+xfail\s*$(?P<body>.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

# Markdown bullet citing a dep id. Tolerant of `- BON-X`, `- ``BON-X```,
# `* BON-X`, with or without backticks.
_BULLET_DEP_RE = re.compile(
    r"^\s*[-*]\s+`?(?P<dep>BON-[\w.-]+)`?\s*$",
    re.MULTILINE,
)

# HTML-comment YAML front-matter recogniser. Matches the OPEN block; we
# pull defer lines from the captured body via _FRONT_MATTER_DEP_RE.
_FRONT_MATTER_RE = re.compile(
    r"<!--\s*bonfire:defers\s*(?P<body>.*?)-->",
    re.DOTALL,
)

# Front-matter dep line: a YAML list entry of the shape ``  - BON-X``.
_FRONT_MATTER_DEP_RE = re.compile(
    r"^\s*-\s+(?P<dep>BON-[\w.-]+)\s*$",
    re.MULTILINE,
)

# Cited-dep extractor for xfail reasons. Pattern: "deferred to BON-X".
# Matches both "deferred to BON-A" and "deferred to BON-A and deferred to
# BON-B" by greedy global iteration.
_XFAIL_REASON_DEP_RE = re.compile(r"deferred to\s+(?P<dep>BON-[\w.-]+)")


def parse_sage_decision_log(text: str) -> ParsedDecisionLog:
    """Parse a Sage decision-log text into a :class:`ParsedDecisionLog`.

    Pure function. No I/O. Hybrid front-matter + prose parsing --
    front-matter wins when both are present.

    Edge cases:
        - Empty input -> ``deps=frozenset(), parse_source="absent"``.
        - Front-matter only -> ``parse_source="front_matter"``.
        - Prose only (canonical heading + bullets) -> ``parse_source="prose"``.
        - Both -> front-matter deps win, ``parse_source="front_matter"``.
        - Malformed bullets under canonical heading -> ``parse_source="prose"``,
          ``deps=frozenset()`` (the heading was found; no deps recovered).
        - Multiple canonical sections in one memo -> deps unioned,
          ``parse_source="prose"``.
    """
    # 1. Front-matter takes precedence (per-prompt Q2c hybrid rule).
    fm_match = _FRONT_MATTER_RE.search(text)
    if fm_match is not None:
        body = fm_match.group("body")
        fm_deps = [m.group("dep") for m in _FRONT_MATTER_DEP_RE.finditer(body)]
        deps = frozenset(fm_deps)
        # Provenance records: one per dep, tagged ``front_matter``.
        # Sorted for deterministic ordering (frozenset iteration is
        # insertion-ordered in CPython 3.7+ but not specified).
        records = tuple(
            DeferRecord(dep_id=dep, parse_source="front_matter") for dep in sorted(deps)
        )
        return ParsedDecisionLog(
            deps=deps,
            parse_source="front_matter",
            records=records,
        )

    # 2. Canonical heading prose (multi-section unions).
    sections = list(_DEFER_SECTION_RE.finditer(text))
    if sections:
        deps_set: set[str] = set()
        records_list: list[DeferRecord] = []
        for section in sections:
            body = section.group("body")
            for m in _BULLET_DEP_RE.finditer(body):
                dep = m.group("dep")
                if dep not in deps_set:
                    deps_set.add(dep)
                    records_list.append(
                        DeferRecord(dep_id=dep, parse_source="prose"),
                    )
        return ParsedDecisionLog(
            deps=frozenset(deps_set),
            parse_source="prose",
            records=tuple(records_list),
        )

    # 3. Absent -- no parseable section.
    return ParsedDecisionLog(deps=frozenset(), parse_source="absent", records=())


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _extract_cited_deps(failing_test: FailingTest) -> frozenset[str]:
    """Pull ``BON-XXX`` ids out of an xfail reason (pure)."""
    reason = failing_test.xfail_reason
    if not reason:
        return frozenset()
    return frozenset(m.group("dep") for m in _XFAIL_REASON_DEP_RE.finditer(reason))


def classify_warrior_failure(
    *,
    warrior_failures: tuple[FailingTest, ...] = (),
    sage_decision_log: str = "",
    junit_xml: Any = None,  # reserved for future XML-shape input; ignored
) -> BounceClassification:
    """Deterministic classifier of a warrior verdict + sage decision log.

    Pure function -- no I/O, no clock, no randomness. Decision tree:

    1. ``warrior_failures`` empty -> :attr:`ClassifierVerdict.AMBIGUOUS`
       (non-blaming default; classifier never accuses Sage or Warrior on
       a green run).
    2. Parse the decision log; extract cited deps from each failing test.
    3. If NO failing test cites a dep (all xfail reasons empty) ->
       :attr:`ClassifierVerdict.WARRIOR_BUG` (raw failures are never
       Sage's fault).
    4. If ``sage_decision_log`` is non-empty AND ``parse_source == "absent"``
       -> :attr:`ClassifierVerdict.WARRIOR_BUG` (fail-safe: never silently
       blame Sage on unparseable input).
    5. Compute ``missing_deps = cited_deps - sage_specified_deps``.
    6. ``missing_deps`` empty -> :attr:`ClassifierVerdict.WARRIOR_BUG`
       (Sage specified everything; the failure is not under-marking).
    7. ``missing_deps`` non-empty -> :attr:`ClassifierVerdict.SAGE_UNDER_MARKED`.
       Auto-bounce candidate.

    The ``junit_xml`` parameter is reserved for future XML-shape input;
    the v0.1 caller passes parsed :class:`FailingTest` records directly,
    so ``junit_xml`` is currently a no-op (pure-function discipline -- we
    do NOT read XML files here; that's the handler shell's lane).
    """
    # Step 1: empty-failures short-circuit (non-blaming default).
    if not warrior_failures:
        return BounceClassification(
            verdict=ClassifierVerdict.AMBIGUOUS,
            failing_tests=(),
        )

    # Step 2: parse decision log + collect cited deps.
    parsed = parse_sage_decision_log(sage_decision_log)
    sage_specified = parsed.deps
    cited_set: set[str] = set()
    for ft in warrior_failures:
        cited_set.update(_extract_cited_deps(ft))
    cited = frozenset(cited_set)

    # Step 3: no cited deps anywhere -> raw warrior bug.
    if not cited:
        return BounceClassification(
            verdict=ClassifierVerdict.WARRIOR_BUG,
            failing_tests=warrior_failures,
            sage_specified_deps=sage_specified,
            parse_source=parsed.parse_source,
        )

    # Step 4: non-empty memo that did not parse -> fail-safe to WARRIOR_BUG
    # (never silently classify as Sage's fault on unparseable input). Empty
    # memo (sage_decision_log == "") is INTENTIONALLY skipped here -- an
    # empty memo means Sage filed nothing, which is by-definition under-
    # specification; we let it fall through to step 7.
    if sage_decision_log and parsed.parse_source == "absent":
        return BounceClassification(
            verdict=ClassifierVerdict.WARRIOR_BUG,
            failing_tests=warrior_failures,
            cited_deps=cited,
            sage_specified_deps=sage_specified,
            missing_deps=cited - sage_specified,
            parse_source=parsed.parse_source,
        )

    # Step 5: missing-deps set difference.
    missing = cited - sage_specified

    # Step 6: Sage specified everything -> warrior bug.
    if not missing:
        return BounceClassification(
            verdict=ClassifierVerdict.WARRIOR_BUG,
            failing_tests=warrior_failures,
            cited_deps=cited,
            sage_specified_deps=sage_specified,
            missing_deps=missing,
            parse_source=parsed.parse_source,
        )

    # Step 7: missing deps non-empty -> SAGE_UNDER_MARKED. Tag the
    # under-marked tests (those whose xfail_reason cites at least one
    # missing dep) for downstream reporting.
    under_marked = tuple(ft for ft in warrior_failures if _extract_cited_deps(ft) & missing)
    return BounceClassification(
        verdict=ClassifierVerdict.SAGE_UNDER_MARKED,
        failing_tests=warrior_failures,
        under_marked_tests=under_marked,
        cited_deps=cited,
        sage_specified_deps=sage_specified,
        missing_deps=missing,
        parse_source=parsed.parse_source,
    )


__all__ = [
    "BounceClassification",
    "ClassifierVerdict",
    "DeferRecord",
    "FailingTest",
    "ParsedDecisionLog",
    "classify_warrior_failure",
    "parse_sage_decision_log",
]
