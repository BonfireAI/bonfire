# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""bonfire.handlers -- pipeline stage handlers.

File-level names stay gamified (historical + grep). The generic role each
handler implements lives in ``HANDLER_ROLE_MAP`` and as a module-level
``ROLE`` constant inside each handler module.

| stem                    | class                          | generic role | gamified display |
|-------------------------|--------------------------------|--------------|------------------|
| bard                    | BardHandler                    | publisher    | Bard             |
| wizard                  | WizardHandler                  | reviewer     | Wizard           |
| steward                 | StewardHandler                 | closer       | Steward          |
| architect               | ArchitectHandler               | analyst      | Architect        |
| sage_correction_bounce  | SageCorrectionBounceHandler    | synthesizer  | Sage             |

Deterministic verification handlers bypass the gamified-display map
(``HANDLER_ROLE_MAP``); they appear in ``__all__`` but not in the role
map. Today: ``MergePreflightHandler`` (verifier). The synthesizer-
correction stage (``SageCorrectionBounceHandler``) IS in the map — it
binds the ``sage_correction_bounce`` stage stem to
``AgentRole.SYNTHESIZER`` so the display layer can resolve its gamified
name through the same path as the other handlers. See Sage memo
``bon-519-sage-20260428T033101Z.md`` §A Q1 Path beta + §D10 line 745.
"""

from __future__ import annotations

from bonfire.agent.roles import AgentRole
from bonfire.handlers.architect import ArchitectHandler
from bonfire.handlers.bard import BardHandler
from bonfire.handlers.merge_preflight import MergePreflightHandler
from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler
from bonfire.handlers.steward import StewardHandler
from bonfire.handlers.wizard import WizardHandler

HANDLER_ROLE_MAP: dict[str, AgentRole] = {
    "bard": AgentRole.PUBLISHER,
    "wizard": AgentRole.REVIEWER,
    "steward": AgentRole.CLOSER,
    "sage_correction_bounce": AgentRole.SYNTHESIZER,
    "architect": AgentRole.ANALYST,
}

__all__ = [
    "HANDLER_ROLE_MAP",
    "ArchitectHandler",
    "BardHandler",
    "StewardHandler",
    "MergePreflightHandler",
    "SageCorrectionBounceHandler",
    "WizardHandler",
]
