"""Verification subsystem for Bonfire's correction-bounce pipeline.

This package houses the deterministic, pure-function classifier that decides
whether a Warrior failure is the Sage's fault (under-marked deps), the
Warrior's fault (real bug or unconditional failure), or genuinely ambiguous.

Public surface:

- :class:`ClassifierVerdict` -- 3-verdict StrEnum
  (``SAGE_UNDER_MARKED`` / ``WARRIOR_BUG`` / ``AMBIGUOUS``).
- :class:`BounceClassification` -- frozen dataclass returned by
  :func:`classify_warrior_failure`.
- :class:`FailingTest` -- frozen dataclass describing a single failing
  test for the classifier's input.
- :class:`DeferRecord` -- frozen dataclass for a single Sage-defer entry
  (one ticket id + provenance metadata).
- :class:`ParsedDecisionLog` -- frozen dataclass produced by
  :func:`parse_sage_decision_log` carrying ``deps`` and ``parse_source``.
- :func:`classify_warrior_failure` -- pure function; first-match-wins
  deterministic classifier.
- :func:`parse_sage_decision_log` -- pure function; extracts deferred
  ticket ids from a Sage memo text (front-matter or prose).

The classifier is *pure*: no I/O, no clock, no random. Its caller (the
``SageCorrectionBounceHandler`` stage handler) owns all I/O.
"""

from __future__ import annotations

from bonfire.verify.classifier import (
    BounceClassification,
    ClassifierVerdict,
    DeferRecord,
    FailingTest,
    ParsedDecisionLog,
    classify_warrior_failure,
    parse_sage_decision_log,
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
