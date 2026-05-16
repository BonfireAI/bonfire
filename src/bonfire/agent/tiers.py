# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Model tier vocabulary and role-aware resolver.

Three-tier capability axis (reasoning/fast/balanced) decoupled from the
commercial tier (free/pro/enterprise) handled by ``bonfire.dispatch.tier``.

The resolver is the public primitive consumed by the dispatch engine
integration. Pure synchronous function -- no I/O, no async, no cache.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from bonfire.agent.roles import AgentRole

if TYPE_CHECKING:
    from bonfire.models.config import BonfireSettings

__all__ = [
    "DEFAULT_ROLE_TIER",
    "GAMIFIED_TO_GENERIC",
    "ModelTier",
    "resolve_model_for_role",
]


class ModelTier(StrEnum):
    """Capability tier for selecting a per-role model.

    Values are the canonical serialized form -- used in TOML, JSONL,
    CLI output, and grep patterns.
    """

    REASONING = "reasoning"
    FAST = "fast"
    BALANCED = "balanced"


# Map of gamified workflow-emitted role strings -> canonical AgentRole.
# Workflows in bonfire.workflow.{standard, research} emit lowercase
# gamified names (scout, knight, ...) into StageSpec.role; the resolver
# normalizes them through this table before tier lookup.
GAMIFIED_TO_GENERIC: Mapping[str, AgentRole] = MappingProxyType(
    {
        "scout": AgentRole.RESEARCHER,
        "knight": AgentRole.TESTER,
        "warrior": AgentRole.IMPLEMENTER,
        "cleric": AgentRole.VERIFIER,
        "prover": AgentRole.VERIFIER,  # workflow alias for the verifier role
        "bard": AgentRole.PUBLISHER,
        "wizard": AgentRole.REVIEWER,
        "steward": AgentRole.CLOSER,
        "sage": AgentRole.SYNTHESIZER,
        "architect": AgentRole.ANALYST,
    }
)


# Default role -> tier mapping. The four roles cited in the ticket
# (researcher=reasoning, tester=fast, implementer=fast, reviewer=reasoning)
# are byte-exact. The other five are inferred from role function:
#   - verifier    -> fast      (mechanical pass/fail, no synthesis)
#   - publisher   -> fast      (PR scaffolding, structural)
#   - closer      -> fast      (merge/announce, mechanical)
#   - synthesizer -> reasoning (multi-source synthesis is the reasoning case)
#   - analyst     -> reasoning (architectural analysis is reasoning)
DEFAULT_ROLE_TIER: Mapping[AgentRole, ModelTier] = MappingProxyType(
    {
        AgentRole.RESEARCHER: ModelTier.REASONING,
        AgentRole.TESTER: ModelTier.FAST,
        AgentRole.IMPLEMENTER: ModelTier.FAST,
        AgentRole.VERIFIER: ModelTier.FAST,
        AgentRole.PUBLISHER: ModelTier.FAST,
        AgentRole.REVIEWER: ModelTier.REASONING,
        AgentRole.CLOSER: ModelTier.FAST,
        AgentRole.SYNTHESIZER: ModelTier.REASONING,
        AgentRole.ANALYST: ModelTier.REASONING,
    }
)


def resolve_model_for_role(role: str, settings: BonfireSettings) -> str:
    """Return the user-configured model string for the given agent role.

    Resolution order:
        1. Normalize ``role`` (strip whitespace + lowercase).
        2. If the normalized value is a canonical ``AgentRole``, use it.
        3. Else, look up the gamified alias in ``GAMIFIED_TO_GENERIC``.
        4. If neither matches, fall back to ``ModelTier.BALANCED`` (no raise).
        5. Look up the tier in ``DEFAULT_ROLE_TIER`` for the resolved
           ``AgentRole`` (fallback ``BALANCED`` if absent, defensive).
        6. Return ``getattr(settings.models, tier.value)``.

    Pure synchronous function. No I/O. No cache. Never raises on string input.
    """
    normalized = role.strip().lower() if isinstance(role, str) else ""

    canonical: AgentRole | None
    try:
        canonical = AgentRole(normalized)
    except ValueError:
        canonical = GAMIFIED_TO_GENERIC.get(normalized)

    if canonical is None:
        tier = ModelTier.BALANCED
    else:
        tier = DEFAULT_ROLE_TIER.get(canonical, ModelTier.BALANCED)

    return getattr(settings.models, tier.value)
