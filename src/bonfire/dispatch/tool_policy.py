"""Per-role tool allow-list policy — W1.5.3 default floor.

The :class:`ToolPolicy` Protocol lets the dispatch layer ask "for this role,
which tools are permitted?" without any particular implementation. The bundled
:class:`DefaultToolPolicy` ships the W1.5.3 floor — eight canonical roles
mapped to tool lists lifted from the Bonfire v0.1 axiom tables.

W4.1 (user TOML override) is a future concern; users who wish to override can
implement :class:`ToolPolicy` and pass it into ``StageExecutor`` /
``PipelineEngine`` via the ``tool_policy=`` constructor kwarg.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["DefaultToolPolicy", "ToolPolicy"]


@runtime_checkable
class ToolPolicy(Protocol):
    """Resolves a role name to its permitted tool list.

    Callers pass a role string (e.g. ``"scout"``, ``"warrior"``) and receive
    the list of SDK tool names that role is allowed to invoke. An empty list
    means "no tools permitted" (the SDK interprets ``allowed_tools=[]``
    combined with ``permission_mode='dontAsk'`` as deny-all).

    Implementations MUST be pure (same role → same list) and MUST return a
    fresh list each call so callers may mutate.
    """

    def tools_for(self, role: str) -> list[str]: ...


class DefaultToolPolicy:
    """Built-in W1.5.3 floor allow-list.

    Role strings match the gamified names emitted by Bonfire workflow
    factories (``workflows/standard.py``, ``workflows/research.py``). Unmapped
    roles return an empty list.
    """

    _FLOOR: dict[str, list[str]] = {
        "scout":   ["Read", "Write", "Grep", "WebSearch", "WebFetch"],
        "knight":  ["Read", "Write", "Edit", "Grep", "Glob"],
        "warrior": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "prover":  ["Read", "Bash", "Grep", "Glob"],
        "sage":    ["Read", "Write", "Grep"],
        "bard":    ["Read", "Write", "Grep", "Glob"],
        "wizard":  ["Read", "Grep", "Glob"],
        "herald":  ["Read", "Grep"],
    }

    def tools_for(self, role: str) -> list[str]:
        return list(self._FLOOR.get(role, []))
