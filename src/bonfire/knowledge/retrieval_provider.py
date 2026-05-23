# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tier 1 retrieval provider — async ripgrep-style lookup over a VaultBackend.

Implements the RetrievalProvider Protocol (bonfire.protocols) by delegating to
a VaultBackend's async query. Returns ContextAtom envelopes so the consumer
is tier-agnostic — Tier 2 (Pantheon) implementations return the same shape
with graph-rank scores instead of uniform 1.0.

Seed-keys are accepted but ignored at this tier (the graph notion is Tier 2 /
Pantheon territory). Token budget is similarly Tier 2 — Tier 1 honors a
fixed per-call limit instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.protocols import ContextAtom

if TYPE_CHECKING:
    from bonfire.protocols import VaultBackend


class RipgrepRetrievalProvider:
    """Tier 1 default — async wrapper over VaultBackend.query()."""

    def __init__(self, *, backend: VaultBackend, default_limit: int = 5) -> None:
        self._backend = backend
        self._default_limit = default_limit

    async def retrieve(
        self,
        *,
        query: str,
        seed_keys: list[str] | None = None,
        token_budget: int = 4000,
    ) -> list[ContextAtom]:
        # seed_keys / token_budget intentionally unused at Tier 1; the Protocol
        # signature is shared with Tier 2 which honors both.
        _ = seed_keys, token_budget
        entries = await self._backend.query(query, limit=self._default_limit)
        return [
            ContextAtom(
                key=entry.entry_id,
                body=entry.content,
                source_path=entry.source_path,
                score=1.0,
            )
            for entry in entries
        ]
