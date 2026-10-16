"""Contract for the SDK message-stream closing helper in ``sdk_backend``.

``_closing_stream`` wraps the message stream returned by the SDK query call.
It must yield the very same stream object and, on exit (normal completion,
early break, or exception), await ``aclose()`` on any stream that has
``aclose()`` (a capability check, not a class check: async generators and
non-generator iterators alike), while passing plain async iterators (no
``aclose``) through untouched.

The helper is imported inside each test so that a missing helper fails each
test individually instead of hiding the denominator behind a collection error.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest


def _helper() -> Callable[[AsyncIterator[Any]], AbstractAsyncContextManager[AsyncIterator[Any]]]:
    from bonfire.dispatch.sdk_backend import _closing_stream

    return _closing_stream


def _recording_gen(cleanup: list[str], items: list[int]) -> AsyncGenerator[int, None]:
    async def gen() -> AsyncGenerator[int, None]:
        try:
            for item in items:
                yield item
        finally:
            cleanup.append("closed")

    return gen()


class _PlainAsyncIterator:
    """Minimal async iterator: ``__aiter__``/``__anext__`` only, no ``aclose``."""

    def __init__(self, items: list[int]) -> None:
        self._items = list(items)

    def __aiter__(self) -> _PlainAsyncIterator:
        return self

    async def __anext__(self) -> int:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class _ClosableAsyncIterator:
    """Async iterator with an awaitable ``aclose`` that is NOT an async generator."""

    def __init__(self, items: list[int]) -> None:
        self._items = list(items)
        self.aclose_calls = 0

    def __aiter__(self) -> _ClosableAsyncIterator:
        return self

    async def __anext__(self) -> int:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)

    async def aclose(self) -> None:
        self.aclose_calls += 1


async def test_closing_stream_yields_identical_object() -> None:
    closing_stream = _helper()
    cleanup: list[str] = []
    source = _recording_gen(cleanup, [1, 2])

    async with closing_stream(source) as stream:
        assert stream is source


async def test_closing_stream_closes_generator_on_early_break() -> None:
    closing_stream = _helper()
    cleanup: list[str] = []
    source = _recording_gen(cleanup, [1, 2, 3])
    seen: list[int] = []

    async with closing_stream(source) as stream:
        async for item in stream:
            seen.append(item)
            break

    # Asserted immediately after the block: cleanup must not rely on GC.
    assert seen == [1]
    assert cleanup == ["closed"]
    assert source.ag_running is False
    assert source.ag_frame is None
    with pytest.raises(StopAsyncIteration):
        await source.__anext__()


async def test_closing_stream_propagates_exception_and_closes_generator() -> None:
    closing_stream = _helper()
    cleanup: list[str] = []
    source = _recording_gen(cleanup, [1, 2, 3])

    with pytest.raises(ValueError, match="boom"):
        async with closing_stream(source) as stream:
            async for _item in stream:
                raise ValueError("boom")

    assert cleanup == ["closed"]
    assert source.ag_frame is None


async def test_closing_stream_full_consumption_cleans_up_exactly_once() -> None:
    closing_stream = _helper()
    cleanup: list[str] = []
    items = [1, 2, 3]
    source = _recording_gen(cleanup, items)
    seen: list[int] = []

    async with closing_stream(source) as stream:
        async for item in stream:
            seen.append(item)

    assert seen == items, f"consumed {len(seen)} of {len(items)} items"
    assert cleanup == ["closed"], f"cleanup ran {len(cleanup)} times, expected 1"
    assert source.ag_frame is None


async def test_closing_stream_passes_plain_async_iterator_through() -> None:
    closing_stream = _helper()
    items = [10, 20, 30]
    source = _PlainAsyncIterator(items)
    assert not hasattr(source, "aclose")
    assert not isinstance(source, AsyncGenerator)
    seen: list[int] = []

    async with closing_stream(source) as stream:
        assert stream is source
        async for item in stream:
            seen.append(item)

    assert seen == items, f"consumed {len(seen)} of {len(items)} items"


async def test_closing_stream_closes_non_generator_with_aclose_on_early_break() -> None:
    closing_stream = _helper()
    items = [1, 2, 3]
    source = _ClosableAsyncIterator(items)
    # Fixture controls: this must stay a non-generator that still has aclose().
    assert not inspect.isasyncgen(source)
    assert not isinstance(source, AsyncGenerator)
    assert inspect.iscoroutinefunction(source.aclose)
    seen: list[int] = []

    async with closing_stream(source) as stream:
        assert stream is source
        async for item in stream:
            seen.append(item)
            break

    # Asserted immediately after the block: cleanup must not rely on GC.
    assert seen == [1], f"consumed {len(seen)} of {len(items)} items, expected 1"
    assert source.aclose_calls == 1, f"aclose ran {source.aclose_calls} times, expected 1"
