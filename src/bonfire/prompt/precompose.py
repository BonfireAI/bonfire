# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pre-bake retrieval into a reach_context-shaped dict.

Caller pattern (when a dispatch entry exists that wires this in):

    provider = discover_retrieval_provider()
    reach_context.update(
        await prebake_retrieval(task_description, provider=provider)
    )
    # then pass reach_context into PromptCompiler.compose_agent_prompt(...)

This module is import-cheap (no embedding model, no graph open) so dispatch
hot-paths can call it per-dispatch without warm-up cost.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bonfire.protocols import RetrievalProvider
from bonfire.timeouts import DEFAULT_RETRIEVE_TIMEOUT_S, retrieve_timeout

_log = logging.getLogger(__name__)


# Re-exported from the shared resolver so this call site keeps its stable
# public names while the resolution logic lives in ONE place.
_retrieve_timeout = retrieve_timeout

__all__ = ["DEFAULT_RETRIEVE_TIMEOUT_S", "prebake_retrieval"]


async def prebake_retrieval(
    task: str,
    *,
    provider: RetrievalProvider | None,
    token_budget: int = 4000,
) -> dict[str, Any]:
    """Run the active retrieval provider and serialize results for reach_context.

    Returns a dict shaped for direct ``reach_context.update(...)`` folding.
    On any exception from ``provider.retrieve()`` the failure is logged at
    WARNING and an empty dict is returned — retrieval failure NEVER breaks
    dispatch.

    Parameters
    ----------
    task:
        The task description (used as the query against the provider).
    provider:
        The active RetrievalProvider, or ``None`` for no-op (returns ``{}``).
    token_budget:
        Forwarded to ``provider.retrieve(token_budget=...)``.
    """

    if provider is None:
        return {}

    timeout = _retrieve_timeout()
    try:
        atoms = await asyncio.wait_for(
            provider.retrieve(query=task, token_budget=token_budget),
            timeout=timeout,
        )
    except TimeoutError:
        _log.warning(
            "prebake_retrieval: provider timed out after %ss; returning empty",
            timeout,
        )
        return {}
    except Exception as exc:  # noqa: BLE001 — containment by design
        _log.warning(
            "prebake_retrieval: provider raised %s; returning empty",
            type(exc).__name__,
        )
        return {}

    return {"retrieved_atoms": [a.model_dump() for a in atoms]}
