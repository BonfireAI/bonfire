# === Knight B INNOVATION (lines 201+) ===
"""RED tests for MergePreflightHandler — classifier/integration innovation surface.

Knight B owns lines 201+ (classifier algorithm, JUnit XML parser, stdout
fallback, sibling detection, metadata key registry). Knight A's section
(lines 1-200) handles imports, fixtures, and the 6 conservative-pattern
test classes (TestProtocolConformance, TestPRNumberExtraction,
TestWizardVerdictGate, TestErrorPaths, TestNeverRaises,
TestModuleRoleConstant).

The two sections are written in parallel into independent worktrees and
will be concatenated by the Wizard at contract-lock under banner-comment
discipline (Sage memo §D-CL.2 lines 923-930).

Per Sage memo bon-519-sage-20260428T033101Z.md:
- §D-CL.2 (lines 857-934) -- Knight B contract.
- §A Q4 (lines 79-122) -- classifier algorithm, 6-verdict return type,
  first-match-wins ordering.
- §A Q5 (lines 124-142) -- sibling detection algorithm.
- §A Q6 line 156 -- pre_existing_debt -> ALLOW-WITH-ANNOTATION (Anta-ratified).
- §D4 (lines 383-470) -- classifier function signature + edge case table.
- §D5 (lines 473-522) -- gh client extension + sibling detection function.
- §D10 line 753 -- META_PREFLIGHT_* registry in models/envelope.py.

All tests in this section MUST FAIL on first run (TDD RED): the classifier,
parser, sibling detection, FailingTest dataclass, PreflightVerdict enum,
PreflightClassification dataclass, and META_PREFLIGHT_* constants do not
yet exist on disk. ImportError is the expected failure shape.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Knight B fixtures (independent of Knight A's fixtures; harmless duplicates
# at concatenation time -- pytest tolerates duplicate top-level helpers).
# ---------------------------------------------------------------------------


def _make_failing_test(
    file_path: str = "tests/unit/test_x.py",
    classname: str = "tests.unit.test_x.TestX",
    name: str = "test_y",
    message: str = "AssertionError: boom",
    traceback_files: tuple[str, ...] = (),
):
    """Build a FailingTest dataclass instance.

    Lazy-imported per Sage §D-CL.2 line 878 (no top-level import of innovation
    surface symbols -- they fail-import in RED).
    """
    from bonfire.handlers.merge_preflight import FailingTest

    return FailingTest(
        file_path=file_path,
        classname=classname,
        name=name,
        message=message,
        traceback_files=traceback_files,
    )


# ---------------------------------------------------------------------------
# Classifier — pure-function tests (no I/O, no clock, no random)
# Sage §D-CL.2 line 878-883 + §D4 lines 437-470.
# ---------------------------------------------------------------------------


class TestClassifierGreenPath:
    """returncode=0 + empty failures -> GREEN. No siblings, no baseline.

    Sage §D4 line 449 (step 2: failing_tests is empty AND returncode == 0
    -> GREEN).
    """

    def test_empty_failures_returncode_zero_returns_green(self) -> None:
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        result = classify_pytest_run(
            pytest_returncode=0,
            pytest_duration_seconds=1.23,
            pytest_stdout="1 passed in 1.23s\n",
            failing_tests=(),
            sibling_files={},
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.GREEN

    def test_green_path_has_empty_sibling_pr_numbers(self) -> None:
        """GREEN result carries no sibling PR numbers (no intersection occurred)."""
        from bonfire.handlers.merge_preflight import classify_pytest_run

        result = classify_pytest_run(
            pytest_returncode=0,
            pytest_duration_seconds=0.5,
            pytest_stdout="",
            failing_tests=(),
            sibling_files={42: frozenset({"src/foo.py"})},
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.sibling_pr_numbers == ()


class TestClassifierPreExistingDebt:
    """All failure files in baseline -> PRE_EXISTING_DEBT (Sage §D4 line 450).

    Q6 ratified ALLOW-WITH-ANNOTATION: classifier returns the verdict;
    the handler downstream marks META_PREFLIGHT_TEST_DEBT_NOTED. The
    classifier itself is verdict-only.
    """

    def test_single_failure_in_baseline_returns_pre_existing_debt(self) -> None:
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(file_path="tests/unit/test_legacy.py")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=2.5,
            pytest_stdout="FAILED tests/unit/test_legacy.py::TestLegacy::test_old\n",
            failing_tests=(ft,),
            sibling_files={},
            baseline_failures=frozenset({"tests/unit/test_legacy.py"}),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.PRE_EXISTING_DEBT

    def test_all_failures_in_baseline_returns_pre_existing_debt(self) -> None:
        """Multiple failures, all present in baseline -> still PRE_EXISTING_DEBT."""
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft1 = _make_failing_test(file_path="tests/unit/test_a.py", name="test_a")
        ft2 = _make_failing_test(file_path="tests/unit/test_b.py", name="test_b")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=3.0,
            pytest_stdout="",
            failing_tests=(ft1, ft2),
            sibling_files={},
            baseline_failures=frozenset(
                {"tests/unit/test_a.py", "tests/unit/test_b.py"}
            ),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.PRE_EXISTING_DEBT

    def test_mixed_baseline_and_novel_falls_through_to_warrior_or_cross_wave(self) -> None:
        """Per Sage §D4 line 451 (NOT 'any' -- ALL in baseline). Mixed -> NOT debt.

        Sage edge case table line 467: '2 failures: 1 baseline + 1 novel ->
        falls through to step 4/5 (NOT pre-existing-debt)'.
        """
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft_baseline = _make_failing_test(file_path="tests/unit/test_old.py")
        ft_novel = _make_failing_test(file_path="tests/unit/test_new.py")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=2.0,
            pytest_stdout="",
            failing_tests=(ft_baseline, ft_novel),
            sibling_files={},
            baseline_failures=frozenset({"tests/unit/test_old.py"}),
            sibling_detection_status="ok",
        )
        # Falls through to step 4 (cross-wave check, no siblings) then step 5
        # (PURE_WARRIOR_BUG). MUST NOT be PRE_EXISTING_DEBT.
        assert result.verdict != PreflightVerdict.PRE_EXISTING_DEBT
        assert result.verdict == PreflightVerdict.PURE_WARRIOR_BUG


class TestClassifierCrossWave:
    """Failure file or traceback file ∈ sibling diff -> CROSS_WAVE_INTERACTION.

    Sage §D4 lines 452-453 (step 4: ANY failing-test file path or any
    traceback_files entry intersects union(sibling_files.values())).
    Sage §D-CL.2 line 882-883: sibling_pr_numbers tuple is non-empty AND
    contains the PR number whose files intersected.
    """

    def test_failing_test_file_in_sibling_diff_returns_cross_wave(self) -> None:
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(file_path="tests/unit/test_persona.py")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=2.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={
                17: frozenset({"src/bonfire/persona.py", "tests/unit/test_persona.py"}),
            },
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.CROSS_WAVE_INTERACTION

    def test_cross_wave_records_intersecting_pr_number(self) -> None:
        """Sage §D-CL.2 line 882-883: sibling_pr_numbers non-empty and contains
        the PR number whose files intersected."""
        from bonfire.handlers.merge_preflight import classify_pytest_run

        ft = _make_failing_test(file_path="tests/unit/test_schema.py")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=1.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={
                42: frozenset({"src/other.py"}),
                99: frozenset({"tests/unit/test_schema.py", "src/schema.py"}),
            },
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert len(result.sibling_pr_numbers) > 0
        assert 99 in result.sibling_pr_numbers
        # Non-intersecting PRs may or may not appear, but the intersecting
        # PR MUST appear.

    def test_traceback_file_in_sibling_diff_returns_cross_wave(self) -> None:
        """Sage §D4 line 469: 'Traceback names a file in sibling, but failing
        test file does not -> CROSS_WAVE_INTERACTION (per step 4 "or
        traceback_files")'."""
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(
            file_path="tests/unit/test_isolated.py",  # not in sibling
            traceback_files=("src/bonfire/persona.py",),  # IS in sibling
        )
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=1.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={5: frozenset({"src/bonfire/persona.py"})},
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.CROSS_WAVE_INTERACTION

    def test_sibling_status_error_with_intersection_falls_to_warrior(self) -> None:
        """Sage §D4 line 468: sibling_status='error' -> step 4 yields no
        intersection -> PURE_WARRIOR_BUG (status flagged in result)."""
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(file_path="tests/unit/test_x.py")
        # Even if sibling_files is provided AND would intersect, when
        # sibling_detection_status="error" the classifier MUST NOT produce
        # CROSS_WAVE_INTERACTION (no trustworthy data).
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=1.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={},  # Empty due to detection error
            baseline_failures=frozenset(),
            sibling_detection_status="error",
        )
        assert result.verdict == PreflightVerdict.PURE_WARRIOR_BUG
        assert result.sibling_detection_status == "error"


