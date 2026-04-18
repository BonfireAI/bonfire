"""Workflow registry — a named catalog of workflow factories.

The registry maps string names to factory callables, enabling
configuration-driven workflow selection without hardcoded imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from bonfire.models.plan import WorkflowPlan


class WorkflowRegistry:
    """A named catalog of workflow factory functions.

    Register factories by name, retrieve them by name, list what's available.
    Duplicate registrations are rejected — rename or remove first.
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., WorkflowPlan]] = {}

    def register(self, name: str, factory: Callable[..., WorkflowPlan]) -> None:
        """Register a workflow factory under *name*.

        Raises:
            ValueError: If *name* is already registered.
        """
        if name in self._factories:
            raise ValueError(
                f"Workflow '{name}' is already registered. "
                "Remove it first or choose a different name."
            )
        self._factories[name] = factory

    def get(self, name: str) -> Callable[..., WorkflowPlan]:
        """Retrieve the factory registered under *name*.

        Raises:
            KeyError: If *name* is not registered.
        """
        try:
            return self._factories[name]
        except KeyError:
            available = ", ".join(sorted(self._factories)) or "(none)"
            raise KeyError(f"No workflow registered as '{name}'. Available: {available}") from None

    def list_names(self) -> list[str]:
        """Return a list of all registered workflow names."""
        return list(self._factories.keys())

    def __len__(self) -> int:
        return len(self._factories)

    def __contains__(self, name: str) -> bool:
        return name in self._factories

    def __repr__(self) -> str:
        names = ", ".join(sorted(self._factories))
        return f"WorkflowRegistry([{names}])"


def get_default_registry() -> WorkflowRegistry:
    """Build a registry pre-loaded with the five built-in workflow factories."""
    from bonfire.workflows.research import dual_scout, spike, triple_scout
    from bonfire.workflows.standard import debug, standard_build

    registry = WorkflowRegistry()
    registry.register("standard_build", standard_build)
    registry.register("debug", debug)
    registry.register("dual_scout", dual_scout)
    registry.register("triple_scout", triple_scout)
    registry.register("spike", spike)
    return registry
