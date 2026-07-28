# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pure parser turning a pytest invocation into a typed suite outcome.

This module exists because the quality gates used to answer "did the tests
pass?" by looking for the word ``"passed"`` in the agent's own prose. That
question has an answer in the world -- a process exit code and a summary
line -- and this is the type that carries it.

No I/O, no clock, no randomness: :func:`parse_pytest_run` takes the return
code and the captured output of an already-finished pytest process and
returns a frozen :class:`SuiteOutcome`. The process itself is run by
:class:`bonfire.engine.gate_state.PytestSuiteProbe`, which is the only
module in this path allowed to touch a subprocess.

Exit-code vocabulary (pytest's own, ``pytest.ExitCode``)::

    0  OK                all collected tests passed
    1  TESTS_FAILED      at least one test failed
    2  INTERRUPTED       run interrupted by the user or a plugin
    3  INTERNAL_ERROR    pytest itself blew up
    4  USAGE_ERROR       bad invocation
    5  NO_TESTS_COLLECTED

``5`` is the one worth naming separately. A suite that collected nothing
exits non-zero, so it is not green -- but it is not *red* either, because
nothing ran. A red-phase gate that accepted it would pass on a typo in the
test path, which is the vacuity trap in a different costume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "EXIT_NO_TESTS_COLLECTED",
    "EXIT_OK",
    "EXIT_TESTS_FAILED",
    "SuiteOutcome",
    "parse_pytest_run",
]

EXIT_OK: int = 0
EXIT_TESTS_FAILED: int = 1
EXIT_NO_TESTS_COLLECTED: int = 5

# Longest tail of captured output retained on the outcome, in characters.
# Bounded so a gate message can never carry an unbounded process dump into
# an envelope or an event payload.
_TAIL_CHARS: int = 2048

# ``N passed``, ``N failed``, ``N error``/``N errors`` in pytest's summary
# line. Anchored on the digits so ``0 failed`` parses as zero rather than
# as "the word failed appeared", which is the whole defect this replaces.
_COUNT_RE: re.Pattern[str] = re.compile(
    r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)\b",
    re.IGNORECASE,
)

# ``collected 12 items`` / ``collected 1 item``, emitted before the run.
_COLLECTED_RE: re.Pattern[str] = re.compile(r"^collected\s+(\d+)\s+item", re.IGNORECASE | re.M)

# pytest's final banner line, e.g. ``===== 3 passed in 0.04s =====``.
_SUMMARY_RE: re.Pattern[str] = re.compile(r"^=+\s.*\s=+$", re.M)

# Outcome words that mean "a test body actually executed".
_EXECUTED_KEYS: tuple[str, ...] = ("passed", "failed", "errors", "xfailed", "xpassed")


@dataclass(frozen=True)
class SuiteOutcome:
    """What a pytest process actually did. Frozen; every field measured.

    ``counts`` holds the outcome words pytest printed (``passed``,
    ``failed``, ``errors``, ``skipped``, ``xfailed``, ``xpassed``), each
    paired with its integer count. Absent words are absent pairs, not
    zeros, so "pytest printed no summary at all" stays distinguishable
    from "pytest printed zero failures". It is a tuple of pairs rather
    than a dict so a caller cannot mutate a measurement -- the same
    discipline ``BounceClassification`` applies to its set fields.
    """

    returncode: int
    counts: tuple[tuple[str, int], ...]
    collected: int
    summary_line: str
    output_tail: str

    def count(self, key: str) -> int:
        """Return the count for *key*, or 0 when pytest did not print it."""
        for word, value in self.counts:
            if word == key:
                return value
        return 0

    @property
    def executed(self) -> int:
        """Number of test bodies that ran (passed + failed + errored + xfail)."""
        return sum(self.count(k) for k in _EXECUTED_KEYS)

    @property
    def green(self) -> bool:
        """True iff pytest exited clean *and* something was actually run.

        Both halves are load-bearing. Exit 0 alone is satisfied by a run
        that deselected everything; ``executed > 0`` alone is satisfied by
        a run with failures.
        """
        return (
            self.returncode == EXIT_OK
            and self.count("failed") == 0
            and self.count("errors") == 0
            and self.executed > 0
        )

    @property
    def red(self) -> bool:
        """True iff tests ran and at least one of them failed or errored.

        Deliberately *not* ``not green``: a usage error, an import-time
        crash, or an empty collection are all non-green without being a
        demonstrated red phase.
        """
        return (
            self.returncode == EXIT_TESTS_FAILED
            and (self.count("failed") > 0 or self.count("errors") > 0)
            and self.executed > 0
        )

    @property
    def collected_nothing(self) -> bool:
        """True iff pytest reported that it found no tests to run."""
        return self.returncode == EXIT_NO_TESTS_COLLECTED or (
            self.collected == 0 and self.executed == 0
        )

    def describe(self) -> str:
        """One-line human summary naming the exit code and the counts."""
        if self.summary_line:
            return f"pytest exit {self.returncode}: {self.summary_line}"
        return f"pytest exit {self.returncode}: no summary line in output"


def parse_pytest_run(returncode: int, output: str) -> SuiteOutcome:
    """Parse a finished pytest invocation into a :class:`SuiteOutcome`.

    Args:
        returncode: The process exit status.
        output: Captured stdout and stderr, concatenated.

    The parser reads the *last* summary banner, because a run that prints
    a short-test-summary section prints several banner lines and only the
    final one carries the totals.
    """
    summaries = _SUMMARY_RE.findall(output)
    summary_line = summaries[-1].strip("= ").strip() if summaries else ""

    parsed: dict[str, int] = {}
    for raw_count, raw_word in _COUNT_RE.findall(summary_line):
        word = raw_word.lower()
        key = "errors" if word.startswith("error") else word
        parsed[key] = int(raw_count)
    counts = tuple(sorted(parsed.items()))

    collected_match = _COLLECTED_RE.search(output)
    collected = int(collected_match.group(1)) if collected_match else 0

    return SuiteOutcome(
        returncode=returncode,
        counts=counts,
        collected=collected,
        summary_line=summary_line,
        output_tail=output[-_TAIL_CHARS:],
    )
