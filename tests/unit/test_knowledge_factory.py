"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.get_vault_backend.

Covers the factory defaults (D3.1, D3.2), branch selection, and
``[knowledge]`` extra ImportError handling per Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D3.3, §D8.3.

Note: factory name stays ``get_vault_backend`` per Sage D3.3 — NOT renamed.
"""

from __future__ import annotations

import inspect

from bonfire.knowledge import get_vault_backend
from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultBackend


class TestFactoryDefaults:
    def test_default_backend_is_memory(self):
        sig = inspect.signature(get_vault_backend)
        assert sig.parameters["backend"].default == "memory"

    def test_default_embedding_provider_is_mock(self):
        sig = inspect.signature(get_vault_backend)
        assert sig.parameters["embedding_provider"].default == "mock"


class TestBranchSelection:
    def test_enabled_false_returns_memory_backend(self):
        backend = get_vault_backend(enabled=False)
        assert isinstance(backend, InMemoryVaultBackend)

    def test_backend_memory_returns_memory_backend(self):
        backend = get_vault_backend(backend="memory")
        assert isinstance(backend, InMemoryVaultBackend)

    def test_backend_unknown_returns_memory_backend_fallback(self):
        backend = get_vault_backend(backend="not-a-real-backend")
        assert isinstance(backend, InMemoryVaultBackend)

    def test_backend_lancedb_attempts_lancedb_import(self, monkeypatch):
        # Deny lancedb — factory should either raise ImportError OR fall
        # back to memory backend. Conservative lens: accept either outcome
        # per Sage D8.2 "may raise ImportError if [knowledge] not installed."
        import sys

        monkeypatch.setitem(sys.modules, "lancedb", None)
        try:
            backend = get_vault_backend(backend="lancedb")
        except ImportError:
            return  # acceptable path
        # If it did not raise, it must have fallen back to memory.
        assert isinstance(backend, InMemoryVaultBackend)


class TestProtocolSatisfaction:
    def test_factory_returned_object_satisfies_vault_backend_protocol(self):
        backend = get_vault_backend()
        assert isinstance(backend, VaultBackend)
