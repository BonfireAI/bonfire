# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Observability contract for ``LanceDBBackend.exists()``.

The ``exists()`` method is a dedup-existence check used by the ingest consumer
(``knowledge/consumer.py`` ``_store``): ``if await self.backend.exists(c_hash):
return``. On a backend failure (malformed content_hash, corrupt table, a LanceDB
error) ``exists()`` intentionally FAILS OPEN — it returns ``False`` so ingestion
keeps working — but a silent ``False`` is indistinguishable from a genuine
"not found", so the caller would proceed to a duplicate store with no trace of WHY.

The Elegance Law requires the failure to SPEAK. Its two sibling methods on the
same class already narrate before degrading: ``query()`` and ``get_by_source()``
both ``logger.warning(...)`` then return their empty result. This test pins the
same contract on ``exists()``: a failing lookup must (1) still return ``False``
(fail-open preserved) and (2) emit a WARNING so the swallowed failure is visible.

``lancedb`` is not a test dependency, so we never connect to a real store: we
pre-set the backend's private ``_table``/``_db`` so ``_ensure_connected()`` is a
no-op, and inject a fake table whose ``.search()`` raises. That exercises the
exact ``except`` arm under test without any LanceDB runtime.
"""

from __future__ import annotations

import logging

import pytest

from bonfire.knowledge.backend import LanceDBBackend


class _FakeEmbedder:
    """Minimal embedder stub — ``exists()`` only reads ``dim`` for the zero-vector."""

    dim = 4


class _ExplodingTable:
    """A table whose existence query blows up, mimicking a corrupt/failed store."""

    def count_rows(self) -> int:
        # Non-empty so ``exists()`` proceeds past its early ``return False`` guard
        # and reaches the protected ``.search(...).where(...).to_list()`` block.
        return 1

    def search(self, _vector: object) -> _ExplodingTable:
        raise RuntimeError("simulated LanceDB search failure")


def _make_backend() -> LanceDBBackend:
    backend = LanceDBBackend(vault_path=":memory:", embedder=_FakeEmbedder())
    # Pre-wire the lazy-connect fields so ``_ensure_connected()`` short-circuits
    # (it returns early when ``_table is not None``) and never imports lancedb.
    backend._table = _ExplodingTable()
    backend._db = object()
    return backend


@pytest.mark.asyncio
async def test_exists_fails_open_to_false_on_backend_error() -> None:
    """A failed existence lookup must preserve the fail-open ``False`` contract."""
    backend = _make_backend()
    result = await backend.exists("deadbeef")
    assert result is False


@pytest.mark.asyncio
async def test_exists_narrates_swallowed_failure_with_a_warning() -> None:
    """A failed existence lookup must emit a WARNING — it must not fail silently.

    Matches the sibling idiom (``query()``/``get_by_source()`` log
    ``logger.warning('Vault ... failed: %s', exc)``); the underlying exception
    message must ride in the log so the WHY is recoverable from the trace.
    """
    backend = _make_backend()
    with caplog_warning() as records:
        result = await backend.exists("deadbeef")

    assert result is False, "fail-open contract must hold"
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert warnings, "exists() must narrate its swallowed failure, not eat it silently"
    joined = " ".join(r.getMessage() for r in warnings)
    assert "simulated LanceDB search failure" in joined, (
        "the originating exception must be carried in the warning"
    )


# ---------------------------------------------------------------------------
# caplog plumbing
# ---------------------------------------------------------------------------


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _CaplogWarning:
    """Captures WARNING+ records from the backend module's logger for one block."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("bonfire.knowledge.backend")
        self._handler = _RecordingHandler()
        self._prev_level = self._logger.level

    def __enter__(self) -> list[logging.LogRecord]:
        self._logger.addHandler(self._handler)
        self._logger.setLevel(logging.WARNING)
        return self._handler.records

    def __exit__(self, *_exc: object) -> None:
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._prev_level)


def caplog_warning() -> _CaplogWarning:
    return _CaplogWarning()
