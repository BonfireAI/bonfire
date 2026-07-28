"""Contract for ``bonfire.verify.suite`` — the pytest-run parser.

The parser is the seam where a process result becomes a typed fact. Its
job is narrow and its failure modes are specific: reading ``0 failed`` as
a failure is the exact class of bug the gates are being moved away from,
and calling an empty collection "green" would make every suite-backed
gate vacuous.
"""

from __future__ import annotations

import pytest

from bonfire.verify.suite import SuiteOutcome, parse_pytest_run

_GREEN = "collected 3 items\n\n=========== 3 passed in 0.05s ==========="
_RED = "collected 3 items\n\n===== 1 failed, 2 passed in 0.06s ====="
_ZERO_FAILED = "collected 5 items\n\n===== 5 passed, 0 failed in 0.06s ====="
_EMPTY = "===== no tests ran in 0.01s ====="
_COLLECT_ERROR = "!!!!! Interrupted: 1 error during collection !!!!!\n== 1 error in 0.2s =="


class TestCounts:
    def test_reads_the_summary_counts(self) -> None:
        outcome = parse_pytest_run(0, _GREEN)
        assert outcome.count("passed") == 3
        assert outcome.count("failed") == 0
        assert outcome.collected == 3

    def test_zero_failed_is_zero_not_a_failure(self) -> None:
        """The old gate's regex had to special-case this. A count cannot."""
        outcome = parse_pytest_run(0, _ZERO_FAILED)
        assert outcome.count("failed") == 0
        assert outcome.green is True

    def test_absent_words_are_absent_not_zero(self) -> None:
        outcome = parse_pytest_run(0, _GREEN)
        assert dict(outcome.counts) == {"passed": 3}

    def test_counts_are_immutable(self) -> None:
        outcome = parse_pytest_run(0, _GREEN)
        assert isinstance(outcome.counts, tuple)

    def test_reads_the_last_summary_banner(self) -> None:
        """A short-test-summary section prints several banners; totals are last."""
        output = (
            "collected 3 items\n"
            "=========== short test summary info ===========\n"
            "FAILED tests/test_a.py::test_x\n"
            "===== 1 failed, 2 passed in 0.06s ====="
        )
        outcome = parse_pytest_run(1, output)
        assert outcome.count("failed") == 1
        assert outcome.count("passed") == 2


class TestGreen:
    def test_exit_zero_with_tests_is_green(self) -> None:
        assert parse_pytest_run(0, _GREEN).green is True

    def test_failures_are_not_green(self) -> None:
        assert parse_pytest_run(1, _RED).green is False

    def test_an_empty_collection_is_not_green(self) -> None:
        """Exit 5 has no failures either. Accepting it would make gates vacuous."""
        outcome = parse_pytest_run(5, _EMPTY)
        assert outcome.green is False
        assert outcome.collected_nothing is True

    def test_a_collection_error_is_not_green(self) -> None:
        assert parse_pytest_run(2, _COLLECT_ERROR).green is False


class TestRed:
    def test_a_failing_test_is_red(self) -> None:
        assert parse_pytest_run(1, _RED).red is True

    def test_green_is_not_red(self) -> None:
        assert parse_pytest_run(0, _GREEN).red is False

    @pytest.mark.parametrize(
        ("returncode", "output"),
        [
            (5, _EMPTY),
            (4, "ERROR: file or directory not found: tests/"),
            (3, "INTERNALERROR> Traceback"),
        ],
    )
    def test_a_broken_invocation_is_not_red(self, returncode: int, output: str) -> None:
        """Not-green and red are different claims; only one of them is evidence."""
        outcome = parse_pytest_run(returncode, output)
        assert outcome.green is False
        assert outcome.red is False


class TestShape:
    def test_outcome_is_frozen(self) -> None:
        outcome = parse_pytest_run(0, _GREEN)
        with pytest.raises(AttributeError):
            outcome.returncode = 1  # type: ignore[misc]

    def test_describe_names_the_exit_code(self) -> None:
        assert "exit 1" in parse_pytest_run(1, _RED).describe()

    def test_describe_survives_output_with_no_summary(self) -> None:
        assert "no summary line" in parse_pytest_run(3, "boom").describe()

    def test_tail_is_bounded(self) -> None:
        outcome = parse_pytest_run(0, "x" * 10_000 + _GREEN)
        assert len(outcome.output_tail) <= 2048

    def test_is_a_suite_outcome(self) -> None:
        assert isinstance(parse_pytest_run(0, _GREEN), SuiteOutcome)
