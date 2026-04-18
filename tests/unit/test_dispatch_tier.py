"""RED tests for ``bonfire.dispatch.tier`` — W3.2 TierGate contract.

Canonical Sage synthesis of Knight-A (resilience) + Knight-B (fidelity).
Public v0.1 ships ``TierGate`` as a *contract*: every call returns ``True``
because v0.1 is the personal-tool baseline. The reason this suite still
carries weight is that the SHAPE of that contract is load-bearing for any
future commercial tier logic. If v0.1's gate accidentally accepts positional
args, swallows keyword drift, or raises on unknown tiers, every tier-aware
fork inherits the footgun.

Invariants locked by this suite
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Canonical path ``bonfire.dispatch.tier.TierGate`` AND package re-export
  ``bonfire.dispatch.TierGate`` resolve to the same class object.
* ``check_tier(*, agent_name, model, tier="free") -> bool`` — keyword-
  friendly shape, ``tier`` defaults to ``"free"``.
* Return type is strictly ``bool`` (not truthy ``1`` or ``"yes"``).
* All tier strings return ``True`` in v0.1 — including unknown tiers and
  empty strings. No exceptions leak for any combination of agent / model /
  tier (a gate that throws would hard-fail the dispatcher).
* Construction takes no required args (v0.1 gate is stateless).
* Instances are independent — no hidden singleton / global state.
"""

from __future__ import annotations

import pytest

try:
    from bonfire.dispatch.tier import TierGate
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    TierGate = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.dispatch.tier is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.tier not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Imports / re-exports
# ---------------------------------------------------------------------------


class TestTierGateImports:
    """TierGate is importable from module and package."""

    def test_import_from_tier_module(self):
        from bonfire.dispatch.tier import TierGate as _TG

        assert _TG is not None

    def test_import_from_dispatch_package(self):
        from bonfire.dispatch import TierGate as _TG

        assert _TG is not None

    def test_package_and_module_export_same_class(self):
        from bonfire.dispatch import TierGate as pkg_cls
        from bonfire.dispatch.tier import TierGate as mod_cls

        assert pkg_cls is mod_cls


# ---------------------------------------------------------------------------
# Construction — stateless, zero-arg
# ---------------------------------------------------------------------------


class TestTierGateConstruction:
    """TierGate construction is a zero-arg, stateless operation in v0.1."""

    def test_constructs_with_no_args(self):
        gate = TierGate()
        assert gate is not None

    def test_independent_instances(self):
        """Two gates must be distinct objects (no singleton masquerading)."""
        a = TierGate()
        b = TierGate()
        assert a is not b


# ---------------------------------------------------------------------------
# check_tier returns True for every combination in v0.1
# ---------------------------------------------------------------------------


class TestCheckTierAlwaysTrue:
    """In v0.1, every check_tier call returns True — no commercial gating."""

    def test_returns_true_for_free_tier(self):
        gate = TierGate()
        assert gate.check_tier(agent_name="scout", model="claude-sonnet", tier="free") is True

    def test_returns_true_for_pro_tier(self):
        gate = TierGate()
        assert gate.check_tier(agent_name="knight", model="claude-opus", tier="pro") is True

    def test_returns_true_for_enterprise_tier(self):
        gate = TierGate()
        assert gate.check_tier(agent_name="wizard", model="claude-opus", tier="enterprise") is True

    def test_returns_true_for_unknown_tier(self):
        """Unknown tier strings do NOT crash or return False — graceful default."""
        gate = TierGate()
        assert gate.check_tier(agent_name="warrior", model="gpt-4", tier="alien") is True

    def test_returns_true_for_empty_strings(self):
        """Empty strings for every arg — still graceful True."""
        gate = TierGate()
        assert gate.check_tier(agent_name="", model="", tier="") is True

    @pytest.mark.parametrize(
        ("agent", "model", "tier"),
        [
            ("scout", "claude-haiku", "free"),
            ("knight", "claude-sonnet", "pro"),
            ("wizard", "claude-opus", "enterprise"),
            ("bard", "deepseek-v3", "free"),
            ("sage", "gpt-4o", "hobbyist"),
            ("orchestrator", "model-with-slashes/v2", "free"),
        ],
    )
    def test_returns_true_for_matrix_of_combos(self, agent: str, model: str, tier: str):
        gate = TierGate()
        assert gate.check_tier(agent_name=agent, model=model, tier=tier) is True


# ---------------------------------------------------------------------------
# Interface shape — defaults + return type
# ---------------------------------------------------------------------------


class TestCheckTierInterface:
    """The callable interface enforces the documented shape."""

    def test_tier_defaults_to_free(self):
        """Omitting tier must not crash — defaults to 'free'."""
        gate = TierGate()
        assert gate.check_tier(agent_name="scout", model="claude-sonnet") is True

    def test_return_type_is_bool_not_truthy(self):
        """Must return a real ``bool`` — truthy ``1`` / ``'yes'`` would break
        callers that assert ``is True``."""
        gate = TierGate()
        result = gate.check_tier(agent_name="x", model="y", tier="z")
        assert isinstance(result, bool)
        assert result is True

    def test_instance_is_stateless_enough_to_reuse(self):
        """Two calls on the same instance yield the same result — no hidden state."""
        gate = TierGate()
        first = gate.check_tier(agent_name="s", model="m", tier="free")
        second = gate.check_tier(agent_name="s", model="m", tier="free")
        assert first is True and second is True


# ---------------------------------------------------------------------------
# Resilience — no crashes on odd inputs
# ---------------------------------------------------------------------------


class TestCheckTierResilience:
    """The gate must NOT crash for the inputs a stressed dispatcher may emit."""

    def test_no_crash_on_long_agent_name(self):
        gate = TierGate()
        very_long = "agent-" + "x" * 10_000
        assert gate.check_tier(agent_name=very_long, model="m", tier="free") is True

    def test_no_crash_on_whitespace_inputs(self):
        gate = TierGate()
        assert gate.check_tier(agent_name="  \t\n", model="  ", tier="  ") is True

    def test_no_crash_on_unicode_inputs(self):
        gate = TierGate()
        assert gate.check_tier(agent_name="スカウト", model="モデル", tier="自由") is True
