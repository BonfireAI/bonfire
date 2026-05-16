# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""ContextBuilder -- assembles context strings for pipeline stages.

Accumulates prior stage results, task descriptions, bounce context, and
budget info into a single context string. Respects a ``max_context_tokens``
limit, truncating low-priority sections first while preserving task and
bounce context.

ContextBuilder does not currently apply an absolute-path check on ``task`` or
``bounce_context``; both strings are trusted as supplied by the caller. A
follow-up may layer an opt-in guard at this seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec


class ContextBuilder:
    """Builds context strings for pipeline stages with priority-based truncation."""

    def __init__(self, *, max_context_tokens: int = 8000) -> None:
        self._max_tokens = max_context_tokens

    async def build(
        self,
        *,
        stage: StageSpec,
        prior_results: dict[str, Envelope],
        budget_remaining_usd: float = 0.0,
        task: str = "",
        bounce_context: str = "",
        known_issues: str = "",
    ) -> str:
        """Build a context string from available inputs.

        Priority (higher = survives truncation):
            100 -- task
             90 -- bounce_context
             80 -- known_issues
             70 -- prior results (each)
             50 -- budget info
        """
        # Collect (priority, text) sections
        sections: list[tuple[int, str]] = []

        if task:
            sections.append((100, f"## Task\n\n{task}"))

        if bounce_context:
            sections.append((90, f"## Bounce Context\n\n{bounce_context}"))

        if known_issues:
            sections.append((80, known_issues))

        for name, envelope in prior_results.items():
            sections.append((70, f"## Output from {name}\n\n{envelope.result}"))

        if budget_remaining_usd > 0:
            sections.append((50, f"## Budget Remaining\n\n${budget_remaining_usd:.2f} USD"))

        # Sort by priority descending for assembly
        sections.sort(key=lambda s: s[0], reverse=True)

        # Join all sections
        full_text = "\n\n".join(text for _, text in sections)

        # Estimate tokens: ~4 chars per token
        max_chars = self._max_tokens * 4

        if len(full_text) <= max_chars:
            return full_text

        # Truncation: drop lowest-priority sections first
        # Keep adding from highest priority until we'd exceed the limit
        kept: list[str] = []
        used = 0
        for _priority, text in sections:
            # Account for separator
            separator_cost = 2 if kept else 0  # "\n\n"
            needed = len(text) + separator_cost
            if used + needed <= max_chars:
                kept.append(text)
                used += needed
            elif _priority >= 90:
                # Task and bounce context MUST survive -- force-include
                kept.append(text)
                used += needed

        return "\n\n".join(kept)
