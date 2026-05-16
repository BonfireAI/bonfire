# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Per-role tool allow-list policy — W1.5.3 default floor + W4.1 user seam.

The :class:`ToolPolicy` Protocol lets the dispatch layer ask "for this role,
which tools are permitted?" without any particular implementation. The bundled
:class:`DefaultToolPolicy` ships the W1.5.3 floor — eight canonical roles
mapped to tool lists lifted from the Bonfire v0.1 axiom tables.

The :class:`ToolPolicy` Protocol IS the W4.1 user-configurable surface. Users
who wish to override the floor implement :class:`ToolPolicy` and pass their
implementation into ``PipelineEngine`` via the ``tool_policy=`` constructor
kwarg. No TOML loader ships in v0.1; the Protocol seam is the public
surface.

The floor table's gamified role keys (``scout``, ``knight``, ``warrior``, ...)
are a ratified exception to ADR-001's "all code uses generic names" rule —
see ``docs/adr/ADR-001-naming-vocabulary.md`` § Ratified Exceptions and the
pin test ``tests/unit/test_adr_001_ratified_exceptions.py``.
``DefaultToolPolicy.tools_for`` accepts either gamified or generic input via
the ``GAMIFIED_TO_GENERIC`` mapping at ``bonfire.agent.tiers``, so the
floor's internal key vocabulary is invisible to callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from bonfire.agent.tiers import GAMIFIED_TO_GENERIC

__all__ = ["DefaultToolPolicy", "ToolPolicy"]


@runtime_checkable
class ToolPolicy(Protocol):
    """Resolves a role name to its permitted tool list.

    Callers pass a role string (e.g. ``"scout"``, ``"warrior"``) and receive
    the list of SDK tool names that role is allowed to invoke. An empty list
    means "no tools permitted".

    Implementations MUST be pure (same role → same list) and MUST return a
    fresh list each call so callers may mutate.
    """

    def tools_for(self, role: str) -> list[str]: ...


# Inverse mapping from generic ``AgentRole`` value to a gamified key that is
# present in ``DefaultToolPolicy._FLOOR``. ``GAMIFIED_TO_GENERIC`` is
# many-to-one (``cleric`` and ``prover`` both alias ``VERIFIER``); when more
# than one gamified alias resolves to the same generic, we prefer the alias
# that is actually a key in the floor table — that's the one the W4.1 test
# contract pins. Aliases that resolve to generics with no floor entry
# (``architect`` → ``analyst``) are simply not in this inverse map; callers
# passing those generics receive ``[]`` (the floor's natural default).
_FLOOR_KEYS_RATIFIED: frozenset[str] = frozenset(
    {"scout", "knight", "warrior", "prover", "sage", "bard", "wizard", "steward"}
)


def _build_generic_to_gamified() -> Mapping[str, str]:
    inv: dict[str, str] = {}
    for gamified, generic in GAMIFIED_TO_GENERIC.items():
        # Only consider gamified aliases that are actually floor keys.
        if gamified not in _FLOOR_KEYS_RATIFIED:
            continue
        # First-write wins; given the ratified-keys filter, each generic
        # appears at most once anyway.
        inv.setdefault(generic.value, gamified)
    return MappingProxyType(inv)


_GENERIC_TO_GAMIFIED: Mapping[str, str] = _build_generic_to_gamified()


class DefaultToolPolicy:
    """Built-in W1.5.3 floor allow-list.

    Role strings match the gamified names emitted by Bonfire workflow
    factories (``workflows/standard.py``, ``workflows/research.py``).
    ``tools_for`` accepts either gamified or generic input — the generic
    form normalizes through ``GAMIFIED_TO_GENERIC`` at
    ``bonfire.agent.tiers`` and falls back to ``[]`` when no floor entry
    is reachable.
    """

    _FLOOR: dict[str, list[str]] = {
        "scout": ["Read", "Write", "Grep", "WebSearch", "WebFetch"],
        "knight": ["Read", "Write", "Edit", "Grep", "Glob"],
        "warrior": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "prover": ["Read", "Bash", "Grep", "Glob"],
        "sage": ["Read", "Write", "Grep"],
        "bard": ["Read", "Write", "Grep", "Glob"],
        "wizard": ["Read", "Grep", "Glob"],
        "steward": ["Read", "Grep"],
    }

    def tools_for(self, role: str) -> list[str]:
        # Direct lookup: preserves the W4.1 byte-for-byte contract on
        # gamified inputs. ``dict.get`` raises ``TypeError`` for
        # unhashable inputs (list/dict) — that's the documented
        # AMBIG #5 behavior and we preserve it.
        floor_hit = self._FLOOR.get(role)
        if floor_hit is not None:
            return list(floor_hit)

        # Generic-input path: normalize and look up the gamified key.
        # Only str inputs are normalized; non-str hashable inputs (None,
        # int, tuple) just fall through to ``[]`` per AMBIG #5.
        if isinstance(role, str):
            normalized = role.strip().lower()
            gamified = _GENERIC_TO_GAMIFIED.get(normalized)
            if gamified is not None:
                return list(self._FLOOR[gamified])

        return []
