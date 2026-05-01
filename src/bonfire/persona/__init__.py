# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""bonfire.persona — CLI display translation subsystem.

The persona module is Bonfire's display layer. It turns pipeline events
into character-voiced lines and translates canonical agent role values
into persona-specific display labels via the three-layer naming
vocabulary (:mod:`bonfire.naming`).

Personas are display-only. They never touch agent prompts, quality
gates, or any part of the orchestration pipeline. A persona swap
changes what the user sees — never what the system does.

Public surface:
    * :class:`BasePersona` — default implementation.
    * :class:`PhraseBank` — anti-repeat formatter.
    * :class:`PersonaProtocol` — structural contract
      (``@runtime_checkable``).
    * :class:`PersonaLoader` — two-tier TOML discovery with total
      :meth:`~PersonaLoader.load` and strict
      :meth:`~PersonaLoader.validate`.
    * :class:`PersonaSchemaError` — exception raised by strict
      validation.
"""

from bonfire.persona.base import BasePersona
from bonfire.persona.loader import PersonaLoader, PersonaSchemaError
from bonfire.persona.phrase_bank import PhraseBank
from bonfire.persona.protocol import PersonaProtocol

__all__ = [
    "BasePersona",
    "PersonaLoader",
    "PersonaProtocol",
    "PersonaSchemaError",
    "PhraseBank",
]
