# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Shared timeout resolution for Bonfire."""

from __future__ import annotations

import os

DEFAULT_TIMEOUTS: dict[str, float | None] = {
    "version": 5.0,
    "capability": 2.0,
    "git": 5.0,
    "pytest": 300.0,
    "retrieve": 30.0,
    "dispatch": None,
}


def resolve_timeout(
    kind: str, *, override: float | None = None, env_var: str | None = None
) -> float | None:
    """Resolve a timeout in seconds.

    Precedence: explicit ``override`` > ``env_var`` (float-coerced) >
    ``DEFAULT_TIMEOUTS[kind]``. Raises ``KeyError`` for an unknown ``kind``
    when neither an override nor an env value is supplied.
    """
    if override is not None:
        return override
    if env_var is not None:
        raw = os.getenv(env_var)
        if raw is not None:
            return float(raw)
    return DEFAULT_TIMEOUTS[kind]


#: Env var honored by the per-call retrieval timeout resolver.
RETRIEVE_TIMEOUT_ENV = "BONFIRE_RETRIEVE_TIMEOUT_S"

#: Default per-call retrieval timeout (seconds). Behavior-preserving alias of
#: ``DEFAULT_TIMEOUTS["retrieve"]`` re-exported by the two retrieval call sites
#: (``bonfire.mcp.retrieval_server`` and ``bonfire.prompt.precompose``).
DEFAULT_RETRIEVE_TIMEOUT_S: float = DEFAULT_TIMEOUTS["retrieve"]


def retrieve_timeout() -> float:
    """Resolve the per-call retrieval timeout (seconds).

    The single source of truth for both retrieval call sites
    (``bonfire.mcp.retrieval_server`` and ``bonfire.prompt.precompose``).
    Honors the ``BONFIRE_RETRIEVE_TIMEOUT_S`` env override; falls back to
    ``DEFAULT_RETRIEVE_TIMEOUT_S``.
    """
    return resolve_timeout("retrieve", env_var=RETRIEVE_TIMEOUT_ENV)
