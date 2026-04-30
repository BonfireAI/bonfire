"""Per-call-site model resolution for backend-mode dispatch.

Architectural seam (per cluster-351 Sage memo §C.1)
---------------------------------------------------

Three call sites in the engine and handler tree -- ``StageExecutor``,
``PipelineEngine``, and ``WizardHandler`` -- each needed to resolve "what
model string should ``DispatchOptions.model`` carry?" by combining a
per-call-site explicit override, the role-based ``ModelTier`` lookup
(``bonfire.agent.tiers.resolve_model_for_role``), and the pipeline default
on ``PipelineConfig.model``. Before this seam landed, each of the three
call sites carried its own inline ``or``-chain. They rhymed but did not
match: the pipeline's chain stamped the dispatched model BACK onto
``Envelope.model`` (a public-vs-internal contract bug, see Sage memo §D)
while the executor used an empty-string sentinel; the wizard ordered the
fallback differently again.

This module is the single seam those three call sites converge on. The
public primitive ``resolve_model_for_role(role, settings)`` continues to
live at ``bonfire.agent.tiers`` (per ``bon-350-sage-20260427T182947Z.md``
D-CL.1) -- this helper is a thin engine-side compositor that adds the
explicit-override and config-fallback rails without leaking any new
vocabulary into ``bonfire.agent``.

Three-tier precedence (locked by Sage cluster-350 D-CL.1, ratified by
cluster-351 §C.1):

    1. ``explicit_override`` -- per-stage / per-envelope escape hatch.
       Empty string falls through to (2).
    2. ``resolve_model_for_role(role, settings)`` -- role-based routing
       via ``ModelTier`` (returns string from ``settings.models``).
    3. ``config.model`` -- pipeline default (``PipelineConfig.model``).

Defensive contract: when all three layers are empty, return the
empty-string sentinel ``""``. The helper NEVER raises on string input
and performs NO I/O (purity asserted by
``tests/unit/test_engine_model_resolver.py::test_resolve_dispatch_model_purity_no_io``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from bonfire.agent.tiers import resolve_model_for_role

if TYPE_CHECKING:
    from bonfire.models.config import BonfireSettings, PipelineConfig

__all__ = ["resolve_dispatch_model"]


# Sentinel for the "all three precedence layers were empty" defensive
# return. Same string value as Python's literal ``""``; declaring it
# ``Final`` here documents the architectural intent that downstream
# code must treat this as the "no model resolved" signal rather than a
# legitimate model name.
_EMPTY_MODEL_SENTINEL: Final[str] = ""


def resolve_dispatch_model(
    *,
    explicit_override: str,
    role: str,
    settings: BonfireSettings,
    config: PipelineConfig,
) -> str:
    """Return the model string for a backend-mode dispatch call site.

    Three-tier precedence (per Sage cluster-351 §C.1):

        1. ``explicit_override`` -- per-stage / per-envelope escape hatch.
           Empty string falls through to (2).
        2. ``resolve_model_for_role(role, settings)`` -- role-based
           routing via ``ModelTier`` (returns a string sourced from
           ``settings.models.{reasoning,fast,balanced}``).
        3. ``config.model`` -- pipeline default
           (``PipelineConfig.model``).

    Pure synchronous function. Never raises on string input.

    Parameters
    ----------
    explicit_override:
        The per-call-site override. The executor passes
        ``envelope.model`` (built from ``stage.model_override or ""`` at
        ``executor.py:196``); the pipeline passes ``spec.model_override``
        directly; the wizard passes ``stage.model_override or ""``.
    role:
        Verbatim role string. The helper does NOT normalize -- the inner
        ``resolve_model_for_role`` strips + lowercases at
        ``tiers.py:99``. Empty string is fine; it routes through the
        ``BALANCED`` tier fallback in the inner resolver.
    settings:
        ``BonfireSettings`` instance threaded from the composition root.
        See ``bonfire.engine.factory.load_settings_or_default`` for the
        canonical fallback when no settings are explicitly provided.
    config:
        ``PipelineConfig`` for the engine; its ``model`` field is the
        last-ditch fallback.

    Returns
    -------
    str
        Non-empty model string suitable for
        ``DispatchOptions.model`` on the happy path. Empty string
        (``_EMPTY_MODEL_SENTINEL``) is only returned if (1), (2), and
        (3) are ALL empty -- this defensive return value preserves
        today's executor contract (``executor.py:196`` already produces
        an empty-string envelope.model when no override is set).

    Notes
    -----
    The helper deliberately does NOT (per Sage §C.1):

    - Instantiate ``BonfireSettings()``: settings flow in as a
      parameter; the helper is pure.
    - Normalize role strings: ``resolve_model_for_role`` already
      normalizes (``tiers.py:99``).
    - Cache: memoization is separable from precedence and is rejected
      for v0.1 per Sage memo §B.1 (fork-safety + test-isolation).
    """
    # Per cluster-351 Sage memo §C.1 layer 1 -- explicit_override wins.
    if explicit_override:
        return explicit_override

    # Per cluster-351 Sage memo §C.1 layer 2 -- role-based ModelTier
    # routing. Inner resolver normalizes the role string itself.
    role_resolved = resolve_model_for_role(role, settings)
    if role_resolved:
        return role_resolved

    # Per cluster-351 Sage memo §C.1 layer 3 -- pipeline default
    # fallback. May itself be ``""`` if config.model is unset; the
    # defensive contract preserves that as the empty-string sentinel.
    return config.model or _EMPTY_MODEL_SENTINEL
