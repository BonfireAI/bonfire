"""RED tests — BON-341 W5.2 — `bonfire.knowledge.__init__.get_vault_backend`.

Sage D3.1-D3.3 + D8.2 locks:

- Factory name STAYS ``get_vault_backend`` (D3.3 — NOT renamed to get_knowledge_backend).
- Default ``backend="memory"`` (D3.1 — flipped from v1's "lancedb").
- Default ``embedding_provider="mock"`` (D3.2 — flipped from v1's "ollama").
- Signature: ``(*, enabled=True, backend="memory", vault_path=".bonfire/vault",
  embedding_provider="mock", embedding_model="nomic-embed-text", embedding_dim=768, **kwargs)``
- Return: instance satisfying ``VaultBackend`` @runtime_checkable protocol.
- Branches:
  - enabled=False OR backend="memory" -> InMemoryVaultBackend.
  - backend="lancedb" -> LanceDBBackend (may raise ImportError).
  - anything else -> InMemoryVaultBackend fallback.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import inspect

import pytest

from bonfire.knowledge import get_vault_backend
from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultBackend

# ---------------------------------------------------------------------------
# Signature / defaults
# ---------------------------------------------------------------------------


class TestFactoryDefaults:
    def test_default_backend_is_memory(self) -> None:
        """Sage D3.1: default backend == 'memory' (flipped from v1's 'lancedb')."""
        sig = inspect.signature(get_vault_backend)
        assert sig.parameters["backend"].default == "memory"

    def test_default_embedding_provider_is_mock(self) -> None:
        """Sage D3.2: default embedding_provider == 'mock'."""
        sig = inspect.signature(get_vault_backend)
        assert sig.parameters["embedding_provider"].default == "mock"

    # knight-a(innovative): all-keyword-only signature assertion.
    def test_factory_all_params_are_keyword_only(self) -> None:
        """All parameters on get_vault_backend are keyword-only."""
        sig = inspect.signature(get_vault_backend)
        for name, p in sig.parameters.items():
            if name == "kwargs":
                continue  # **kwargs handled separately
            assert p.kind in (p.KEYWORD_ONLY, p.VAR_KEYWORD), (
                f"Parameter {name!r} must be keyword-only."
            )


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------


class TestFactoryBranches:
    def test_enabled_false_returns_memory_backend(self) -> None:
        """enabled=False -> InMemoryVaultBackend regardless of other args."""
        backend = get_vault_backend(enabled=False, backend="lancedb")
        assert isinstance(backend, InMemoryVaultBackend)

    def test_backend_memory_returns_memory_backend(self) -> None:
        backend = get_vault_backend(backend="memory")
        assert isinstance(backend, InMemoryVaultBackend)

    def test_backend_unknown_returns_memory_backend_fallback(self) -> None:
        """Unknown backend string -> InMemoryVaultBackend (safe fallback)."""
        backend = get_vault_backend(backend="mars-orbit-kv-store")
        assert isinstance(backend, InMemoryVaultBackend)

    def test_default_call_returns_memory_backend(self) -> None:
        """No args -> InMemoryVaultBackend (Sage D3.1 default)."""
        assert isinstance(get_vault_backend(), InMemoryVaultBackend)

    def test_backend_lancedb_attempts_lancedb_import(self) -> None:
        """backend='lancedb' either returns LanceDBBackend or raises ImportError.

        On a fresh install (no ``bonfire[knowledge]`` extra), the lancedb
        branch raises ImportError. On an installed extras-env, it returns
        a LanceDBBackend instance. Either is acceptable per Sage D8.2 +
        pyproject.toml:36.
        """
        try:
            backend = get_vault_backend(backend="lancedb")
        except ImportError:
            return  # expected on no-extra install
        # If no ImportError: must satisfy VaultBackend protocol.
        assert isinstance(backend, VaultBackend)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestFactoryReturnType:
    def test_factory_returned_object_satisfies_vault_backend_protocol(self) -> None:
        """Default factory call returns something satisfying the protocol."""
        backend = get_vault_backend()
        assert isinstance(backend, VaultBackend)

    # knight-a(innovative): protocol conformance across multiple branch invocations.
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"enabled": False},
            {"backend": "memory"},
            {"backend": "unknown-fallback"},
            {},
        ],
    )
    def test_every_non_lancedb_branch_returns_valid_backend(self, kwargs: dict) -> None:
        backend = get_vault_backend(**kwargs)
        assert isinstance(backend, VaultBackend)


# ---------------------------------------------------------------------------
# Factory name preservation (D3.3 guard)
# ---------------------------------------------------------------------------


class TestFactoryNamePreservation:
    """D3.3: ``get_vault_backend`` name MUST be preserved (not renamed to
    ``get_knowledge_backend``)."""

    def test_get_vault_backend_is_importable_by_name(self) -> None:
        from bonfire.knowledge import get_vault_backend as _gvb

        assert callable(_gvb)

    def test_get_knowledge_backend_does_not_exist(self) -> None:
        """Sage D3.3 locks the name — a renamed variant MUST NOT leak."""
        import bonfire.knowledge as kmod

        assert not hasattr(kmod, "get_knowledge_backend")
