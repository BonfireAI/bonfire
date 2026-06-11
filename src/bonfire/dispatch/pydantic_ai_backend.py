# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""PydanticAIBackend — AgentBackend wrapper around ``pydantic_ai.Agent``.

Wraps ``pydantic_ai.Agent.run()`` behind Bonfire's ``AgentBackend``
protocol so enrichment LLM calls flow through the same cost-metering and
event-bus surface as every other dispatch.

Cold-start: ``pydantic_ai`` is lazy-imported INSIDE ``execute()``, NOT
at module top level. The module-level ``Agent`` sentinel (``None``) is
populated on first call so ``unittest.mock.patch`` can intercept the
name at ``bonfire.dispatch.pydantic_ai_backend.Agent``. The module
loads cleanly whether or not ``pydantic_ai`` is installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bonfire.dispatch._cost import safe_cost_from_usage

if TYPE_CHECKING:
    from bonfire.models.envelope import Envelope
    from bonfire.protocols import DispatchOptions

# Lazy-loaded on first execute() call. Patchable via
# ``patch("bonfire.dispatch.pydantic_ai_backend.Agent")``.
Agent: Any = None


class PydanticAIBackend:
    """``AgentBackend`` implementation backed by ``pydantic_ai.Agent.run()``.

    Parameters
    ----------
    model
        The model identifier string (e.g. ``"claude-sonnet-4-20250514"``).
    """

    def __init__(self, model: str = "") -> None:
        self._model = model

    async def execute(
        self,
        envelope: Envelope,
        *,
        options: DispatchOptions,
    ) -> Envelope:
        """Run a single agent turn via pydantic_ai and return enriched envelope.

        Lazy-imports ``pydantic_ai.Agent`` on first call and caches at
        module level so subsequent calls (and ``unittest.mock.patch``)
        see the same name.
        """
        global Agent
        if Agent is None:
            from pydantic_ai import Agent as _Agent

            Agent = _Agent

        model = options.model or self._model or "test-model"
        agent = Agent(model)
        result = await agent.run(envelope.task)

        output_text = str(result.output) if result.output else ""

        # Cost metering: extract token usage if available (shared helper
        # preserves the swallow-and-default-to-0.0 discipline verbatim).
        cost_usd = safe_cost_from_usage(result)

        return envelope.with_result(output_text, cost_usd=cost_usd)

    async def health_check(self) -> bool:
        """Return ``True`` — the backend is always nominally ready."""
        return True
