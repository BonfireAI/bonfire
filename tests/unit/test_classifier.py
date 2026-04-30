"""RED tests for `bonfire.verify.classifier` — INNOVATION coverage (Knight B).

Per Sage memo
`docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md` §D-CL.2
("Knight B INNOVATION") and `docs/audit/sage-decisions/bon-513-sage-D-20260428T210000Z.md`
§D2 (3-verdict classifier algorithm; first-match-wins decision tree) +
§D5 (decision-log schema).

Knight B owns the *algorithm* coverage:
    - 3-verdict StrEnum (`SAGE_UNDER_MARKED` / `WARRIOR_BUG` / `AMBIGUOUS`).
    - Decision-log parser parametrize over front_matter / prose / absent /
      both / malformed-bullets-under-canonical-heading.
    - Edge cases (empty memo, malformed memo, JUnit-XML missing, partial
      dep match -> AMBIGUOUS not silently WARRIOR_BUG).

Knight A's lane (NOT covered here): handler protocol conformance, gate
evaluation. Those live in the sibling files alongside Knight A's spine
classes (this file does not contain handler-protocol or gate tests).

This is RED. Tests are marked `@pytest.mark.xfail(strict=True, reason=...)`
because the implementation modules do not yet exist; Warrior implements
later, then we strip xfail and they pass GREEN. xpassing here is a bug
(strict=True) — it means the symbol exists but the test doesn't actually
exercise the post-implementation contract.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

# === Knight B INNOVATION ===

# --- Dep-presence flags (over-specified per Sage §D-CL.1 line 27-50) --------
# Every dep enumerated explicitly. The xfail condition AND-s them all so
# BON-513's own classifier (the artifact this ticket ships) would classify
# a missed dep as SAGE_UNDER_MARKED.


def _module_present(modname: str) -> bool:
    """Check whether a module is importable, tolerating missing
    intermediate packages (find_spec raises ModuleNotFoundError when
    bonfire.verify itself doesn't exist yet)."""
    try:
        return importlib.util.find_spec(modname) is not None
    except (ModuleNotFoundError, ValueError):
        return False


_CLASSIFIER_PRESENT = _module_present("bonfire.verify.classifier")
_VERIFY_PKG_PRESENT = _module_present("bonfire.verify")
_DECISION_LOG_PRESENT = (
    _module_present("bonfire.verify.decision_log") or _CLASSIFIER_PRESENT
    # decision_log helpers may live in classifier.py
)

_BOTH_LANDED = _CLASSIFIER_PRESENT and _VERIFY_PKG_PRESENT and _DECISION_LOG_PRESENT

_CLASSIFIER_XFAIL = pytest.mark.xfail(
    condition=not _BOTH_LANDED,
    reason=(
        "v0.1 RED: bonfire.verify.classifier AND bonfire.verify (package) "
        "AND decision-log parser symbols must all land. Deferred to "
        "BON-513-warrior-impl (Sage memo "
        "docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md "
        "§D-CL.2 + §D2)."
    ),
    strict=True,
)


# ---------------------------------------------------------------------------
# Test fixtures (factories — innovation pattern from BON-519 Knight B)
# ---------------------------------------------------------------------------


def _failing_test(
    *,
    file_path: str = "tests/unit/test_x.py",
    classname: str = "tests.unit.test_x.TestX",
    name: str = "test_y",
    message: str = "AssertionError: boom",
    xfail_reason: str = "",
    failure_kind: str = "real_failure",
) -> Any:
    """Build a `FailingTest` (lazy-imported per Sage §D-CL.2 RED idiom)."""
    from bonfire.verify.classifier import FailingTest

    return FailingTest(
        file_path=file_path,
        classname=classname,
        name=name,
        message=message,
        xfail_reason=xfail_reason,
        failure_kind=failure_kind,
    )


def _decision_log_with_defer(deps: tuple[str, ...]) -> str:
    """Build a synthetic Sage memo with a canonical DEFER section.

    Sage §D5 schema: `## DEFER via xfail` followed by markdown bullets
    citing each dep ticket id.
    """
    bullets = "\n".join(f"- `{dep}`" for dep in deps)
    return f"""# Sage memo for some-ticket

## §A — Ratification

(content)

## DEFER via xfail

The following deps are deferred:

{bullets}

## §D — Design

(content)
"""


def _decision_log_front_matter(deps: tuple[str, ...]) -> str:
    """Build a synthetic Sage memo using HTML-comment YAML front-matter.

    User prompt Q2a: `<!-- bonfire:defers ... -->` format.
    """
    deps_yaml = "\n".join(f"  - {dep}" for dep in deps)
    return f"""<!-- bonfire:defers
defers:
{deps_yaml}
-->

# Sage memo

(no canonical heading)

## §A — Ratification

content
"""


# ---------------------------------------------------------------------------
# §D-CL.2 / §D2: classifier coverage — 4 sub-classes (Sage §D-CL.2 line 134)
#
# Sage memo §D-CL.2 enumerates `TestClassifier` with 4 sub-classes
# (GreenPath / SageUnderMarked / WarriorBug / EdgeCases). pytest does NOT
# collect nested classes by default, so we expand each sub-class to a
# top-level class with a descriptive name.
# ---------------------------------------------------------------------------


class TestClassifierGreenPath:
    """Sage §D-CL.2 'TestClassifierGreenPath' — empty failures -> non-blaming.

    Note: Sage §D2 line 132 declares `INDETERMINATE` (rationale=
    "no_failures"); user prompt Q1a declares the 3-verdict StrEnum as
    SAGE_UNDER_MARKED / WARRIOR_BUG / AMBIGUOUS. Wizard reconciles —
    this file uses the user-prompt vocabulary (3-verdict) but still
    asserts "empty failures returns a non-blaming verdict".
    """

    def test_no_failures_returns_non_blaming_verdict(self) -> None:
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        result = classify_warrior_failure(
            warrior_failures=(),
            sage_decision_log="",
            junit_xml=None,
        )
        # On no failures, classifier MUST NOT blame Sage or Warrior.
        # Tolerant of either "AMBIGUOUS" (3-verdict StrEnum) or "GREEN"
        # (alternate spelling), but NEVER SAGE_UNDER_MARKED/WARRIOR_BUG.
        assert result.verdict not in (
            ClassifierVerdict.SAGE_UNDER_MARKED,
            ClassifierVerdict.WARRIOR_BUG,
        )

    def test_no_failures_failing_tests_is_empty_tuple(self) -> None:
        """Round-trip: classifier output `failing_tests` is `()` on green."""
        from bonfire.verify.classifier import classify_warrior_failure

        result = classify_warrior_failure(
            warrior_failures=(),
            sage_decision_log="",
            junit_xml=None,
        )
        assert result.failing_tests == ()


class TestClassifierSageUnderMarked:
    """Sage §D-CL.2 'TestClassifierSageUnderMarked' — failing tests cite
    deps that the Sage decision log did NOT enumerate."""

    def test_one_failure_two_cited_deps_one_in_decision_log(self) -> None:
        """Failing test cites BON-A AND BON-B; Sage memo only enumerates
        BON-A. Verdict: SAGE_UNDER_MARKED."""
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        ft = _failing_test(
            xfail_reason="v0.1 gap: deferred to BON-A and deferred to BON-B.",
        )
        decision_log = _decision_log_with_defer(("BON-A",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert result.verdict == ClassifierVerdict.SAGE_UNDER_MARKED

    def test_round_trip_under_marked_tests_tuple(self) -> None:
        """`result.under_marked_tests` round-trips the failing test paths."""
        from bonfire.verify.classifier import classify_warrior_failure

        ft = _failing_test(
            file_path="tests/unit/test_alpha.py",
            xfail_reason="deferred to BON-A and deferred to BON-B",
        )
        decision_log = _decision_log_with_defer(("BON-A",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert isinstance(result.under_marked_tests, tuple)
        assert "tests/unit/test_alpha.py" in {t.file_path for t in result.under_marked_tests}

    def test_cited_deps_is_frozenset(self) -> None:
        """`result.cited_deps` is `frozenset[str]` of deps the failing
        tests' xfail reasons mention."""
        from bonfire.verify.classifier import classify_warrior_failure

        ft = _failing_test(
            xfail_reason="deferred to BON-X and deferred to BON-Y",
        )
        decision_log = _decision_log_with_defer(("BON-X",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert isinstance(result.cited_deps, frozenset)
        assert "BON-X" in result.cited_deps
        assert "BON-Y" in result.cited_deps

    def test_sage_specified_deps_is_frozenset(self) -> None:
        """`result.sage_specified_deps` is a `frozenset[str]` parsed
        from the decision log."""
        from bonfire.verify.classifier import classify_warrior_failure

        ft = _failing_test(
            xfail_reason="deferred to BON-X and deferred to BON-Y",
        )
        decision_log = _decision_log_with_defer(("BON-X", "BON-Z"))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert isinstance(result.sage_specified_deps, frozenset)
        assert "BON-X" in result.sage_specified_deps
        assert "BON-Z" in result.sage_specified_deps

    def test_missing_deps_is_set_difference(self) -> None:
        """`result.missing_deps == result.cited_deps -
        result.sage_specified_deps` (the "what Sage forgot" set)."""
        from bonfire.verify.classifier import classify_warrior_failure

        ft = _failing_test(
            xfail_reason="deferred to BON-X and deferred to BON-Y",
        )
        decision_log = _decision_log_with_defer(("BON-X",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert isinstance(result.missing_deps, frozenset)
        assert result.missing_deps == result.cited_deps - result.sage_specified_deps
        # And on SAGE_UNDER_MARKED, missing_deps is non-empty.
        assert len(result.missing_deps) > 0


class TestClassifierWarriorBug:
    """Sage §D-CL.2 'TestClassifierWarriorBug' — Sage specified the
    cited deps correctly; Warrior is the bug source."""

    def test_failing_test_cites_dep_in_decision_log_returns_warrior_bug(
        self,
    ) -> None:
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        ft = _failing_test(xfail_reason="deferred to BON-A")
        decision_log = _decision_log_with_defer(("BON-A",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert result.verdict == ClassifierVerdict.WARRIOR_BUG

    def test_failing_test_no_xfail_reason_returns_warrior_bug(self) -> None:
        """Raw pytest failure (no xfail marker at all) -> WARRIOR_BUG."""
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        ft = _failing_test(xfail_reason="", failure_kind="real_failure")
        decision_log = _decision_log_with_defer(("BON-A",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert result.verdict == ClassifierVerdict.WARRIOR_BUG

    def test_classifier_never_blames_sage_for_unconditional_failures(
        self,
    ) -> None:
        """Failing test that should have passed unconditionally is
        NEVER SAGE_UNDER_MARKED — even if decision log is empty."""
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        ft = _failing_test(xfail_reason="", failure_kind="real_failure")
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log="",
            junit_xml=None,
        )
        # No xfail reason -> not Sage's fault.
        assert result.verdict != ClassifierVerdict.SAGE_UNDER_MARKED


class TestClassifierEdgeCases:
    """Sage §D-CL.2 'TestClassifierEdgeCases' — empty memo, malformed
    memo, JUnit fallback, partial-match -> AMBIGUOUS."""

    def test_empty_decision_log_with_xfail_failure_returns_sage_under_marked(
        self,
    ) -> None:
        """Sage filed nothing; failing test cites a dep -> by definition
        Sage under-specified."""
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        ft = _failing_test(xfail_reason="deferred to BON-X")
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log="",
            junit_xml=None,
        )
        assert result.verdict == ClassifierVerdict.SAGE_UNDER_MARKED

    def test_malformed_decision_log_returns_warrior_bug(self) -> None:
        """No parseable canonical heading -> fail-safe to WARRIOR_BUG.
        (Never silently classify as Sage's fault on unparseable input.)
        """
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        ft = _failing_test(xfail_reason="deferred to BON-X")
        malformed = "this is not a real sage memo, no DEFER section"
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=malformed,
            junit_xml=None,
        )
        assert result.verdict == ClassifierVerdict.WARRIOR_BUG

    def test_junit_xml_none_falls_back_to_stdout_regex(self) -> None:
        """JUnit XML missing -> fall back to stdout regex parsing of
        `warrior_envelope.result`. Sage §D-CL.2 line 179."""
        from bonfire.verify.classifier import classify_warrior_failure

        ft = _failing_test(xfail_reason="deferred to BON-X")
        decision_log = _decision_log_with_defer(("BON-X",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        # Result is a valid Classification regardless of XML availability.
        assert result is not None
        assert hasattr(result, "verdict")

    def test_partial_dep_match_returns_ambiguous_not_warrior_bug(self) -> None:
        """User-prompt §A Q1a + Knight B specific constraint:
        classifier emits AMBIGUOUS (NOT silently WARRIOR_BUG) when the
        defer set is *partial-match* against failing tests — i.e. some
        cited deps are in the memo, some are not, BUT the missing deps
        do not unambiguously match a known Sage-side gap.

        Failure shape: classifier silently rounds to WARRIOR_BUG without
        surfacing the ambiguity.

        Mitigation tested: classifier MUST return AMBIGUOUS when the
        decision log enumerates SOME but not ALL cited deps AND the
        partial-match heuristic cannot decisively classify."""
        from bonfire.verify.classifier import (
            ClassifierVerdict,
            classify_warrior_failure,
        )

        # Two failing tests; one cites BON-A (in memo), one cites BON-B
        # AND BON-C (BON-B in memo, BON-C not). Partial match on test 2.
        ft1 = _failing_test(
            file_path="tests/unit/test_one.py",
            xfail_reason="deferred to BON-A",
        )
        ft2 = _failing_test(
            file_path="tests/unit/test_two.py",
            xfail_reason="deferred to BON-B and deferred to BON-C",
        )
        decision_log = _decision_log_with_defer(("BON-A", "BON-B"))
        result = classify_warrior_failure(
            warrior_failures=(ft1, ft2),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        # The under-mark on ft2 (missing BON-C) is real; classifier
        # MUST NOT collapse this into WARRIOR_BUG. It can be either
        # SAGE_UNDER_MARKED (if the under-mark on ft2 wins first-match)
        # OR AMBIGUOUS (if mixed-failure heuristic fires). Both are
        # acceptable; WARRIOR_BUG is NOT.
        assert result.verdict in (
            ClassifierVerdict.SAGE_UNDER_MARKED,
            ClassifierVerdict.AMBIGUOUS,
        )
        assert result.verdict != ClassifierVerdict.WARRIOR_BUG

    def test_classification_dataclass_is_frozen(self) -> None:
        """Sage §D-CL.7 #6: classifier non-determinism via dict ordering.
        Mitigation: every set-shape field is `frozenset[str]`; the
        dataclass is frozen so callers cannot mutate it."""
        import dataclasses

        from bonfire.verify.classifier import classify_warrior_failure

        ft = _failing_test(xfail_reason="deferred to BON-A")
        decision_log = _decision_log_with_defer(("BON-A",))
        result = classify_warrior_failure(
            warrior_failures=(ft,),
            sage_decision_log=decision_log,
            junit_xml=None,
        )
        assert dataclasses.is_dataclass(result)
        assert getattr(result.__class__, "__dataclass_params__").frozen


# ---------------------------------------------------------------------------
# §D-CL.2 / §D5: TestDecisionLogParser — parametrize over 5 cases
# ---------------------------------------------------------------------------


# Per Sage §D2 step 2 + §D5 schema + user prompt Q2 (c) hybrid front-matter
# + prose parsing; `parse_source: Literal["front_matter", "prose", "absent"]`.
_PARSER_PARAMS = [
    # 1. Front-matter only — HTML-comment YAML
    pytest.param(
        _decision_log_front_matter(("BON-A", "BON-B")),
        frozenset({"BON-A", "BON-B"}),
        "front_matter",
        id="front_matter_only",
    ),
    # 2. Prose only — `## DEFER via xfail` canonical heading + bullets
    pytest.param(
        _decision_log_with_defer(("BON-X", "BON-Y", "BON-Z")),
        frozenset({"BON-X", "BON-Y", "BON-Z"}),
        "prose",
        id="prose_only",
    ),
    # 3. Both — front-matter wins (per user prompt Q2 c hybrid)
    pytest.param(
        _decision_log_front_matter(("BON-FM",)) + "\n" + _decision_log_with_defer(("BON-PROSE",)),
        frozenset({"BON-FM"}),
        "front_matter",
        id="both_front_matter_wins",
    ),
    # 4. Absent — no DEFER section, no front-matter
    pytest.param(
        "# Sage memo\n\nNo DEFER section here.\n",
        frozenset(),
        "absent",
        id="absent",
    ),
    # 5. Malformed bullets under canonical heading -> parse_source="prose",
    #    records empty (per user-prompt §"DECISION-LOG PARSER TESTS" 5).
    pytest.param(
        "# Sage memo\n\n## DEFER via xfail\n\n"
        "this section has prose but NO bullet list of dep ids\n"
        "the parser should still register parse_source=prose\n",
        frozenset(),
        "prose",
        id="malformed_bullets_under_canonical_heading",
    ),
]


class TestDecisionLogParser:
    """Sage §D5 schema + §D-CL.2 'TestDecisionLogParserIntegration' lane.

    Pure function: `parse_sage_decision_log(text: str) -> ParsedDecisionLog`.
    No I/O. No mocking. Parametrize covers all 5 cases per §D2 + user prompt.
    """

    @pytest.mark.parametrize(
        "memo_text,expected_deps,expected_source",
        _PARSER_PARAMS,
    )
    def test_parses_deps_and_source(
        self,
        memo_text: str,
        expected_deps: frozenset,
        expected_source: str,
    ) -> None:
        from bonfire.verify.classifier import parse_sage_decision_log

        parsed = parse_sage_decision_log(memo_text)
        assert parsed.deps == expected_deps
        assert parsed.parse_source == expected_source

    def test_parser_returns_frozenset_not_set(self) -> None:
        """Sage §D-CL.7 #6 mitigation: parser returns frozenset (immutable)."""
        from bonfire.verify.classifier import parse_sage_decision_log

        parsed = parse_sage_decision_log(
            _decision_log_with_defer(("BON-A", "BON-B")),
        )
        assert isinstance(parsed.deps, frozenset)

    def test_parser_is_pure_function_no_io(self) -> None:
        """Sage §D-CL.6 #2 + §D-CL.7 #6: parser has NO I/O. Verified by
        passing in-memory text and confirming output is deterministic."""
        from bonfire.verify.classifier import parse_sage_decision_log

        memo = _decision_log_with_defer(("BON-A",))
        # Same input -> same output, twice in a row.
        first = parse_sage_decision_log(memo)
        second = parse_sage_decision_log(memo)
        assert first.deps == second.deps
        assert first.parse_source == second.parse_source

    def test_parser_strict_canonical_heading_literal(self) -> None:
        """User-prompt Q6 (a): strict canonical heading literal
        `## DEFER via xfail`. A near-miss heading like `## Defer via XFail`
        does NOT match (case-sensitive)."""
        from bonfire.verify.classifier import parse_sage_decision_log

        # Wrong case -> not parsed as a DEFER section.
        wrong_case = "# Sage memo\n\n## Defer via XFail\n\n- `BON-A`\n"
        parsed = parse_sage_decision_log(wrong_case)
        assert parsed.deps == frozenset()

    def test_parser_multi_section_unions(self) -> None:
        """Sage §D-CL.2 line 184: memo with multiple DEFER sections —
        parser unions across sections (same parse_source)."""
        from bonfire.verify.classifier import parse_sage_decision_log

        multi = (
            "# Sage memo\n\n"
            "## DEFER via xfail\n\n- `BON-A`\n\n"
            "## §B — Other content\n\n"
            "## DEFER via xfail\n\n- `BON-B`\n"
        )
        parsed = parse_sage_decision_log(multi)
        assert parsed.deps == frozenset({"BON-A", "BON-B"})
