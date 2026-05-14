# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Bracket stages — first-class pre/post-pipeline judgment slots.

A *bracket* is a sequential list of :class:`~bonfire.models.plan.StageSpec`
stages that run BEFORE (``pre_bracket``) or AFTER (``post_bracket``) the
main DAG. Brackets exist so that domain-axiom enforcement (the future
Hephaestus / Artificer pre-bracket) and post-pipeline judgment (the v0.1
Caronte / Inquisitor post-bracket) plug into the pipeline engine through
one symmetrical seam instead of via ad-hoc per-feature surgery.

The bracket layer answers a small, typed question per post-bracket
stage envelope:

    Given the envelope this stage produced, what does its outcome mean
    for the pipeline's final ``success`` flag and for downstream
    effectuation (the Steward's apply step)?

The answer is a :class:`BracketDecision`. The function that computes
the answer is a :class:`BracketRouter` (a Protocol so users can plug
in their own routers — TOML-loaded, project-scoped, or
test-injected — without subclassing the engine).

The shipped default is :class:`CaronteBracketRouter`, which reads the
two pinned metadata keys
(:data:`~bonfire.models.envelope.META_BRACKET_VERDICT_STATUS` and
:data:`~bonfire.models.envelope.META_BRACKET_EFFECTUATE`) and maps
PASS/CONCERNS/FAIL onto pipeline ``success`` per the Knight contract.

Hephaestus v1.1 plugs in by passing a different :class:`BracketRouter`
to the engine's ``bracket_router`` kwarg — the engine plumbing does
not change. Main-DAG-failure short-circuit is a *natural* consequence
of the bracket layer running in its own phase after the main DAG
returns success; no per-feature special case lives in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from bonfire.models.envelope import (
    META_BRACKET_EFFECTUATE,
    META_BRACKET_VERDICT_STATUS,
)

if TYPE_CHECKING:
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec


# ---------------------------------------------------------------------------
# BracketDecision — the typed answer a router returns
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BracketDecision:
    """Typed routing decision for a single post-bracket stage envelope.

    The engine consults a :class:`BracketRouter` per post-bracket stage
    and folds each :class:`BracketDecision` into the running pipeline
    outcome:

    - ``success`` — whether this stage's outcome permits the pipeline's
      final ``success`` flag to stay ``True``. Any decision with
      ``success=False`` forces the pipeline result to ``success=False``.
    - ``effectuate`` — whether downstream side-effect application (the
      Steward) is allowed to proceed. A ``False`` value here flips the
      :data:`~bonfire.models.envelope.META_BRACKET_EFFECTUATE` metadata
      key on the bracket envelope before it is recorded.
    - ``reason`` — human-readable note used for events and audit logs.

    The dataclass is immutable so test fixtures and synthesizers can
    pass decisions around as ordinary values.
    """

    success: bool
    effectuate: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# BracketRouter — the Protocol callers plug into the engine
# ---------------------------------------------------------------------------


@runtime_checkable
class BracketRouter(Protocol):
    """Strategy that turns a bracket-stage envelope into a routing decision.

    Implementations are pure — they read the envelope's metadata + result
    and return a :class:`BracketDecision`. They must not mutate engine
    state or perform I/O.

    A custom router can be passed to
    :class:`~bonfire.engine.pipeline.PipelineEngine` at construction
    time via the ``bracket_router`` kwarg. If omitted, the engine
    instantiates :class:`CaronteBracketRouter`.
    """

    def route(self, envelope: Envelope) -> BracketDecision:
        """Return a routing decision for ``envelope``."""
        ...


# ---------------------------------------------------------------------------
# CaronteBracketRouter — the v0.1 default (PASS / CONCERNS / FAIL)
# ---------------------------------------------------------------------------


class CaronteBracketRouter:
    """Default router — PASS/CONCERNS/FAIL → pipeline routing per Knight memo.

    Reads two metadata keys off the bracket-stage envelope:

    - :data:`~bonfire.models.envelope.META_BRACKET_VERDICT_STATUS`
      — ``"PASS"`` | ``"CONCERNS"`` | ``"FAIL"`` (the raw label).
    - :data:`~bonfire.models.envelope.META_BRACKET_EFFECTUATE`
      — explicit boolean (the handler's own pre-computed effectuate
      bit, treated as authoritative when present).

    Routing table (PASS-first, fail-safe default):

    +-----------+---------+-------------+--------------------------+
    | verdict   | success | effectuate  | meaning                  |
    +===========+=========+=============+==========================+
    | PASS      | True    | True        | Steward proceeds.        |
    +-----------+---------+-------------+--------------------------+
    | CONCERNS  | True    | False       | Pipeline ran clean;      |
    |           |         |             | Anta triages.            |
    +-----------+---------+-------------+--------------------------+
    | FAIL      | False   | False       | Bracket rejected.        |
    +-----------+---------+-------------+--------------------------+
    | missing   | True    | True        | Tolerant default —       |
    |           |         |             | stage that didn't emit   |
    |           |         |             | a verdict is treated as  |
    |           |         |             | informational.           |
    +-----------+---------+-------------+--------------------------+
    """

    #: Verdict strings that yield ``success=True``.
    _SUCCESS_VERDICTS: frozenset[str] = frozenset({"PASS", "CONCERNS"})

    #: Verdict strings that yield ``effectuate=True`` (only PASS).
    _EFFECTUATE_VERDICTS: frozenset[str] = frozenset({"PASS"})

    def route(self, envelope: Envelope) -> BracketDecision:
        """Return a :class:`BracketDecision` for ``envelope``."""
        status_raw = envelope.metadata.get(META_BRACKET_VERDICT_STATUS)
        # No verdict emitted → treat as a non-judging bracket stage.
        # (Hephaestus v1.1 may emit pre-bracket gates that omit a
        # verdict status entirely; they are advisory, not authoritative.)
        if status_raw is None:
            return BracketDecision(
                success=True,
                effectuate=True,
                reason="bracket stage emitted no verdict status (advisory)",
            )

        status = str(status_raw).upper()
        success = status in self._SUCCESS_VERDICTS
        # Explicit handler-provided effectuate bit wins when present;
        # otherwise derive from the verdict.
        explicit = envelope.metadata.get(META_BRACKET_EFFECTUATE)
        if isinstance(explicit, bool):
            effectuate = explicit
        else:
            effectuate = status in self._EFFECTUATE_VERDICTS

        return BracketDecision(
            success=success,
            effectuate=effectuate,
            reason=f"caronte verdict={status}",
        )


# ---------------------------------------------------------------------------
# BracketSlot — internal helper binding (stages, router) for the engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BracketSlot:
    """A bracket position — its sequence of stages plus the router.

    Engine-internal type; the public engine surface accepts the raw
    ``list[StageSpec]`` plus an optional ``bracket_router`` and folds
    them into a :class:`BracketSlot` during ``__init__``.
    """

    stages: tuple[StageSpec, ...] = field(default_factory=tuple)
    router: BracketRouter = field(default_factory=CaronteBracketRouter)

    @property
    def is_empty(self) -> bool:
        """``True`` iff the slot has no stages — engine treats as no-op."""
        return not self.stages


__all__ = [
    "BracketDecision",
    "BracketRouter",
    "BracketSlot",
    "CaronteBracketRouter",
]
