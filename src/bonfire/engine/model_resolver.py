"""Dispatch-site model resolver helper.

Pure synchronous primitive that collapses the three-tier ``or`` chain used
at every dispatch call site (``StageExecutor``, ``PipelineEngine``,
``WizardHandler``) into a single source-of-truth helper. Per the Sage
architectural memo at
``docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md`` §C.1
+ §F, this module replaces the inline precedence chain at the three call
sites without altering its behavior.

The inner role-based primitive ``resolve_model_for_role`` continues to
live at ``bonfire.agent.tiers`` (per the cluster-350 D-CL.1 lock); this
module is the *dispatch-site* wrapper that adds the explicit-override and
config-default layers around it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.agent.tiers import resolve_model_for_role

if TYPE_CHECKING:
    from bonfire.models.config import BonfireSettings, PipelineConfig


def resolve_dispatch_model(
    *,
    explicit_override: str,
    role: str,
    settings: BonfireSettings,
    config: PipelineConfig,
) -> str:
    """Return the model string for a dispatch call site.

    Three-tier precedence (locked by Sage cluster-350 D-CL.1 and ratified
    by cluster-351):

        1. ``explicit_override`` -- per-stage / per-envelope escape hatch.
           Empty string falls through to (2).
        2. ``resolve_model_for_role(role, settings)`` -- role-based
           routing via ``ModelTier`` (returns the string from
           ``settings.models``).
        3. ``config.model`` -- pipeline default (``PipelineConfig.model``).

    Pure synchronous function. Never raises on string input. Performs no
    I/O -- ``settings`` and ``config`` are passed in pre-built; the helper
    does not instantiate ``BonfireSettings()``. Role normalization is
    delegated to ``resolve_model_for_role``; the helper does not strip or
    lowercase ``role`` before delegating.

    Args:
        explicit_override: Per-call-site override (envelope.model in the
            executor; ``spec.model_override`` in the pipeline; the wizard's
            ``stage.model_override or ""`` in the reviewer handler).
        role: Stage role string. Passed verbatim to
            ``resolve_model_for_role`` which performs normalization.
        settings: ``BonfireSettings`` instance carrying ``settings.models``.
        config: ``PipelineConfig`` carrying the pipeline-default model.

    Returns:
        Non-empty model string suitable for ``DispatchOptions.model``.
        Empty string is only returned if (1), (2), and (3) are ALL empty
        -- defensive return value preserves today's executor contract.
    """
    return explicit_override or resolve_model_for_role(role, settings) or config.model
