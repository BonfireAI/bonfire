# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Lock the ADR-001 Ratified Exceptions list — no silent vocabulary drift.

ADR-001 ratifies a single exception to "all code uses generic names": the
``DefaultToolPolicy._FLOOR`` table keys on gamified names to match the
workflow-factory wire format. This test ensures the exception remains
coherent: every floor key must be a known gamified alias in
``GAMIFIED_TO_GENERIC``. New gamified-keyed surfaces require amending the
ADR-001 § Ratified Exceptions section, not silently extending the set.
"""

from __future__ import annotations

from bonfire.agent.tiers import GAMIFIED_TO_GENERIC
from bonfire.dispatch.tool_policy import DefaultToolPolicy


def test_floor_keys_are_ratified_gamified_aliases() -> None:
    """Every ``_FLOOR`` key MUST be a known alias in ``GAMIFIED_TO_GENERIC``.

    If this test fails, you have either:

    1. Added a new role to the floor table — amend ADR-001 § Ratified
       Exceptions to ratify the new key, or migrate the new key to the
       generic ``AgentRole`` value per the ADR's default rule.
    2. Removed an alias from ``GAMIFIED_TO_GENERIC`` — restore the alias
       or migrate the corresponding floor key.

    Either path keeps the binding doc, the implementation, and the test
    suite from silently drifting again.
    """
    policy = DefaultToolPolicy()
    floor_keys = set(policy._FLOOR.keys())
    ratified_aliases = set(GAMIFIED_TO_GENERIC.keys())

    extra = floor_keys - ratified_aliases
    assert not extra, (
        f"_FLOOR contains role keys not in GAMIFIED_TO_GENERIC: {sorted(extra)}. "
        "Amend ADR-001 § Ratified Exceptions before extending the set."
    )
