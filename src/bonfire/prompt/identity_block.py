# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Identity-block frontmatter validation model.

Pydantic model for validating the cognitive identity frontmatter of an
agent role. The seven ``cognitive_pattern`` literals are the documented
allowed values; ``truncation_priority`` must be a positive integer.

The model pins ``frozen=True`` for immutability and ``extra="forbid"``
so that unknown frontmatter keys fail loudly at parse time rather than
silently drifting into dispatch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _OutputContract(BaseModel):
    """Schema for the ``output_contract`` field in identity frontmatter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: str
    required_sections: list[str]

    def __getitem__(self, key: str) -> object:
        """Support dict-like access for backward compatibility."""
        return getattr(self, key)


class IdentityBlock(BaseModel):
    """Validated identity-block frontmatter metadata.

    All fields are required. The model is frozen (immutable) and rejects
    unknown keys.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    version: str
    truncation_priority: int = Field(gt=0)
    cognitive_pattern: Literal[
        "observe",
        "contract",
        "execute",
        "synthesize",
        "audit",
        "publish",
        "announce",
    ]
    tools: list[str] = Field(default_factory=list)
    output_contract: _OutputContract
