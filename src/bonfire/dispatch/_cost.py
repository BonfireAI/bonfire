# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Shared cost-extraction helpers for dispatch backends.

The two backends extract a ``cost_usd`` from differently-shaped provider
objects, but both must (a) never raise and (b) fall back to ``0.0`` when
the cost is absent or malformed. These helpers factor that swallow-and-
default discipline into one place WITHOUT changing any output value:

* :func:`safe_cost_from_usage` — for ``pydantic_ai`` style results that
  expose ``result.usage.total_tokens`` (cost = tokens * ``TOKEN_COST_USD``).
* :func:`safe_cost_from_attr` — for SDK ``ResultMessage`` style objects
  that expose a ready-computed cost attribute (e.g. ``total_cost_usd``).

Both return ``float`` and never propagate ``TypeError``/``AttributeError``.
"""

from __future__ import annotations

from typing import Any

# Per-token cost multiplier used by the pydantic_ai backend's token-count
# heuristic. Kept identical to the value previously inlined in
# ``PydanticAIBackend.execute()`` so extraction is byte-for-byte neutral.
TOKEN_COST_USD: float = 0.00001


def safe_cost_from_usage(result: Any) -> float:
    """Extract a token-derived cost from a ``usage``-bearing result.

    Mirrors the inlined logic in ``PydanticAIBackend.execute()``:

        usage = getattr(result, "usage", None)
        if usage is not None:
            total_tokens = getattr(usage, "total_tokens", 0) or 0
            if isinstance(total_tokens, (int, float)):
                cost_usd = total_tokens * 0.00001

    Returns ``0.0`` when ``usage`` is absent/``None``, when ``total_tokens``
    is missing/``None``/non-numeric, and swallows ``(TypeError,
    AttributeError)`` exactly as the original did.
    """
    cost_usd = 0.0
    try:
        usage = getattr(result, "usage", None)
        if usage is not None:
            total_tokens = getattr(usage, "total_tokens", 0) or 0
            if isinstance(total_tokens, (int, float)):
                cost_usd = total_tokens * TOKEN_COST_USD
    except (TypeError, AttributeError):
        cost_usd = 0.0
    return cost_usd


def safe_cost_from_attr(obj: Any, attr: str) -> float:
    """Extract a ready-computed cost attribute, defaulting to ``0.0``.

    Mirrors the inlined logic in ``SdkBackend._do_execute()``:

        cost_usd = getattr(msg, "total_cost_usd", None) or 0.0

    A missing attribute, a ``None`` value, or any other falsy value yields
    ``0.0`` — identical to the original ``... or 0.0`` expression.
    """
    return getattr(obj, attr, None) or 0.0