class TestClassifierPureWarriorBug:
    """No baseline match, no sibling intersection -> PURE_WARRIOR_BUG.

    Sage §D4 line 454 (step 5: 'Otherwise -> PURE_WARRIOR_BUG').
    """

    def test_novel_failure_no_siblings_returns_pure_warrior_bug(self) -> None:
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(file_path="tests/unit/test_brand_new.py")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=1.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={},
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.PURE_WARRIOR_BUG

    def test_novel_failure_with_non_intersecting_siblings_returns_warrior(self) -> None:
        """Siblings exist but their files don't intersect failing tests."""
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(
            file_path="tests/unit/test_isolated.py",
            traceback_files=("src/bonfire/isolated.py",),
        )
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=1.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={
                5: frozenset({"src/elsewhere.py", "tests/unit/test_other.py"}),
            },
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.PURE_WARRIOR_BUG


class TestClassifierEdgeCases:
    """Sage §D4 lines 458-470 — edge cases including pytest_collection_error,
    merge_conflict, parametrize variants, first-match-wins ordering."""

    def test_empty_inputs_returns_green(self) -> None:
        """All-empty inputs (no failing tests, no siblings, no baseline) -> GREEN."""
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        result = classify_pytest_run(
            pytest_returncode=0,
            pytest_duration_seconds=0.1,
            pytest_stdout="",
            failing_tests=(),
            sibling_files={},
            baseline_failures=frozenset(),
            sibling_detection_status="skipped",
        )
        assert result.verdict == PreflightVerdict.GREEN

    def test_pytest_collection_error_returncode_nonzero_no_failures(self) -> None:
        """rc != 0 AND failing_tests empty -> PYTEST_COLLECTION_ERROR.

        Sage §D4 line 448 (step 1) + §A Q4 line 106.
        """
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        result = classify_pytest_run(
            pytest_returncode=4,  # pytest collection-error exit code
            pytest_duration_seconds=0.2,
            pytest_stdout="ERROR: ImportError while importing test module\n",
            failing_tests=(),
            sibling_files={},
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.PYTEST_COLLECTION_ERROR

    @pytest.mark.parametrize(
        "junit_class_path,expected_file",
        [
            ("tests/unit/test_x.py::TestY::test_z", "tests/unit/test_x.py"),
            ("tests/unit/test_x.py::TestY::test_z[param-1]", "tests/unit/test_x.py"),
            ("tests/unit/test_x.py::test_z[param-A]", "tests/unit/test_x.py"),
            ("tests/unit/test_parametrize.py::test_a[1-2-3]", "tests/unit/test_parametrize.py"),
        ],
    )
    def test_parametrize_variants_extract_file_path(
        self, junit_class_path: str, expected_file: str
    ) -> None:
        """Parametrize-generated failures: file path is the same as the
        parametrize source. Sage §D4 line 458 (parametrize edge case).

        The classifier operates on FailingTest.file_path which the parser
        is responsible for extracting. This test asserts the classifier
        treats file paths uniformly regardless of parametrize suffixes.
        """
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(file_path=expected_file)
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=0.5,
            pytest_stdout=f"FAILED {junit_class_path}\n",
            failing_tests=(ft,),
            sibling_files={7: frozenset({expected_file})},
            baseline_failures=frozenset(),
            sibling_detection_status="ok",
        )
        # file in sibling -> CROSS_WAVE_INTERACTION
        assert result.verdict == PreflightVerdict.CROSS_WAVE_INTERACTION
        assert 7 in result.sibling_pr_numbers

    def test_first_match_wins_baseline_before_sibling(self) -> None:
        """Sage §A Q4 line 87 (first match wins ordering): if a failing test
        is BOTH in baseline AND in sibling files, classifier returns
        PRE_EXISTING_DEBT (step 3 fires before step 4).
        """
        from bonfire.handlers.merge_preflight import (
            PreflightVerdict,
            classify_pytest_run,
        )

        ft = _make_failing_test(file_path="tests/unit/test_overlap.py")
        result = classify_pytest_run(
            pytest_returncode=1,
            pytest_duration_seconds=1.0,
            pytest_stdout="",
            failing_tests=(ft,),
            sibling_files={11: frozenset({"tests/unit/test_overlap.py"})},
            # Same file is ALSO in baseline -- step 3 must fire first.
            baseline_failures=frozenset({"tests/unit/test_overlap.py"}),
            sibling_detection_status="ok",
        )
        assert result.verdict == PreflightVerdict.PRE_EXISTING_DEBT

    def test_merge_conflict_verdict_exists_in_enum(self) -> None:
        """Sage §D2 step 5 line 274 + §D4 line 396: MERGE_CONFLICT is a
        verdict literal. The pipeline blocks on this verdict. The classifier
        does not produce MERGE_CONFLICT directly (handler shell does, when
        diff fails to apply); but the enum MUST expose it as a member so
        the handler can construct the result."""
        from bonfire.handlers.merge_preflight import PreflightVerdict

        # Enum membership check.
        assert hasattr(PreflightVerdict, "MERGE_CONFLICT")
        assert PreflightVerdict.MERGE_CONFLICT.value == "merge_conflict"


