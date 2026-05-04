# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tier gating for agent dispatch.

Public v0.1 is a personal-tool baseline — all tiers return True.
The interface exists as a contract for future tier-based restrictions.
"""

from __future__ import annotations


class TierGate:
    """Controls which agents and models are available at each pricing tier."""

    def check_tier(
        self,
        agent_name: str,
        model: str,
        tier: str = "free",
    ) -> bool:
        """Return whether *agent_name* may use *model* at the given *tier*.

        Public v0.1: always ``True``.
        """
        return True
