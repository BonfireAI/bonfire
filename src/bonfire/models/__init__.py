"""bonfire.models — cross-package data contracts.

This package holds the typed, frozen Pydantic shapes that travel
between every other Bonfire package. It is dependency-free at the
package level so anything in the project may import from it without
risking a cycle.

Sub-modules (imported by path — e.g.
``from bonfire.models.envelope import Envelope``):

    * :mod:`bonfire.models.config` — runtime configuration shapes.
    * :mod:`bonfire.models.envelope` — the ``Envelope`` carried through
      the pipeline plus its ``TaskStatus`` enum.
    * :mod:`bonfire.models.events` — ``BonfireEvent`` base + the typed
      event hierarchy emitted on the bus.
    * :mod:`bonfire.models.plan` — ``WorkflowPlan``, ``StageSpec``,
      ``GateContext`` / ``GateResult`` and related plan-level types.

No ``__all__`` is defined here because the package deliberately does
not re-export — callers reach into the sub-module that owns the type.
"""
