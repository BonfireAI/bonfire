# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Lock the ADR-001 Ratified Exceptions list — no silent vocabulary drift.

ADR-001 ratifies a single exception to "all code uses generic names": the
``DefaultToolPolicy._FLOOR`` table keys on gamified names to match the
workflow-factory wire format. This test enforces the exception's closed-list
claim: the floor's keys MUST equal the exact ratified set, AND every
ratified key MUST resolve through ``GAMIFIED_TO_GENERIC``. New gamified-
keyed surfaces require amending the ADR-001 § Ratified Exceptions section,
not silently extending the set.
"""

from __future__ import annotations

from bonfire.agent.tiers import GAMIFIED_TO_GENERIC
from bonfire.dispatch.tool_policy import DefaultToolPolicy

# The exact set of role keys ratified in ADR-001 § Ratified Exceptions.
# Keep in lockstep with the ADR text. The closed-list assertion below catches
# silent drift in either direction (adding or removing a key without amending
# the binding doc).
RATIFIED_FLOOR_KEYS: frozenset[str] = frozenset(
    {"scout", "knight", "warrior", "prover", "sage", "bard", "wizard", "steward"}
)


def test_floor_keys_match_adr_ratified_set() -> None:
    """``_FLOOR.keys()`` MUST equal the ADR-001 ratified set — closed-list enforcement.

    Two layers are checked, each with its own assertion so failures point to
    the precise drift:

    1. **Closed-list:** ``_FLOOR`` is exactly ``RATIFIED_FLOOR_KEYS``.
       Adding or removing a key without amending the ADR fails here.
    2. **Coherence:** every ratified key is a known alias in
       ``GAMIFIED_TO_GENERIC``. Removing an alias from the mapping or
       ratifying a key with no alias fails here.

    Either failure means the binding doc, the floor table, and the alias map
    have drifted. Reconcile by amending ADR-001 § Ratified Exceptions before
    changing the code.
    """
    floor_keys = frozenset(DefaultToolPolicy()._FLOOR.keys())
    ratified_aliases = frozenset(GAMIFIED_TO_GENERIC.keys())

    assert floor_keys == RATIFIED_FLOOR_KEYS, (
        "_FLOOR keys diverge from ADR-001 § Ratified Exceptions.\n"
        f"  In _FLOOR but not ratified: {sorted(floor_keys - RATIFIED_FLOOR_KEYS)}\n"
        f"  Ratified but missing from _FLOOR: {sorted(RATIFIED_FLOOR_KEYS - floor_keys)}\n"
        "Amend the ADR before changing the floor key set."
    )
    assert RATIFIED_FLOOR_KEYS <= ratified_aliases, (
        "Ratified keys not present in GAMIFIED_TO_GENERIC: "
        f"{sorted(RATIFIED_FLOOR_KEYS - ratified_aliases)}. "
        "Restore the alias in agent/tiers.py or amend the ratified set."
    )
