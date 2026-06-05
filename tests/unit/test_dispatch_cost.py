# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Unit tests for ``bonfire.dispatch._cost`` — shared cost-extraction helpers.

These helpers factor the duplicated cost-extraction logic from the two
backends without changing any output value:

* :func:`safe_cost_from_usage` mirrors ``pydantic_ai_backend.execute()``
  (``getattr(result, "usage", None)`` → ``usage.total_tokens or 0`` →
  ``isinstance(int|float)`` → ``* 0.00001``; swallow ``(TypeError,
  AttributeError)`` → ``0.0``).
* :func:`safe_cost_from_attr` mirrors ``sdk_backend._do_execute()``
  (``getattr(obj, attr, None) or 0.0``).

The pin is BEHAVIOR PRESERVATION: every assertion below encodes the exact
value the inlined code produced before extraction.
"""

from __future__ import annotations

from types import SimpleNamespace

from bonfire.dispatch._cost import safe_cost_from_attr, safe_cost_from_usage

_TOKEN_RATE = 0.00001


# ---------------------------------------------------------------------------
# safe_cost_from_usage — pydantic_ai backend path
# ---------------------------------------------------------------------------


class TestSafeCostFromUsage:
    def test_valid_usage_total_tokens(self):
        """``usage.total_tokens`` numeric → tokens * 0.00001."""
        result = SimpleNamespace(usage=SimpleNamespace(total_tokens=500))
        assert safe_cost_from_usage(result) == 500 * _TOKEN_RATE

    def test_usage_none(self):
        """``usage`` attribute is ``None`` → 0.0 (no crash)."""
        result = SimpleNamespace(usage=None)
        assert safe_cost_from_usage(result) == 0.0

    def test_usage_missing_attr(self):
        """``result`` has no ``usage`` attribute at all → 0.0."""
        result = SimpleNamespace()
        assert safe_cost_from_usage(result) == 0.0

    def test_total_tokens_none(self):
        """``total_tokens`` is ``None`` → ``or 0`` → 0.0."""
        result = SimpleNamespace(usage=SimpleNamespace(total_tokens=None))
        assert safe_cost_from_usage(result) == 0.0

    def test_total_tokens_missing(self):
        """``usage`` has no ``total_tokens`` attribute → default 0 → 0.0."""
        result = SimpleNamespace(usage=SimpleNamespace())
        assert safe_cost_from_usage(result) == 0.0

    def test_total_tokens_non_numeric(self):
        """Non-numeric ``total_tokens`` → isinstance gate fails → 0.0."""
        result = SimpleNamespace(usage=SimpleNamespace(total_tokens="not-a-number"))
        assert safe_cost_from_usage(result) == 0.0

    def test_total_tokens_float(self):
        """Float ``total_tokens`` is accepted by the isinstance gate."""
        result = SimpleNamespace(usage=SimpleNamespace(total_tokens=250.0))
        assert safe_cost_from_usage(result) == 250.0 * _TOKEN_RATE

    def test_total_tokens_zero(self):
        """Zero tokens → ``or 0`` keeps 0 → cost 0.0."""
        result = SimpleNamespace(usage=SimpleNamespace(total_tokens=0))
        assert safe_cost_from_usage(result) == 0.0


# ---------------------------------------------------------------------------
# safe_cost_from_attr — sdk backend path
# ---------------------------------------------------------------------------


class TestSafeCostFromAttr:
    def test_total_cost_usd_present(self):
        """Numeric attribute flows straight through."""
        msg = SimpleNamespace(total_cost_usd=0.42)
        assert safe_cost_from_attr(msg, "total_cost_usd") == 0.42

    def test_total_cost_usd_none(self):
        """``None`` → ``or 0.0`` → 0.0."""
        msg = SimpleNamespace(total_cost_usd=None)
        assert safe_cost_from_attr(msg, "total_cost_usd") == 0.0

    def test_total_cost_usd_missing(self):
        """Missing attribute → default None → ``or 0.0`` → 0.0."""
        msg = SimpleNamespace()
        assert safe_cost_from_attr(msg, "total_cost_usd") == 0.0

    def test_total_cost_usd_zero(self):
        """Zero is falsy → ``or 0.0`` → 0.0 (identical to the inlined code)."""
        msg = SimpleNamespace(total_cost_usd=0.0)
        assert safe_cost_from_attr(msg, "total_cost_usd") == 0.0
