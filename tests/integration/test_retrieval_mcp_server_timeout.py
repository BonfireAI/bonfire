# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract tests: retrieve_context must bound a hung provider with a timeout.

These tests pin the timeout contract for ``bonfire.mcp.retrieval_server``. They
were authored against an implementation that has NO timeout — a hung provider
blocks the stdio loop forever — so they are expected to FAIL until the timeout
wrapper lands.

The contract pinned here (implementer must satisfy EXACTLY this surface):

1. Module constant ``DEFAULT_RETRIEVE_TIMEOUT_S: float = 30.0``.
2. Helper ``_retrieve_timeout() -> float`` returning
   ``float(os.getenv("BONFIRE_RETRIEVE_TIMEOUT_S", DEFAULT_RETRIEVE_TIMEOUT_S))``
   — env override wins; absent env falls back to the default constant.
3. ``handle_retrieve_context`` wraps the provider call in
   ``asyncio.wait_for(active.retrieve(...), timeout=_retrieve_timeout())``. On
   timeout it must surface an error string (the repo convention is a plain
   ``"retrieve_context: ..."`` text response, NOT an MCP ``isError`` envelope)
   whose text contains the phrase ``timed out``.
4. A fast provider call returns unchanged.

NOTE ON CONTRACT DRIFT (read before implementing):
The originating ticket described a different surface than the one that exists in
the tree today — ``_handle_retrieve_context(arguments)``, a module-level
``_PROVIDER``/``_get_provider`` hook, ``DEFAULT_RETRIEVE_TIMEOUT_S``, and an
existing ``tests/mcp/test_retrieval_server.py`` with 7 tests. None of that
matches reality: the real entry point is the keyword-only
``handle_retrieve_context(*, query, token_budget=4000, provider=None)``, the
provider is discovered via ``bonfire._discovery.discover_retrieval_provider``,
and the generic-except path returns
``f"retrieve_context: provider raised {type(exc).__name__}: {exc}"``. These
tests are written against the REAL surface. The two env-knob tests assume the
implementer adds the constant + helper named above; if the implementer chooses
different names, these tests are the contract and the names must match them.
"""

from __future__ import annotations

import asyncio

import pytest

from bonfire.mcp import retrieval_server as mod
from bonfire.protocols import ContextAtom


class _SlowProvider:
    """A RetrievalProvider whose retrieve() hangs until cancelled.

    Mirrors the real provider contract: ``retrieve`` is awaitable and takes
    keyword ``query`` + ``token_budget``. It records cancellation so a test can
    assert the hung coroutine was actually abandoned (not merely ignored).
    """

    def __init__(self) -> None:
        self.cancelled = False

    async def retrieve(self, *, query: str, seed_keys=None, token_budget: int = 4000):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return []


class _FastProvider:
    """A normal provider that returns immediately with the seeded atoms."""

    def __init__(self, atoms: list[ContextAtom]) -> None:
        self._atoms = atoms

    async def retrieve(self, *, query: str, seed_keys=None, token_budget: int = 4000):
        return self._atoms


def test_retrieve_timeout_default_is_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the env var unset, the helper returns the module default of 30.0s."""
    monkeypatch.delenv("BONFIRE_RETRIEVE_TIMEOUT_S", raising=False)
    assert mod.DEFAULT_RETRIEVE_TIMEOUT_S == 30.0
    assert mod._retrieve_timeout() == mod.DEFAULT_RETRIEVE_TIMEOUT_S


def test_retrieve_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env var overrides the default and is coerced to float."""
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "5")
    value = mod._retrieve_timeout()
    assert value == 5.0
    assert isinstance(value, float)


async def test_slow_provider_times_out_returns_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung provider is abandoned and an error string mentioning the timeout
    is returned — fast, proving the loop was not blocked for 10s."""
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "0.05")
    slow = _SlowProvider()

    text = await asyncio.wait_for(
        mod.handle_retrieve_context(query="hi", provider=slow),
        timeout=2.0,  # outer guard: if the impl never times out, fail fast here
    )

    assert isinstance(text, str)
    assert "timed out" in text


async def test_fast_provider_unaffected_by_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that returns promptly is not perturbed by the timeout wrapper."""
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "5")

    fast = _FastProvider([ContextAtom(key="k1", body="ok", source_path="src/x.py", score=0.5)])
    text = await mod.handle_retrieve_context(query="hi", provider=fast)

    assert isinstance(text, str)
    assert "timed out" not in text
    assert "1 atoms" in text
    assert "k1" in text
    assert "ok" in text


async def test_custom_timeout_honored_cancels_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env timeout actually bounds the wait and the slow coroutine is
    cancelled (abandonment), not merely left running."""
    monkeypatch.setenv("BONFIRE_RETRIEVE_TIMEOUT_S", "0.01")
    slow = _SlowProvider()

    text = await asyncio.wait_for(
        mod.handle_retrieve_context(query="hi", provider=slow),
        timeout=2.0,
    )

    assert isinstance(text, str)
    assert "timed out" in text
    # Let the cancellation propagate to the slow coroutine before asserting.
    await asyncio.sleep(0)
    assert slow.cancelled is True
