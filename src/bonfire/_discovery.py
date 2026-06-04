# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Discovery seam for the active RetrievalProvider.

Optional-import probes for the Tier 2 (Pantheon) implementation. If
``bonfire.arachne.provider:ArachneRetrievalProvider`` is importable, returns
an instance. Otherwise falls back to the Tier 1 RipgrepRetrievalProvider.

bonfire-public NEVER imports bonfire/arachne directly — the optional-import
is gated behind a try/except so this module is safe to ship on PyPI with no
Pantheon dependency.

The result is ``@functools.lru_cache(maxsize=1)``-cached so the import
lookup runs at most once per process.
"""

from __future__ import annotations

import functools

from bonfire.protocols import RetrievalProvider


@functools.lru_cache(maxsize=1)
def discover_retrieval_provider() -> RetrievalProvider:
    """Return the active RetrievalProvider for this process.

    Tier 2 (Pantheon) takes priority when its package is importable;
    Tier 1 (Ripgrep) is the fallback.
    """
    try:
        from bonfire.arachne.provider import ArachneRetrievalProvider
    except ImportError:
        from bonfire.knowledge import get_vault_backend
        from bonfire.knowledge.retrieval_provider import RipgrepRetrievalProvider

        backend = get_vault_backend()
        return RipgrepRetrievalProvider(backend=backend)
    else:
        return ArachneRetrievalProvider()
