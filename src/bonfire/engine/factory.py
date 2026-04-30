"""Settings factory for engine + handler composition.

Thin factory that builds a ``BonfireSettings`` instance for a pipeline
run. Replaces the silent ``BonfireSettings()`` fallback at the three
constructor sites (``StageExecutor``, ``PipelineEngine``,
``WizardHandler``) with a warn-on-failure path per the Sage architectural
memo at ``docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md``
§C.2 + §G.

The factory is the single composition root for engine settings: callers
that already hold a ``BonfireSettings`` should pass it through the
``settings=`` kwarg on engine + handler constructors; the factory only
fires on the ``settings=None`` branch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.models.config import BonfireSettings

logger = logging.getLogger(__name__)


def load_settings_or_default() -> BonfireSettings:
    """Build a ``BonfireSettings`` instance for a pipeline run.

    Reads ``bonfire.toml`` from cwd and ``BONFIRE_*`` env vars per the
    pydantic-settings source priority. On a *load* failure (malformed
    TOML, env-var coercion error, validator failure), emits a warning to
    the ``bonfire.engine.factory`` logger and falls back to a
    defaults-only ``BonfireSettings`` via ``model_construct`` (bypasses
    validation; safe for the alpha).

    Caller-facing contract:
        - Returns a fully-constructed ``BonfireSettings``.
        - NEVER raises. Catches ``ValidationError``, ``TOMLDecodeError``,
          ``OSError`` and any other load-time failure; warns via
          ``logger.warning``.
        - Pass the returned instance into ``PipelineEngine``,
          ``StageExecutor``, ``WizardHandler`` constructors via
          ``settings=`` to avoid the re-load.

    Returns:
        A ``BonfireSettings`` instance -- either the result of a normal
        ``BonfireSettings()`` load, or a defaults-only instance from
        ``BonfireSettings.model_construct()`` when the load failed.
    """
    from bonfire.models.config import BonfireSettings

    try:
        return BonfireSettings()
    except Exception as exc:  # noqa: BLE001 -- wraps tomllib + pydantic types
        logger.warning(
            "Failed to load BonfireSettings from bonfire.toml/env (%s); "
            "falling back to schema defaults. Pass settings= explicitly "
            "to suppress this warning.",
            exc,
        )
        return BonfireSettings.model_construct()
