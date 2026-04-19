"""Prompt block truncation and positional ordering.

Provides token estimation, budget calculation, priority-based block
truncation, and U-shaped attention ordering for optimal LLM prompt
construction.

The U-shape algorithm exploits the well-documented primacy/recency bias
in transformer attention: models attend most to the beginning and end of
context, with a "lost in the middle" valley. By placing the highest-priority
block first and second-highest last, we maximize attention on what matters.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.prompt.compiler import PromptBlock

__all__ = [
    "effective_budget",
    "estimate_tokens",
    "order_by_position",
    "truncate_blocks",
]


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using a simple chars/4 heuristic.

    Args:
        text: The input string to estimate tokens for.

    Returns:
        Estimated token count. Zero for empty strings, minimum 1 for
        any non-empty string (even if fewer than 4 characters).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def effective_budget(max_tokens: int, safety_margin: float = 0.15) -> int:
    """Calculate the usable token budget after reserving a safety margin.

    The safety margin prevents prompt overflow when token estimation is
    imprecise — a 15% default buffer absorbs most estimation errors.

    Args:
        max_tokens: The raw maximum token budget.
        safety_margin: Fraction to reserve (0.0–1.0). Defaults to 0.15.

    Returns:
        Floor of ``max_tokens * (1 - safety_margin)``, as an integer.
    """
    return math.floor(max_tokens * (1.0 - safety_margin))


def truncate_blocks(
    blocks: list[PromptBlock],
    budget: int,
) -> list[PromptBlock]:
    """Drop lowest-priority blocks until total tokens fit within budget.

    Algorithm:
    1. Sort blocks by priority ascending (lowest first — drop candidates).
    2. While total estimated tokens exceed budget, drop the front of the
       sorted list (lowest priority). The highest-priority block is NEVER
       dropped entirely.
    3. If the last surviving block still exceeds budget, character-slice
       its content to fit.
    4. Return survivors in their **original insertion order**.

    Args:
        blocks: Prompt blocks to fit within budget.
        budget: Maximum token budget (already safety-adjusted).

    Returns:
        A new list of PromptBlock instances that fit within budget,
        preserving original order. May contain a content-sliced version
        of the highest-priority block if it alone exceeds budget.
    """
    if not blocks:
        return []

    # Track original indices for order preservation
    indexed = list(enumerate(blocks))

    # Sort by priority ascending — lowest priority first (drop candidates)
    by_priority = sorted(indexed, key=lambda pair: pair[1].priority)

    # Survivor set — starts as all blocks
    survivors = list(by_priority)

    def _total_tokens(pairs: list[tuple[int, PromptBlock]]) -> int:
        return sum(estimate_tokens(b.content) for _, b in pairs)

    # Drop lowest-priority blocks until we fit (but never drop the last one)
    while len(survivors) > 1 and _total_tokens(survivors) > budget:
        survivors.pop(0)  # Remove lowest priority survivor

    # If the single (or remaining) survivor(s) still exceed budget,
    # character-slice the highest-priority block
    if _total_tokens(survivors) > budget:
        # Find the highest-priority survivor and slice it
        max_idx = max(range(len(survivors)), key=lambda i: survivors[i][1].priority)
        orig_idx, block = survivors[max_idx]

        # Calculate how many characters we can keep
        # Other survivors consume some budget
        other_tokens = sum(
            estimate_tokens(b.content) for i, (_, b) in enumerate(survivors) if i != max_idx
        )
        remaining_budget = max(1, budget - other_tokens)
        max_chars = remaining_budget * 4

        sliced = replace(block, content=block.content[:max_chars])
        survivors[max_idx] = (orig_idx, sliced)

    # Restore original insertion order
    survivors.sort(key=lambda pair: pair[0])

    return [block for _, block in survivors]


def order_by_position(blocks: list[PromptBlock]) -> list[PromptBlock]:
    """Reorder blocks into a U-shape for optimal transformer attention.

    The U-shape exploits primacy/recency bias:
    - **First position**: highest priority (strongest primacy attention)
    - **Last position**: second-highest priority (strongest recency attention)
    - **Middle positions**: remaining blocks, lowest priority in the valley

    This ensures the most important content occupies the positions where
    LLMs pay the most attention, while less critical content sits in the
    attention trough.

    Args:
        blocks: Prompt blocks to reorder. Input list is NOT mutated.

    Returns:
        A new list with blocks arranged in U-shaped priority order.
    """
    if len(blocks) <= 1:
        return list(blocks)

    # Sort by priority descending
    ranked = sorted(blocks, key=lambda b: b.priority, reverse=True)

    if len(ranked) == 2:
        return list(ranked)  # highest first, lowest last

    # U-shape: highest first, then remaining lowest-to-highest, second-highest last
    # ranked[0] = highest, ranked[1] = second-highest, ranked[2:] = rest descending
    first = ranked[0]
    last = ranked[1]
    middle = sorted(ranked[2:], key=lambda b: b.priority)  # ascending in the valley

    return [first] + middle + [last]
