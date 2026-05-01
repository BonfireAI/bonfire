# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knowledge persistence — storage-agnostic interface.

Factory function ``get_vault_backend()`` returns the configured backend.
Lazy imports keep LanceDB and Ollama out of the default import path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bonfire.protocols import VaultBackend

__all__ = ["get_vault_backend"]


def get_vault_backend(
    *,
    enabled: bool = True,
    backend: str = "memory",
    vault_path: str = ".bonfire/vault",
    embedding_provider: str = "mock",
    embedding_model: str = "nomic-embed-text",
    embedding_dim: int = 768,
    **kwargs: Any,
) -> VaultBackend:
    """Return the configured vault backend.

    - ``enabled=False`` → :class:`InMemoryVaultBackend`
    - ``backend="memory"`` → :class:`InMemoryVaultBackend`
    - ``backend="lancedb"`` → :class:`LanceDBBackend`
    - anything else → :class:`InMemoryVaultBackend` (safe fallback)
    """
    if not enabled or backend == "memory":
        from bonfire.knowledge.memory import InMemoryVaultBackend

        return InMemoryVaultBackend()

    if backend == "lancedb":
        from bonfire.knowledge.backend import LanceDBBackend
        from bonfire.knowledge.embeddings import get_embedder

        embedder = get_embedder(
            provider=embedding_provider,
            model=embedding_model,
            dim=embedding_dim,
        )
        return LanceDBBackend(vault_path=vault_path, embedder=embedder)

    from bonfire.knowledge.memory import InMemoryVaultBackend

    return InMemoryVaultBackend()
