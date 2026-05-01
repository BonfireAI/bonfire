# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Frozen Pydantic model capturing the outcome of an agent dispatch."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from bonfire.models.envelope import Envelope  # noqa: TC001 — Pydantic needs runtime access


class DispatchResult(BaseModel):
    """Immutable result of a dispatch: envelope, timing, retries, cost.

    Fields:
        envelope: The final Envelope (COMPLETED or FAILED).
        duration_seconds: Wall-clock time covering all attempts.
        retries: Number of retry attempts (0 means first-attempt success).
        cost_usd: Cumulative cost across all attempts whose envelope was received.
    """

    model_config = ConfigDict(frozen=True)

    envelope: Envelope
    duration_seconds: float
    retries: int
    cost_usd: float
