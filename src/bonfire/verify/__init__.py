# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""bonfire.verify -- deterministic verification primitives.

The ``verify`` package owns pure-function classifiers that decide pipeline
routing without I/O. Today: the warrior-failure classifier. Tomorrow: any
other deterministic ``(envelope, decision-log) -> verdict`` lens.

The classifier is split intentionally from the handler shell that drives
correction cycles -- pure functions live here, I/O orchestration lives in
``bonfire.handlers``. This separation lets the verdict logic be unit-tested
without subprocess mocks or filesystem fixtures.

Public surface:

- :class:`ClassifierVerdict`  -- StrEnum of the three deterministic verdicts.
- :class:`BounceClassification` -- frozen dataclass, classifier output.
- :class:`DeferRecord`         -- frozen dataclass, single defer entry.
- :class:`ParsedDecisionLog`   -- frozen dataclass, decision-log parser output.
- :class:`FailingTest`         -- frozen dataclass, single warrior failure.
- :func:`classify_warrior_failure` -- the pure-function classifier.
- :func:`parse_sage_decision_log`  -- the pure-function decision-log parser.
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
