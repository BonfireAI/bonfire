# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""PersonaProtocol — structural contract for persona implementations.

Display-only. Transforms pipeline events into character-voiced renderables
for CLI output. Never touches agent prompts or quality gates.

The protocol is a ``typing.Protocol`` decorated with ``@runtime_checkable``
so ``isinstance(obj, PersonaProtocol)`` works. It is NOT an ABC — personas
conform structurally, not by inheritance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bonfire.models.events import BonfireEvent


@runtime_checkable
class PersonaProtocol(Protocol):
    """Contract for persona implementations."""

    @property
    def name(self) -> str:
        """The persona's display name."""
        ...

    def format_event(self, event: BonfireEvent) -> str | None:
        """Format a pipeline event into a string, or None if unhandled."""
        ...

    def format_summary(self, stats: dict) -> str:
        """Format a pipeline summary into a string."""
        ...
