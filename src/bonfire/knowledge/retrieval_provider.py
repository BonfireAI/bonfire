# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tier 1 retrieval provider — ripgrep over a VaultBackend.

Implements the RetrievalProvider Protocol (bonfire.protocols) by delegating to
a VaultBackend's keyword query. Returns ContextAtom envelopes so the consumer
is tier-agnostic. Seed-keys are accepted but ignored at this tier (the graph
notion is Tier 2 / Pantheon).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.protocols import ContextAtom

if TYPE_CHECKING:
    from bonfire.protocols import VaultBackend


class RipgrepRetrievalProvider:
    """Tier 1 default — wraps a VaultBackend's query() call."""

    def __init__(self, *, backend: VaultBackend, default_limit: int = 5) -> None:
        self._backend = backend
        self._default_limit = default_limit

    def retrieve(
        self,
        *,
        query: str,
        seed_keys: list[str] | None = None,
        token_budget: int = 4000,
    ) -> list[ContextAtom]:
        # seed_keys intentionally unused at Tier 1; Protocol signature is shared
        # with Tier 2 which honors it.
        _ = seed_keys, token_budget
        hits = self._backend.query(query, limit=self._default_limit)
        return [
            ContextAtom(
                key=hit.key,
                body=hit.body,
                source_path=hit.source_path,
                score=getattr(hit, "score", 1.0),
            )
            for hit in hits
        ]
