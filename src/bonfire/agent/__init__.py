"""Agent role definitions and the canonical naming vocabulary."""

from bonfire.agent.roles import AgentRole
from bonfire.agent.tiers import (
    DEFAULT_ROLE_TIER,
    GAMIFIED_TO_GENERIC,
    ModelTier,
    resolve_model_for_role,
)

__all__ = [
    "DEFAULT_ROLE_TIER",
    "GAMIFIED_TO_GENERIC",
    "AgentRole",
    "ModelTier",
    "resolve_model_for_role",
]
