# SPDX-License-Identifier: Apache-2.0
"""Tests for discover_retrieval_provider() — the Tier 2 optional-import seam."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from bonfire import _discovery
from bonfire.knowledge.retrieval_provider import RipgrepRetrievalProvider


@pytest.fixture(autouse=True)
def _clear_discovery_cache():
    """Each test starts with a cold cache to control the discovery path."""
    _discovery.discover_retrieval_provider.cache_clear()
    yield
    _discovery.discover_retrieval_provider.cache_clear()


def test_discovery_falls_back_to_ripgrep_when_arachne_absent(monkeypatch):
    """No bonfire.arachne.provider module → RipgrepRetrievalProvider."""

    # Ensure the optional Pantheon module is not present.
    monkeypatch.delitem(sys.modules, "bonfire.arachne", raising=False)
    monkeypatch.delitem(sys.modules, "bonfire.arachne.provider", raising=False)

    # Force the import to fail even if the package is installed.
    import builtins

    _real_import = builtins.__import__

    def _fake_import(name, *a, **kw):
        if name == "bonfire.arachne.provider":
            raise ImportError("no Arachne in this test")
        return _real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    provider = _discovery.discover_retrieval_provider()
    assert isinstance(provider, RipgrepRetrievalProvider)


def test_discovery_returns_arachne_when_present(monkeypatch):
    """If bonfire.arachne.provider exposes ArachneRetrievalProvider, use it."""

    class _StubArachneProvider:
        async def retrieve(self, *, query, seed_keys=None, token_budget=4000):
            return []

    fake_module = ModuleType("bonfire.arachne.provider")
    fake_module.ArachneRetrievalProvider = _StubArachneProvider  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "bonfire.arachne", ModuleType("bonfire.arachne"))
    monkeypatch.setitem(sys.modules, "bonfire.arachne.provider", fake_module)

    provider = _discovery.discover_retrieval_provider()
    assert isinstance(provider, _StubArachneProvider)


def test_discovery_lru_caches(monkeypatch):
    """Repeated calls return the same instance without re-running discovery."""
    first = _discovery.discover_retrieval_provider()
    second = _discovery.discover_retrieval_provider()
    assert first is second
