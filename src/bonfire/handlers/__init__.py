"""bonfire.handlers -- pipeline stage handlers.

File-level names stay gamified (historical + grep). The generic role each
handler implements lives in ``HANDLER_ROLE_MAP`` and as a module-level
``ROLE`` constant inside each handler module.

| stem       | class               | generic role | gamified display |
|------------|---------------------|--------------|------------------|
| bard       | BardHandler         | publisher    | Bard             |
| wizard     | WizardHandler       | reviewer     | Wizard           |
| herald     | HeraldHandler       | closer       | Herald           |
| architect  | ArchitectHandler    | analyst      | Architect        |

Note: ``MergePreflightHandler`` is a deterministic verification handler
and bypasses the gamified-display map (``HANDLER_ROLE_MAP``); it appears
in ``__all__`` but not in the role map. See Sage memo
``bon-519-sage-20260428T033101Z.md`` §A Q1 Path β + §D10 line 745.
"""

from __future__ import annotations

from bonfire.agent.roles import AgentRole
from bonfire.handlers.architect import ArchitectHandler
from bonfire.handlers.bard import BardHandler
from bonfire.handlers.herald import HeraldHandler
from bonfire.handlers.merge_preflight import MergePreflightHandler
from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler
from bonfire.handlers.wizard import WizardHandler

HANDLER_ROLE_MAP: dict[str, AgentRole] = {
    "bard": AgentRole.PUBLISHER,
    "wizard": AgentRole.REVIEWER,
    "herald": AgentRole.CLOSER,
    "architect": AgentRole.ANALYST,
}

__all__ = [
    "HANDLER_ROLE_MAP",
    "ArchitectHandler",
    "BardHandler",
    "HeraldHandler",
    "MergePreflightHandler",
    "SageCorrectionBounceHandler",
    "WizardHandler",
]