# ---------------------------------------------------------------------------
# JUnit XML parser — Sage §D-CL.2 lines 884-888 + §D4 line 421-427.
# ---------------------------------------------------------------------------


class TestJunitXmlParser:
    """parse_pytest_junit_xml: well-formed, malformed, missing file."""

    def test_well_formed_xml_returns_two_failing_tests(self, tmp_path) -> None:
        """1 passing + 2 failing tests in JUnit XML -> 2 FailingTest entries
        with correct file/class/name/traceback. Sage §D-CL.2 line 885-886.
        """
        from bonfire.handlers.merge_preflight import (
            FailingTest,
            parse_pytest_junit_xml,
        )

        xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="3" errors="0" failures="2">
    <testcase classname="tests.unit.test_x" name="test_pass" file="tests/unit/test_x.py" time="0.001"/>
    <testcase classname="tests.unit.test_x" name="test_fail_one" file="tests/unit/test_x.py" time="0.002">
      <failure message="AssertionError: expected 1 got 2">tests/unit/test_x.py:42: in test_fail_one
    assert 1 == 2
AssertionError</failure>
    </testcase>
    <testcase classname="tests.unit.test_y" name="test_fail_two" file="tests/unit/test_y.py" time="0.003">
      <failure message="ValueError">tests/unit/test_y.py:10: in test_fail_two
    raise ValueError</failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml)
        result = parse_pytest_junit_xml(xml_path)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(ft, FailingTest) for ft in result)
        files = {ft.file_path for ft in result}
        assert "tests/unit/test_x.py" in files
        assert "tests/unit/test_y.py" in files

    def test_malformed_xml_returns_empty_tuple_fail_safe(self, tmp_path) -> None:
        """Sage §D-CL.2 line 887: malformed XML -> empty tuple (fail-safe,
        NEVER fail-open into green). The caller treats empty + rc!=0 as
        PYTEST_COLLECTION_ERROR.
        """
        from bonfire.handlers.merge_preflight import parse_pytest_junit_xml

        xml_path = tmp_path / "bad.xml"
        xml_path.write_text("<<this is not valid xml>>>")
        result = parse_pytest_junit_xml(xml_path)
        assert result == ()

    def test_missing_file_returns_empty_tuple(self, tmp_path) -> None:
        """Sage §D-CL.2 line 888: missing file -> empty tuple."""
        from bonfire.handlers.merge_preflight import parse_pytest_junit_xml

        missing = tmp_path / "does-not-exist.xml"
        result = parse_pytest_junit_xml(missing)
        assert result == ()

    def test_empty_testsuite_returns_empty_tuple(self, tmp_path) -> None:
        """Well-formed XML with no failing testcases -> empty tuple."""
        from bonfire.handlers.merge_preflight import parse_pytest_junit_xml

        xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="1" errors="0" failures="0">
    <testcase classname="t" name="ok" file="tests/x.py" time="0.001"/>
  </testsuite>
