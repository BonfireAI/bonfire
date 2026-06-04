# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin the ``contain_as_error`` containment helper (errors.py).

The helper wraps a never-raise shell body: it reraises
``asyncio.CancelledError`` (cancellation must surface), captures an
``ErrorDetail`` (with a LIVE traceback) for any ordinary ``Exception``,
and exposes the captured detail to the caller. It does NOT swallow the
exception silently -- the caller reads the captured detail and builds its
own failure envelope, preserving verdict-before-side-effect ordering.
"""

from __future__ import annotations

import asyncio

import pytest

from bonfire.errors import contain_as_error
from bonfire.models.envelope import ErrorDetail


def test_no_exception_leaves_detail_none() -> None:
    with contain_as_error("stage_x") as box:
        _ = 1 + 1
    assert box.error is None


def test_ordinary_exception_captured_as_error_detail() -> None:
    with contain_as_error("stage_x") as box:
        raise ValueError("boom")
    assert isinstance(box.error, ErrorDetail)
    assert box.error.error_type == "ValueError"
    assert box.error.message == "boom"
    assert box.error.stage_name == "stage_x"


def test_traceback_is_live_not_nonetype_sentinel() -> None:
    with contain_as_error("stage_x") as box:
        raise RuntimeError("with traceback")
    assert box.error is not None
    # Live traceback (captured inside the except) names the raising frame,
    # never the meaningless "NoneType: None" sentinel from format_exc()
    # called outside an active except.
    assert box.error.traceback is not None
    assert "RuntimeError" in box.error.traceback
    assert "NoneType: None" not in box.error.traceback


def test_cancelled_error_reraises_not_captured() -> None:
    with pytest.raises(asyncio.CancelledError):
        with contain_as_error("stage_x") as box:
            raise asyncio.CancelledError
    # Cancellation surfaced; it was NOT swallowed into the detail box.
    assert box.error is None


def test_stage_name_optional() -> None:
    with contain_as_error() as box:
        raise KeyError("k")
    assert box.error is not None
    assert box.error.stage_name is None
