"""Prompt compilation and truncation.

Public API:
- IdentityBlock — validated identity frontmatter (formerly ``AxiomMeta``)
- PromptBlock — immutable prompt content unit
- PromptTemplate — parsed template with YAML frontmatter
- PromptCompiler — load, render, truncate, order, join
- estimate_tokens, effective_budget, truncate_blocks, order_by_position
"""

from bonfire.prompt.compiler import PromptBlock, PromptCompiler, PromptTemplate
from bonfire.prompt.identity_block import IdentityBlock
from bonfire.prompt.truncation import (
    effective_budget,
    estimate_tokens,
    order_by_position,
    truncate_blocks,
)

__all__ = [
    "IdentityBlock",
    "PromptBlock",
    "PromptCompiler",
    "PromptTemplate",
    "effective_budget",
    "estimate_tokens",
    "order_by_position",
    "truncate_blocks",
]
