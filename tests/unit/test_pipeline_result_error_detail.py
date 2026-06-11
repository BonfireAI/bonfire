# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin PipelineResult.error_detail (engine/pipeline.py).

``error_detail: ErrorDetail | None`` is the structured, traceback-bearing
failure on PipelineResult (Elegance Law); ``error: str`` stays for
back-compat. The never-raise ``run()`` shell populates ``error_detail``
(with a live traceback) on its catch-all failure path.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bonfire.engine.pipeline import PipelineEngine, PipelineResult
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import ErrorDetail


def test_default_error_detail_is_none() -> None:
    r = PipelineResult(success=True, session_id="s")
    assert r.error_detail is None


def test_back_compat_error_str_preserved() -> None:
    r = PipelineResult(success=False, session_id="s", error="boom")
    assert r.error == "boom"
    assert r.error_detail is None


def test_error_detail_carries_structured_failure() -> None:
    detail = ErrorDetail(error_type="ValueError", message="x")
    r = PipelineResult(success=False, session_id="s", error="x", error_detail=detail)
    assert r.error_detail is detail
    assert r.error_detail.error_type == "ValueError"


class _BoomPlan:
    """Minimal stand-in: any attribute access blows up the inner shell."""

    name = "boom"

    @property
    def stages(self) -> Any:
        raise RuntimeError("inner exploded")


@pytest.mark.asyncio
async def test_run_failure_path_populates_error_detail_with_traceback() -> None:
    # Drive run()'s catch-all by making _run_inner raise. We patch
    # _run_inner to raise so the public never-raise shell path is exercised.
    # A real engine (with a bus) is built rather than a bare ``__new__`` so the
    # outer-exception branch's ``__outer__`` PipelineFailed emit -- the
    # bus-vs-result parity guarantee -- also fires through the live ``_emit``.
    engine = PipelineEngine(
        backend=object(),  # type: ignore[arg-type]
        bus=EventBus(),
        config=PipelineConfig(),
    )

    async def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("inner exploded")

    engine._run_inner = _boom  # type: ignore[attr-defined,method-assign]

    result = await engine.run(object(), session_id="sid")  # type: ignore[arg-type]

    assert result.success is False
    # Back-compat str still populated.
    assert "inner exploded" in result.error
    # Structured detail populated with a LIVE traceback.
    assert result.error_detail is not None
    assert result.error_detail.error_type == "RuntimeError"
    assert result.error_detail.message == "inner exploded"
    assert result.error_detail.traceback is not None
    assert "RuntimeError" in result.error_detail.traceback
    assert "NoneType: None" not in result.error_detail.traceback


@pytest.mark.asyncio
async def test_run_reraises_cancelled_error() -> None:
    engine = PipelineEngine.__new__(PipelineEngine)

    async def _cancel(*_a: Any, **_k: Any) -> Any:
        raise asyncio.CancelledError

    engine._run_inner = _cancel  # type: ignore[attr-defined,method-assign]

    with pytest.raises(asyncio.CancelledError):
        await engine.run(object(), session_id="sid")  # type: ignore[arg-type]
