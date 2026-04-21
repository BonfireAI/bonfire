"""BasePersona — default persona implementation.

Satisfies :class:`~bonfire.persona.protocol.PersonaProtocol` structurally.
Uses a :class:`~bonfire.persona.phrase_bank.PhraseBank` to format events
and carries an optional ``display_names`` map so the CLI can translate
canonical :class:`~bonfire.agent.roles.AgentRole` values into gamified
labels on a per-persona basis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.naming import ROLE_DISPLAY
from bonfire.persona.phrase_bank import PhraseBank

if TYPE_CHECKING:
    from bonfire.agent.roles import AgentRole
    from bonfire.models.events import BonfireEvent


class BasePersona:
    """Minimal persona that formats events via a :class:`PhraseBank`.

    Parameters
    ----------
    name:
        Persona identity — the serialized string form.
    phrases:
        Mapping of event types (optionally with ``:variant`` suffix) to
        lists of format-string phrases. Missing or ``None`` yields an
        empty bank.
    display_names:
        Optional mapping of :class:`AgentRole` values (as strings) to
        gamified display labels. If a role is absent from this map,
        :meth:`display_name` falls back to the professional label from
        :data:`~bonfire.naming.ROLE_DISPLAY`.
    """

    def __init__(
        self,
        name: str,
        phrases: dict[str, list[str]] | None = None,
        display_names: dict[str, str] | None = None,
    ) -> None:
        self._name = name
        self._bank = PhraseBank(phrases or {})
        self._display_names: dict[str, str] = dict(display_names or {})

    @property
    def name(self) -> str:
        """The persona's identity string."""
        return self._name

    def format_event(self, event: BonfireEvent) -> str | None:
        """Format a pipeline event, or return None if unhandled."""
        event_type: str = getattr(event, "event_type", "")
        context = event.model_dump()
        return self._bank.select(event_type, context)

    def format_summary(self, stats: dict) -> str:
        """Format a pipeline summary into a one-line string."""
        parts = [f"{k}={v}" for k, v in stats.items()]
        return f"[{self._name}] " + ", ".join(parts)

    def display_name(self, role: AgentRole) -> str:
        """Return the persona's display name for *role*.

        Lookup order:
          1. Gamified label carried by this persona (``display_names`` map).
          2. Professional label from :data:`bonfire.naming.ROLE_DISPLAY`.

        Never raises for any canonical :class:`AgentRole` value.
        """
        key = role.value if hasattr(role, "value") else str(role)
        gamified = self._display_names.get(key)
        if gamified:
            return gamified
        fallback = ROLE_DISPLAY.get(key)
        if fallback is not None:
            return fallback.professional
        # Last-resort: echo the role's string form. Unreachable for any
        # canonical AgentRole, but keeps the method total for any caller.
        return key
