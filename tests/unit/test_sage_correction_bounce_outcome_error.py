# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin _CorrectionCycleOutcome.error + cancellation discipline.

Phase 4 adds ``error: ErrorDetail | None`` to ``_CorrectionCycleOutcome``
and populates it via ``ErrorDetail.from_exception`` inside the cycle's
except blocks (dispatch / cherry-pick / re-verify). The failed envelope
built from such an outcome carries that captured ErrorDetail (live
traceback) instead of synthesizing one from bare strings.

Discipline locked here:
  - ``asyncio.CancelledError`` still propagates (never swallowed).
  - verdict-before-side-effect ordering: a raised dispatch exception
    yields a FAILED envelope carrying the structured error.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bonfire.handlers.sage_correction_bounce import (
    SageCorrectionBounceHandler,
    _CorrectionCycleOutcome,
)
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.plan import StageSpec


def _stage() -> StageSpec:
    return StageSpec(
        name="sage_correction_bounce",
        agent_name="sage-correction",
        role="synthesizer",
        handler_name="sage_correction_bounce",
    )


def _under_marked_prior() -> dict[str, str]:
    # Drives the SAGE_UNDER_MARKED route -> _run_correction_cycle.
    return {"classifier_verdict": "sage_under_marked", "warrior": "1 failed"}


class _BoomBackend:
    async def execute(self, _envelope: Any, *, options: Any) -> Any:
        raise RuntimeError("backend exploded")


class _CancelBackend:
    async def execute(self, _envelope: Any, *, options: Any) -> Any:
        raise asyncio.CancelledError


# ---------------------------------------------------------------------------
# Additive field default
# ---------------------------------------------------------------------------


def test_outcome_error_defaults_none() -> None:
    outcome = _CorrectionCycleOutcome(status=TaskStatus.COMPLETED)
    assert outcome.error is None


# ---------------------------------------------------------------------------
# Dispatch exception -> FAILED envelope carrying structured ErrorDetail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_exception_populates_error_detail() -> None:
    handler = SageCorrectionBounceHandler(backend=_BoomBackend())
    envelope = Envelope(task="t")

    result = await handler.handle(_stage(), envelope, _under_marked_prior())

    assert result.status == TaskStatus.FAILED
    assert isinstance(result.error, ErrorDetail)
    assert result.error.error_type == "RuntimeError"
    assert "backend exploded" in result.error.message
    # Live traceback captured inside the cycle's except block.
    assert result.error.traceback is not None
    assert "RuntimeError" in result.error.traceback
    assert "NoneType: None" not in result.error.traceback
    assert result.error.stage_name == "sage_correction_bounce"


# ---------------------------------------------------------------------------
# CancelledError must propagate, NOT be swallowed into a FAILED envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_error_propagates_not_swallowed() -> None:
    handler = SageCorrectionBounceHandler(backend=_CancelBackend())
    envelope = Envelope(task="t")

    with pytest.raises(asyncio.CancelledError):
        await handler.handle(_stage(), envelope, _under_marked_prior())