</testsuites>
"""
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml)
        result = parse_pytest_junit_xml(xml_path)
        assert result == ()


# ---------------------------------------------------------------------------
# Stdout fallback parser — Sage §D-CL.2 lines 890-892 + §D4 lines 429-433.
# ---------------------------------------------------------------------------


class TestStdoutFallbackParser:
    """Regex extracts FAILED lines from pytest stdout when JUnit XML is absent."""

    def test_simple_failed_line_extracts_file_class_name(self) -> None:
        """Sage §D-CL.2 line 891: pytest stdout snippet with
        'FAILED tests/x.py::TestY::test_z' lines -> parsed correctly."""
        from bonfire.handlers.merge_preflight import parse_pytest_stdout_fallback

        stdout = """=================== FAILURES ===================
___________________ TestY.test_z ___________________
FAILED tests/x.py::TestY::test_z - AssertionError: nope
=================== 1 failed in 0.5s ==================="""
        result = parse_pytest_stdout_fallback(stdout)
        assert isinstance(result, tuple)
        assert len(result) >= 1
        # At least one FailingTest with the right file_path.
        assert any(ft.file_path == "tests/x.py" for ft in result)

    def test_parametrize_variant_extracts_file_path(self) -> None:
        """Sage §D-CL.2 line 892: 'FAILED tests/x.py::test_z[param-1]' ->
        file path extracted as 'tests/x.py' (NOT 'tests/x.py[param-1]')."""
        from bonfire.handlers.merge_preflight import parse_pytest_stdout_fallback

        stdout = "FAILED tests/x.py::test_z[param-1] - boom\n"
        result = parse_pytest_stdout_fallback(stdout)
        assert any(ft.file_path == "tests/x.py" for ft in result)

    def test_no_failed_lines_returns_empty_tuple(self) -> None:
        """All-pass stdout -> empty tuple (no failures parsed)."""
        from bonfire.handlers.merge_preflight import parse_pytest_stdout_fallback

        stdout = "============= 100 passed in 5.5s =============\n"
        result = parse_pytest_stdout_fallback(stdout)
        assert result == ()


# ---------------------------------------------------------------------------
# Sibling detection — Sage §D-CL.2 lines 894-898 + §D5 lines 510-522.
# ---------------------------------------------------------------------------


class TestSiblingDetection:
    """detect_sibling_prs: ok / skipped / error / empty list."""

    async def test_zero_open_prs_returns_empty_dict_ok_status(self) -> None:
        """Mock with 0 open PRs -> ({}, 'ok')."""
        from bonfire.github import MockGitHubClient
        from bonfire.handlers.merge_preflight import detect_sibling_prs

        mock = MockGitHubClient()
        files_by_pr, status = await detect_sibling_prs(
            mock, "master", current_pr_number=42
        )
        assert files_by_pr == {}
        assert status == "ok"

    async def test_one_open_pr_returns_populated_dict(self) -> None:
        """Sage §D-CL.2 line 896: detect_sibling_prs returns
        ({pr_n: file_set}, 'ok')."""
        from bonfire.github import MockGitHubClient
        from bonfire.handlers.merge_preflight import detect_sibling_prs

        mock = MockGitHubClient()
        # Mock must be configurable with canned siblings; test asserts the
        # public configuration interface works (per Sage §D-CL.2 line 895).
        # Configuration shape: list_open_prs returns canned PRSummary list
        # and current_pr_number is excluded.
        mock.set_open_prs(  # type: ignore[attr-defined]
            base="master",
            prs=[
                {
                    "number": 17,
                    "head_branch": "feat/peer",
                    "title": "peer pr",
                    "file_paths": ("src/bonfire/persona.py",),
                },
            ],
        )
        files_by_pr, status = await detect_sibling_prs(
            mock, "master", current_pr_number=42
        )
        assert status == "ok"
        assert 17 in files_by_pr
        assert "src/bonfire/persona.py" in files_by_pr[17]

    async def test_current_pr_excluded_from_results(self) -> None:
        """detect_sibling_prs MUST exclude current_pr_number from siblings
        (Sage §A Q5 line 132 step 3: 'Filter: exclude PR N itself')."""
        from bonfire.github import MockGitHubClient
        from bonfire.handlers.merge_preflight import detect_sibling_prs

        mock = MockGitHubClient()
        mock.set_open_prs(  # type: ignore[attr-defined]
            base="master",
            prs=[
                {
                    "number": 42,  # current PR; MUST be filtered
                    "head_branch": "feat/me",
                    "title": "self",
                    "file_paths": ("src/me.py",),
                },
                {
                    "number": 17,
                    "head_branch": "feat/peer",
                    "title": "peer",
                    "file_paths": ("src/peer.py",),
                },
            ],
        )
        files_by_pr, status = await detect_sibling_prs(
            mock, "master", current_pr_number=42
        )
        assert 42 not in files_by_pr
        assert 17 in files_by_pr

    async def test_runtime_error_from_client_returns_error_status(self) -> None:
        """Sage §D-CL.2 line 898 + §D5 line 518: list_open_prs raising
        RuntimeError -> ({}, 'error') (graceful degradation, no exception
        bubbles)."""
        from bonfire.handlers.merge_preflight import detect_sibling_prs

        class _RaisingClient:
            async def list_open_prs(self, base, *, exclude=None):
                raise RuntimeError("gh CLI exploded")

        files_by_pr, status = await detect_sibling_prs(
            _RaisingClient(), "master", current_pr_number=1
        )
        assert files_by_pr == {}
        assert status == "error"


# ---------------------------------------------------------------------------
# Metadata key registry — Sage §D-CL.2 lines 900-901 + §D10 line 753.
# ---------------------------------------------------------------------------


class TestPreflightMetadataKeys:
    """META_PREFLIGHT_CLASSIFICATION + META_PREFLIGHT_TEST_DEBT_NOTED live
    in bonfire.models.envelope (Sage §D10 line 753)."""

    def test_meta_preflight_classification_importable(self) -> None:
        from bonfire.models.envelope import META_PREFLIGHT_CLASSIFICATION

        assert isinstance(META_PREFLIGHT_CLASSIFICATION, str)
        assert META_PREFLIGHT_CLASSIFICATION  # non-empty

    def test_meta_preflight_test_debt_noted_importable(self) -> None:
        from bonfire.models.envelope import META_PREFLIGHT_TEST_DEBT_NOTED

        assert isinstance(META_PREFLIGHT_TEST_DEBT_NOTED, str)
        assert META_PREFLIGHT_TEST_DEBT_NOTED  # non-empty

    def test_meta_preflight_keys_are_distinct(self) -> None:
        """Sage §D-CL.2 line 901 (implicit): the two new keys are distinct
        from each other AND from existing META_* keys (no collision)."""
        from bonfire.models.envelope import (
            META_PR_NUMBER,
            META_PR_URL,
            META_PREFLIGHT_CLASSIFICATION,
            META_PREFLIGHT_TEST_DEBT_NOTED,
            META_REVIEW_SEVERITY,
            META_REVIEW_VERDICT,
            META_TICKET_REF,
        )

        all_keys = {
            META_PR_NUMBER,
            META_PR_URL,
            META_REVIEW_SEVERITY,
            META_REVIEW_VERDICT,
            META_TICKET_REF,
            META_PREFLIGHT_CLASSIFICATION,
            META_PREFLIGHT_TEST_DEBT_NOTED,
        }
        # All seven distinct -- no collisions, no aliasing.
        assert len(all_keys) == 7
        assert META_PREFLIGHT_CLASSIFICATION != META_PREFLIGHT_TEST_DEBT_NOTED
