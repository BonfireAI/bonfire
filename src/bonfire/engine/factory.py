"""Composition-root factory for ``BonfireSettings`` instances.

Architectural seam (per cluster-351 Sage memo §C.2)
---------------------------------------------------

Three engine + handler classes -- ``PipelineEngine``, ``StageExecutor``,
``WizardHandler`` -- accept ``settings: BonfireSettings | None = None``
in their constructors. Before this seam landed, each class fell back to
``BonfireSettings()`` directly on the ``None`` branch. Three problems
followed from that pattern:

1. **Silent disk + env reads in a constructor.** ``BonfireSettings()``
   reads ``bonfire.toml`` from cwd and ``BONFIRE_*`` env vars (per
   pydantic-settings source priority). A constructor that "looks inert"
   is in fact doing I/O; tests that did not pin cwd or scrub env vars
   were racing against operator-side state.
2. **Silent ``ValidationError`` on malformed TOML.** A typo in
   ``bonfire.toml`` would surface as a raw ``pydantic_core.ValidationError``
   from a constructor the caller thought was inert -- no warn, no
   recovery, no doctrinal alignment with the rest of the repo's
   loud-fail-soft pattern (see ``wizard.py:_parse_verdict``,
   ``pipeline.py:464-480``).
3. **Three identical fallback sites drifting independently.** Each
   constructor's "if None: BonfireSettings()" branch was a copy-paste;
   any improvement (warn, log, structured exception) had to land three
   times.

This module collapses those three sites into one. The factory is the
single fallback rail that:

- Returns a ``BonfireSettings`` on the happy path (clean cwd + no
  ``BONFIRE_*`` env vars).
- Catches ``ValidationError``, ``TOMLDecodeError``, ``OSError``
  (and the broader ``Exception`` catch-all for defense in depth -- the
  factory is a load-failure shield, not a validator) and logs a
  ``WARNING`` with the exception type AND message.
- Falls back to ``BonfireSettings.model_construct()`` -- which bypasses
  validation -- so callers get an instance with field defaults rather
  than a propagated exception.

Caller-facing contract (per Sage §C.2 + test contract §H.2):

- ``load_settings_or_default()`` NEVER raises.
- On load failure, emits exactly one ``WARNING``-level record on the
  ``bonfire.engine.factory`` logger; the message format is
  ``WARNING_MESSAGE_TEMPLATE`` below.
- Returns a fully-constructed ``BonfireSettings`` instance.

Pre-v0.1.0 deprecation note (per Sage §E item 3): the optional
``settings=`` kwarg on ``PipelineEngine.__init__`` /
``StageExecutor.__init__`` / ``WizardHandler.__init__`` is scheduled to
become required at v0.2. Callers building these classes should pass
``settings=load_settings_or_default()`` once at the composition root
and thread the result through, rather than relying on the
``None``-branch fallback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from bonfire.models.config import BonfireSettings

__all__ = ["load_settings_or_default"]


logger = logging.getLogger(__name__)


# Single source of truth for the warning message text. Tests assert on
# the substring ``"Failed to load BonfireSettings"`` (per
# ``test_engine_factory.py::test_load_settings_*_warns_*``); declaring
# the template ``Final`` here keeps that assertion stable across any
# log-message tweaks future maintainers make.
_WARNING_MESSAGE_TEMPLATE: Final[str] = (
    "Failed to load BonfireSettings from bonfire.toml/env "
    "(%s: %s); falling back to schema defaults via model_construct(). "
    "Pass settings= explicitly to the engine + handler constructors to "
    "suppress this warning."
)


def load_settings_or_default() -> BonfireSettings:
    """Build a ``BonfireSettings`` instance for a pipeline run.

    Reads ``bonfire.toml`` from cwd and ``BONFIRE_*`` env vars per
    pydantic-settings source priority. On a *load* failure (malformed
    TOML, env-var coercion error, validator failure, or any other
    ``Exception`` raised during construction), emits a ``WARNING``-level
    log record on the ``bonfire.engine.factory`` logger and falls back
    to a defaults-only ``BonfireSettings`` via ``model_construct``
    (bypasses validation; safe for the alpha window).

    Returns
    -------
    BonfireSettings
        A fully-constructed settings instance. NEVER raises.

    Notes
    -----
    Caller-facing contract (per Sage cluster-351 §C.2):

    - Returns a ``BonfireSettings`` on every code path.
    - On failure, logs a ``WARNING`` containing the exception type AND
      message (the type alone is too cryptic for end-users debugging a
      malformed TOML; the message alone hides whether the failure was a
      TOML decode error or a Pydantic validation error).
    - Pass the returned instance into ``PipelineEngine``,
      ``StageExecutor``, ``WizardHandler`` constructors via
      ``settings=`` to avoid the per-constructor reload cost (~1-10ms
      under nominal conditions per Machinist scout report B).

    Caught exception families (per Sage §C.2 docstring pin):

    - ``pydantic.ValidationError`` -- env-var coercion + validator
      failure.
    - ``tomllib.TOMLDecodeError`` -- malformed ``bonfire.toml``.
    - ``OSError`` -- file permission / unreadable ``bonfire.toml``.
    - ``Exception`` (defensive catch-all) -- never let a constructor
      surprise propagate from this seam; the factory is a load-failure
      shield, not a validator.
    """
    # Per cluster-351 Sage memo §C.2 -- happy path returns a fully
    # constructed BonfireSettings; the import is local to keep the
    # module-level import surface minimal (settings.config is a
    # heavyweight pydantic + tomllib import).
    from bonfire.models.config import BonfireSettings

    try:
        return BonfireSettings()
    except Exception as exc:  # noqa: BLE001 -- factory is a load-failure shield
        # Log type AND message: the type is critical for an operator
        # diagnosing whether the failure was a malformed TOML
        # (TOMLDecodeError), a bad env var (ValidationError), or an
        # I/O issue (OSError). The message provides the specific field
        # / token that tripped the failure.
        logger.warning(
            _WARNING_MESSAGE_TEMPLATE,
            type(exc).__name__,
            exc,
        )
        # Per cluster-351 Sage memo §C.2 -- defensive fallback via
        # ``model_construct`` so callers always receive a usable
        # ``BonfireSettings`` instance with field defaults.
        return BonfireSettings.model_construct()
