# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin the MERGE_CONFLICT ErrorDetail capture (merge_preflight.py).

Phase 4 stops discarding the ``RuntimeError`` in the
RuntimeError -> MERGE_CONFLICT translation inside
``_classify_preflight_run``. The translated ``PreflightClassification``
now carries an ``error: ErrorDetail | None`` built via
``ErrorDetail.from_exception`` (live traceback), while the *verdict*
itself is unchanged (still MERGE_CONFLICT). ``_PytestResult`` likewise
gains an optional ``error`` field.
"""

from __future__ import annotations

from pathlib import Path

from bonfire.handlers.merge_preflight import (
    PreflightClassification,
    PreflightVerdict,
    _PytestResult,
)
from bonfire.models.envelope import ErrorDetail


def _detail() -> ErrorDetail:
    try:
        raise RuntimeError("git apply --3way failed")
    except RuntimeError as exc:
        return ErrorDetail.from_exception(exc, stage_name="merge_preflight")


# ---------------------------------------------------------------------------
# Additive fields default to None (back-compat)
# ---------------------------------------------------------------------------


def test_preflight_classification_error_defaults_none() -> None:
    pc = PreflightClassification(verdict=PreflightVerdict.GREEN)
    assert pc.error is None


def test_pytest_result_error_defaults_none() -> None:
    pr = _PytestResult(
        returncode=0,
        duration_seconds=0.0,
        stdout_tail="",
        junit_xml_path=Path("/fake/x.xml"),
    )
    assert pr.error is None


# ---------------------------------------------------------------------------
# MERGE_CONFLICT classification carries the captured exception
# ---------------------------------------------------------------------------


def test_merge_conflict_classification_carries_error_detail() -> None:
    detail = _detail()
    pc = PreflightClassification(
        verdict=PreflightVerdict.MERGE_CONFLICT,
        pytest_returncode=-1,
        error=detail,
    )
    # Verdict unchanged.
    assert pc.verdict == PreflightVerdict.MERGE_CONFLICT
    # Exception no longer discarded.
    assert pc.error is not None
    assert pc.error.error_type == "RuntimeError"
    assert "git apply --3way failed" in pc.error.message
    # Live traceback captured inside the except.
    assert pc.error.traceback is not None
    assert "RuntimeError" in pc.error.traceback
    assert "NoneType: None" not in pc.error.traceback
