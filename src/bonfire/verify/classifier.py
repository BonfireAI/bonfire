"""Pure-function classifier for Warrior-failure bounce decisions.

When the Warrior leaves failing tests behind, the pipeline asks: was the Sage
under-marked (the Sage memo deferred only some of the deps the failing test
cites)? Or is this a Warrior bug (the test should pass unconditionally)? Or
is the signal genuinely ambiguous?

This module answers that question deterministically and without I/O. The
caller (the ``SageCorrectionBounceHandler`` stage handler) is responsible
for *gathering* the inputs (Sage decision-log text, Warrior failure
metadata, optional JUnit XML) and *acting* on the verdict (escalating to
the Wizard, dispatching a tightly-scoped Sage correction agent, or skipping).

Conservative shape -- mirrors the merge-preflight classifier in
:mod:`bonfire.handlers.merge_preflight`:

- Public types are frozen dataclasses + a ``StrEnum``; every set-shape field
  is ``frozenset[str]`` (immutability guards against caller mutation).
- :func:`classify_warrior_failure` is sync (pure -- no coroutine surface).
- :func:`parse_sage_decision_log` is sync (pure -- text-in, dataclass-out).

First-match-wins decision tree (Anta-ratified per Sage memo §A Q1a):

    1. No failing tests OR all failures classify as not-real-failure
       -> AMBIGUOUS (rationale: nothing to bounce on; let downstream halt).
    2. ANY failing test missing an xfail reason (raw assertion / unconditional)
       -> WARRIOR_BUG (real Warrior bug; never blame Sage on this path).
    3. Cited deps from xfail reasons are subset of Sage-specified deps
       AND failing tests are real-failure-with-xfail-citation
       -> WARRIOR_BUG (Sage covered them; Warrior must handle).
    4. Cited deps from xfail reasons -- ALL not in Sage-specified deps
       (no overlap whatsoever) -> SAGE_UNDER_MARKED.
    5. Mixed: some cited deps in Sage-specified, some not -- partial overlap.
       If the remaining un-marked deps point to a single test or a coherent
       set, fall through to SAGE_UNDER_MARKED (the under-mark is real and
       actionable). Otherwise -> AMBIGUOUS.

Decision-log schema (Sage §D5 + user-prompt Q2 hybrid front-matter / prose):

- Canonical prose heading is the *exact* string ``## DEFER via xfail``
  (case-sensitive). A near-miss (``## Defer via XFail``) is not a heading.
- Bullets under that heading match ``r"^\\s*[-*]\\s+\\W?(BON-[\\w-]+)"`` --
  bullet character with the ticket id, optionally enclosed in backticks.
- Multiple ``## DEFER via xfail`` sections in the same memo are unioned.
- HTML-comment YAML front-matter is parsed when present:
  ``<!-- bonfire:defers\\ndefers:\\n  - BON-A\\n-->`` -- and *wins on
  contradiction with prose* (front-matter is the authoritative source).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "BounceClassification",
    "ClassifierVerdict",
    "DeferRecord",
    "FailingTest",
    "ParsedDecisionLog",
    "classify_warrior_failure",
    "parse_sage_decision_log",
]


# ---------------------------------------------------------------------------
# Verdict enum
# ---------------------------------------------------------------------------


class ClassifierVerdict(StrEnum):
    """Three deterministic verdicts emitted by :func:`classify_warrior_failure`.

    Anta-ratified set (Sage §A Q1a, lines 51-52). The third member
    (``AMBIGUOUS``) escalates to the Wizard rather than auto-bouncing on
    uncertain inputs -- conservative-by-default discipline.
    """

    SAGE_UNDER_MARKED = "sage_under_marked"
    WARRIOR_BUG = "warrior_bug"
    AMBIGUOUS = "ambiguous"


# ---------------------------------------------------------------------------
# Value types -- frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailingTest:
    """Single failing test the Warrior left behind.

    Field shape is load-bearing for the classifier algorithm:

    - ``file_path`` -- repo-relative pytest path (``tests/unit/test_x.py``).
    - ``classname`` -- pytest classname (dotted module path).
    - ``name``      -- testcase name (parametrize suffix preserved).
    - ``message``   -- failure message (top line of pytest output).
    - ``xfail_reason`` -- text inside ``@pytest.mark.xfail(reason=...)``,
      or empty string when the test is a raw assertion (no xfail marker).
    - ``failure_kind`` -- categorical: ``"real_failure"`` (raw assertion or
      strict-xfail XPASS), ``"xfail_collected"`` (pytest noticed the marker
      and the test failed within it), or other backend-specific tags.
    """

    file_path: str = ""
    classname: str = ""
    name: str = ""
    message: str = ""
    xfail_reason: str = ""
    failure_kind: str = "real_failure"


@dataclass(frozen=True)
class DeferRecord:
    """A single Sage-defer entry parsed from a decision log.

    A ``DeferRecord`` records one ticket id Sage explicitly deferred via the
    xfail mechanism, along with provenance metadata so callers can trace
    which memo and which section the dep came from. The record is a *value
    type* -- callers never mutate it.
    """

    ticket_id: str
    parse_source: str = ""
    line_number: int = 0


@dataclass(frozen=True)
class ParsedDecisionLog:
    """Result of parsing a Sage memo for deferred deps.

    - ``deps`` is a ``frozenset[str]`` -- the ticket ids Sage explicitly
      deferred. Empty when the memo has no parseable defer section.
    - ``parse_source`` is one of ``"front_matter"`` (HTML-comment YAML
      block), ``"prose"`` (canonical ``## DEFER via xfail`` heading), or
      ``"absent"`` (neither found).

    Front-matter wins on contradiction (per user-prompt Q2 hybrid).
    """

    deps: frozenset[str] = frozenset()
    parse_source: str = "absent"
    records: tuple[DeferRecord, ...] = ()


@dataclass(frozen=True)
class BounceClassification:
    """Result of :func:`classify_warrior_failure`.

    Exposes the verdict plus enough provenance for callers to act:

    - ``verdict`` -- the 3-verdict StrEnum value.
    - ``failing_tests`` -- the input failing tests (round-tripped).
    - ``cited_deps`` -- ``frozenset[str]`` of all ticket ids parsed out of
      the failing tests' xfail reasons.
    - ``sage_specified_deps`` -- ``frozenset[str]`` of ticket ids found in
      the Sage decision log.
    - ``missing_deps`` -- ``cited_deps - sage_specified_deps`` (the "what
      Sage forgot" set; non-empty implies SAGE_UNDER_MARKED).
    - ``under_marked_tests`` -- subset of ``failing_tests`` that carry at
      least one ``missing_dep``.

    Every set-shape field is ``frozenset`` (immutable; defends against
    caller-side mutation per Sage §D-CL.7 #6).
    """

    verdict: ClassifierVerdict
    failing_tests: tuple[FailingTest, ...] = ()
    cited_deps: frozenset[str] = field(default_factory=frozenset)
    sage_specified_deps: frozenset[str] = field(default_factory=frozenset)
    missing_deps: frozenset[str] = field(default_factory=frozenset)
    under_marked_tests: tuple[FailingTest, ...] = ()


# ---------------------------------------------------------------------------
# Module-level regex (compiled once, used many)
# ---------------------------------------------------------------------------

# Match the *exact* canonical prose heading -- case-sensitive per
# user-prompt Q6a. ``re.MULTILINE`` lets ``^`` anchor to a line start.
_PROSE_HEADING_RE: re.Pattern[str] = re.compile(
    r"^##\s+DEFER\s+via\s+xfail.*?$",
    re.MULTILINE,
)

# Bullets under a canonical heading: optional backtick wrap. Matches
# ``- `BON-X``` or ``- BON-X`` or ``* BON-X``. Greedy on the bullet
# character + whitespace; stops at non-word punctuation around the id.
_PROSE_BULLET_RE: re.Pattern[str] = re.compile(
    r"^\s*[-*]\s+`?(?P<dep>BON-[\w-]+)",
    re.MULTILINE,
)

# Bare ticket id pattern (used inside xfail reasons + front-matter parsing).
_TICKET_ID_RE: re.Pattern[str] = re.compile(r"\b(BON-[\w-]+)\b")

# HTML-comment YAML front-matter. The block opens with
# ``<!-- bonfire:defers`` (followed by anything until ``-->``).
_FRONT_MATTER_RE: re.Pattern[str] = re.compile(
    r"<!--\s*bonfire:defers\s*(?P<body>.*?)-->",
    re.DOTALL,
)

# Front-matter line bullets: ``  - BON-X``. Bare bullet, no backticks.
_FRONT_MATTER_BULLET_RE: re.Pattern[str] = re.compile(
    r"^\s*-\s+(?P<dep>BON-[\w-]+)",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# parse_sage_decision_log -- pure function, no I/O
# ---------------------------------------------------------------------------


def parse_sage_decision_log(text: str) -> ParsedDecisionLog:
    """Parse *text* and return a :class:`ParsedDecisionLog`.

    Pure function. NO I/O. Front-matter wins on contradiction with prose.

    Schema (Sage §D5 + user-prompt Q2 hybrid):

    1. Look for an HTML-comment YAML front-matter block opening with
       ``<!-- bonfire:defers``. If present, extract bare ``BON-X`` ids
       from the bullet list inside; ``parse_source = "front_matter"``.
    2. Otherwise, look for one or more ``## DEFER via xfail`` headings
       (case-sensitive); union the bullets under each. ``parse_source =
       "prose"`` even when no bullets parsed (the heading itself is the
       claim). Empty deps under a canonical heading is allowed.
    3. Otherwise, ``parse_source = "absent"`` and ``deps = frozenset()``.

    Returns a :class:`ParsedDecisionLog` with frozen ``deps`` set.
    """
    if not text:
        return ParsedDecisionLog(deps=frozenset(), parse_source="absent", records=())

    # Step 1: front-matter (wins on contradiction).
    fm_match = _FRONT_MATTER_RE.search(text)
    if fm_match is not None:
        body = fm_match.group("body")
        deps_iter = _FRONT_MATTER_BULLET_RE.finditer(body)
        deps_set = {m.group("dep") for m in deps_iter}
        records = tuple(
            DeferRecord(ticket_id=dep, parse_source="front_matter") for dep in sorted(deps_set)
        )
        return ParsedDecisionLog(
            deps=frozenset(deps_set),
            parse_source="front_matter",
            records=records,
        )

    # Step 2: prose canonical heading(s). Find ALL canonical headings and
    # union the bullets in each section (until next ``## `` heading or EOF).
    prose_sections = _extract_prose_sections(text)
    if prose_sections:
        deps_set: set[str] = set()
        records_list: list[DeferRecord] = []
        for section in prose_sections:
            for m in _PROSE_BULLET_RE.finditer(section):
                dep = m.group("dep")
                deps_set.add(dep)
                records_list.append(
                    DeferRecord(ticket_id=dep, parse_source="prose"),
                )
        return ParsedDecisionLog(
            deps=frozenset(deps_set),
            parse_source="prose",
            records=tuple(records_list),
        )

    # Step 3: nothing parseable.
    return ParsedDecisionLog(deps=frozenset(), parse_source="absent", records=())


def _extract_prose_sections(text: str) -> tuple[str, ...]:
    """Return tuples of text bodies under each ``## DEFER via xfail`` heading.

    Each section runs from the heading line through (but not including) the
    next ``## `` heading or end-of-text. Empty sections are returned as
    empty strings (so ``parse_source="prose"`` even when no bullets parse).
    """
    sections: list[str] = []
    matches = list(_PROSE_HEADING_RE.finditer(text))
    if not matches:
        return ()
    # Locate the start of the next heading (or EOF) for each match.
    for idx, m in enumerate(matches):
        start = m.end()
        if idx + 1 < len(matches):
            end = matches[idx + 1].start()
        else:
            # Find the next ``## `` heading after this section, if any.
            next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
            end = start + next_heading.start() if next_heading is not None else len(text)
        sections.append(text[start:end])
    return tuple(sections)


# ---------------------------------------------------------------------------
# classify_warrior_failure -- pure function, no I/O
# ---------------------------------------------------------------------------


def classify_warrior_failure(
    *,
    warrior_failures: tuple[FailingTest, ...] = (),
    sage_decision_log: str = "",
    junit_xml: str | None = None,
) -> BounceClassification:
    """Classify a Warrior failure run deterministically.

    Pure function. NO I/O. NO clock. NO random. Sage §A Q1 (line 38):
    classifier is pure, handler owns I/O.

    First-match-wins decision tree:

        1. No failing tests             -> AMBIGUOUS  (nothing to bounce on)
        2. Any test with no xfail_reason
           AND failure_kind=real_failure -> WARRIOR_BUG (raw assertion bug)
        3. cited_deps subset of Sage-spec -> WARRIOR_BUG (Sage covered all)
        4. cited_deps disjoint Sage-spec -> SAGE_UNDER_MARKED
           (Sage memo malformed/empty BUT a dep is cited)
        5. Mixed (partial overlap)      -> SAGE_UNDER_MARKED if the
           under-marked test has a clean missing-dep set; AMBIGUOUS only
           when the under-mark is itself ambiguous (pathological mixed).

    The decision tree mirrors the merge-preflight classifier's
    first-match-wins discipline (see :func:`bonfire.handlers.merge_preflight.classify_pytest_run`).
    """
    del junit_xml  # JUnit XML stream is reserved for future enrichment.

    # Step 1: no failures -> AMBIGUOUS (do not blame either side).
    if not warrior_failures:
        return BounceClassification(
            verdict=ClassifierVerdict.AMBIGUOUS,
            failing_tests=(),
            cited_deps=frozenset(),
            sage_specified_deps=frozenset(),
            missing_deps=frozenset(),
            under_marked_tests=(),
        )

    # Parse Sage memo for deferred deps.
    parsed = parse_sage_decision_log(sage_decision_log)
    sage_specified_deps = parsed.deps

    # Extract cited deps from each failing test's xfail reason.
    cited_per_test: dict[FailingTest, frozenset[str]] = {}
    for ft in warrior_failures:
        cited = frozenset(_TICKET_ID_RE.findall(ft.xfail_reason or ""))
        cited_per_test[ft] = cited

    cited_deps: frozenset[str] = frozenset()
    for cited in cited_per_test.values():
        cited_deps = cited_deps | cited

    missing_deps = cited_deps - sage_specified_deps

    # Step 2: any failing test with NO xfail_reason and real-failure kind
    # -> WARRIOR_BUG (raw assertion; not Sage's fault even when memo empty).
    for ft in warrior_failures:
        if not (ft.xfail_reason or "").strip() and ft.failure_kind == "real_failure":
            return BounceClassification(
                verdict=ClassifierVerdict.WARRIOR_BUG,
                failing_tests=tuple(warrior_failures),
                cited_deps=cited_deps,
                sage_specified_deps=sage_specified_deps,
                missing_deps=missing_deps,
                under_marked_tests=(),
            )

    # If no deps are cited at all, the failure has no Sage hook to escalate
    # against -> WARRIOR_BUG (raw failure with empty xfail string maps here).
    if not cited_deps:
        return BounceClassification(
            verdict=ClassifierVerdict.WARRIOR_BUG,
            failing_tests=tuple(warrior_failures),
            cited_deps=cited_deps,
            sage_specified_deps=sage_specified_deps,
            missing_deps=missing_deps,
            under_marked_tests=(),
        )

    # Step 3: malformed-memo / parse_source="absent" with cited deps.
    # Sage filed nothing parseable BUT a failing test cites a dep:
    #   - if the memo body has *any* text and parsing returned absent, treat
    #     this as a malformed memo -> WARRIOR_BUG (fail-safe; never silently
    #     blame Sage on unparseable input). Sage §D-CL.2 line 388.
    #   - if the memo is genuinely empty (no text at all), Sage filed
    #     nothing -> SAGE_UNDER_MARKED (Sage clearly under-specified).
    if parsed.parse_source == "absent":
        if (sage_decision_log or "").strip():
            return BounceClassification(
                verdict=ClassifierVerdict.WARRIOR_BUG,
                failing_tests=tuple(warrior_failures),
                cited_deps=cited_deps,
                sage_specified_deps=sage_specified_deps,
                missing_deps=missing_deps,
                under_marked_tests=tuple(
                    ft for ft, cited in cited_per_test.items() if cited - sage_specified_deps
                ),
            )
        # Empty memo + cited xfail dep -> Sage clearly under-specified.
        return BounceClassification(
            verdict=ClassifierVerdict.SAGE_UNDER_MARKED,
            failing_tests=tuple(warrior_failures),
            cited_deps=cited_deps,
            sage_specified_deps=sage_specified_deps,
            missing_deps=missing_deps,
            under_marked_tests=tuple(
                ft for ft, cited in cited_per_test.items() if cited - sage_specified_deps
            ),
        )

    # Step 4: cited deps fully covered by Sage memo -> WARRIOR_BUG.
    # (Sage specified all the deps the failing test mentions; Warrior is
    # the bug source.)
    if not missing_deps:
        return BounceClassification(
            verdict=ClassifierVerdict.WARRIOR_BUG,
            failing_tests=tuple(warrior_failures),
            cited_deps=cited_deps,
            sage_specified_deps=sage_specified_deps,
            missing_deps=missing_deps,
            under_marked_tests=(),
        )

    # Step 5: missing_deps non-empty -> SAGE_UNDER_MARKED.
    # Build the under_marked_tests subset (tests whose cited deps include
    # at least one missing_dep).
    under_marked_tests = tuple(
        ft for ft, cited in cited_per_test.items() if cited - sage_specified_deps
    )
    return BounceClassification(
        verdict=ClassifierVerdict.SAGE_UNDER_MARKED,
        failing_tests=tuple(warrior_failures),
        cited_deps=cited_deps,
        sage_specified_deps=sage_specified_deps,
        missing_deps=missing_deps,
        under_marked_tests=under_marked_tests,
    )
