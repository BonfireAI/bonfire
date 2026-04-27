"""CONTRACT-LOCKED — BON-350 — RED tests for ``resolve_model_for_role``.

Sage §D8 file 3 / 4 — locks the public resolver primitive at
``bonfire.agent.tiers.resolve_model_for_role``:

  * §D7 — Signature: ``resolve_model_for_role(role: str, settings: BonfireSettings) -> str``.
    Pure synchronous function. Never raises on string input.
  * §D7 fallback chain — canonical ``AgentRole`` first, then
    ``GAMIFIED_TO_GENERIC`` alias, then ``ModelTier.BALANCED`` graceful default.
  * §D7 — Whitespace + case normalization (``strip().lower()``).
  * §D7 — Honors user ``[models]`` overrides via ``settings.models``.
  * §D7 — Returns ``getattr(settings.models, tier.value)`` byte-for-byte
    (BYOK passthrough).
  * §D2 — Resolver re-exported from both ``bonfire.agent.tiers`` and
    ``bonfire.agent``.

Drift-guards (determinism, purity, no-dispatch-import via AST) extend the
floor with adversarial coverage citing §D7 lines 419-420 / 442-444 and
§D-CL.5 verbatim.

These tests are RED until BON-350 Warrior GREEN ships ``tiers.py`` AND
the ``ModelsConfig`` field on ``BonfireSettings``.
"""

from __future__ import annotations

import ast
from pathlib import Path


# ---------------------------------------------------------------------------
# Import surface
# ---------------------------------------------------------------------------


class TestResolverImports:
    """``resolve_model_for_role`` is importable from module + package."""

    def test_resolver_imports_from_module(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role

        assert callable(resolve_model_for_role)

    def test_resolver_imports_from_package(self) -> None:
        from bonfire.agent import resolve_model_for_role

        assert callable(resolve_model_for_role)


# ---------------------------------------------------------------------------
# Canonical AgentRole inputs — direct lookup path (§D7 step 2)
# ---------------------------------------------------------------------------


class TestResolverCanonicalRoles:
    """Canonical role strings resolve to the default-mapped tier."""

    def test_researcher_returns_reasoning_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("researcher", s) == s.models.reasoning

    def test_tester_returns_fast_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("tester", s) == s.models.fast

    def test_implementer_returns_fast_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("implementer", s) == s.models.fast

    def test_reviewer_returns_reasoning_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("reviewer", s) == s.models.reasoning

    def test_synthesizer_returns_reasoning_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("synthesizer", s) == s.models.reasoning


# ---------------------------------------------------------------------------
# Gamified alias inputs — alias-table lookup path (§D7 step 3)
# ---------------------------------------------------------------------------


class TestResolverGamifiedAliases:
    """Gamified workflow strings resolve via ``GAMIFIED_TO_GENERIC``."""

    def test_warrior_returns_fast_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("warrior", s) == s.models.fast

    def test_scout_returns_reasoning_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("scout", s) == s.models.reasoning

    def test_sage_returns_reasoning_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("sage", s) == s.models.reasoning

    def test_wizard_returns_reasoning_default(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("wizard", s) == s.models.reasoning

    def test_prover_returns_fast_default(self) -> None:
        """``prover`` is a workflow alias for ``verifier`` (§D-CL.1)."""
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("prover", s) == s.models.fast


# ---------------------------------------------------------------------------
# Normalization — strip + lower (§D7 step 1)
# ---------------------------------------------------------------------------


class TestResolverNormalization:
    """Whitespace + case normalization happen before any lookup."""

    def test_uppercase_warrior_normalizes(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("WARRIOR", s) == s.models.fast

    def test_whitespace_warrior_normalizes(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("  warrior  ", s) == s.models.fast

    def test_mixed_case_scout_normalizes(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("ScOuT", s) == s.models.reasoning


# ---------------------------------------------------------------------------
# Fallback — unknown / empty / weird inputs return BALANCED (§D7 step 4)
# ---------------------------------------------------------------------------


class TestResolverFallback:
    """Unknown roles fall back to ``ModelTier.BALANCED`` without raising."""

    def test_unknown_role_returns_balanced(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("alien", s) == s.models.balanced

    def test_empty_string_returns_balanced(self) -> None:
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("", s) == s.models.balanced

    def test_random_unicode_returns_balanced(self) -> None:
        """Non-ASCII / unicode garbage falls through to balanced (no raise)."""
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        assert resolve_model_for_role("dragão-mágico", s) == s.models.balanced


# ---------------------------------------------------------------------------
# Honors user [models] overrides — verbatim BYOK passthrough (§D7 step 6)
# ---------------------------------------------------------------------------


class TestResolverHonorsModelsOverride:
    """User-configured ``[models]`` strings flow through verbatim."""

    def test_custom_models_section_returned(self) -> None:
        """A fully-overridden ``ModelsConfig`` flows through the resolver."""
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings, ModelsConfig

        s = BonfireSettings(
            models=ModelsConfig(
                reasoning="custom-opus",
                fast="custom-haiku",
                balanced="custom-sonnet",
            )
        )
        assert resolve_model_for_role("researcher", s) == "custom-opus"
        assert resolve_model_for_role("tester", s) == "custom-haiku"
        assert resolve_model_for_role("alien", s) == "custom-sonnet"

    def test_partial_override_only_changes_one_tier(self) -> None:
        """Overriding only ``reasoning`` leaves ``fast`` / ``balanced`` defaults."""
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings, ModelsConfig

        s = BonfireSettings(models=ModelsConfig(reasoning="custom-opus"))
        assert resolve_model_for_role("researcher", s) == "custom-opus"
        assert resolve_model_for_role("tester", s) == "claude-haiku-4-5"
        assert resolve_model_for_role("alien", s) == "claude-sonnet-4-6"

    def test_byok_string_returned_verbatim(self) -> None:
        """Arbitrary BYOK strings (non-Anthropic) flow through unmodified."""
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings, ModelsConfig

        s = BonfireSettings(
            models=ModelsConfig(
                reasoning="gpt-5",
                fast="haiku-mini",
                balanced="custom/v3",
            )
        )
        assert resolve_model_for_role("reviewer", s) == "gpt-5"
        assert resolve_model_for_role("warrior", s) == "haiku-mini"
        assert resolve_model_for_role("unknown-role", s) == "custom/v3"

    def test_resolver_does_not_raise_on_any_str(self) -> None:
        """Any string input — known, unknown, weird — returns a string."""
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        for candidate in [
            "researcher",
            "WARRIOR",
            "  scout  ",
            "",
            "alien",
            "🔥",
            "1234",
            "knight\nwith\nnewlines",
        ]:
            result = resolve_model_for_role(candidate, s)
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Drift-guards — determinism, purity, AST no-dispatch-import (CONTRACT-LOCKED)
# ---------------------------------------------------------------------------


class TestResolverDeterminism:
    """Same input -> same output across N calls (Sage §D7 'pure').

    Guards against: a future caching/memoization implementation that
    introduces hidden mutable state. Sage §D7 lines 419-420 lock the
    resolver as 'no I/O, no cache' -- determinism over 10 calls is
    the cheapest invariant that breaks if anyone reaches for ``functools.lru_cache``
    on a settings-bearing arg (lru_cache + Pydantic = silent identity bugs).
    """

    def test_same_input_yields_same_output_across_ten_calls(self):
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings

        s = BonfireSettings()
        results = [resolve_model_for_role("warrior", s) for _ in range(10)]
        assert len(set(results)) == 1, f"Non-deterministic resolver output: {results}"


class TestResolverPurity:
    """Calling resolver does not mutate settings (Sage §D7 'pure').

    Cites Sage §D7 lines 442-444 ('side-effect-free'). Guards against:
    a refactor that does ``settings.models.reasoning = ...`` somewhere
    in the resolution path (e.g. lazy-default normalization). The
    invariant is read-only access through ``getattr``.
    """

    def test_resolver_does_not_mutate_settings(self):
        from bonfire.agent.tiers import resolve_model_for_role
        from bonfire.models.config import BonfireSettings, ModelsConfig

        s = BonfireSettings(
            models=ModelsConfig(
                reasoning="custom-reasoning",
                fast="custom-fast",
                balanced="custom-balanced",
            )
        )
        before_reasoning = s.models.reasoning
        before_fast = s.models.fast
        before_balanced = s.models.balanced

        # Call across all three tier outcomes plus fallback.
        resolve_model_for_role("researcher", s)
        resolve_model_for_role("warrior", s)
        resolve_model_for_role("alien", s)

        assert s.models.reasoning == before_reasoning
        assert s.models.fast == before_fast
        assert s.models.balanced == before_balanced


class TestResolverPurityNoDispatchImport:
    """Sage §D-CL.5 purity test via AST inspection.

    Cites Sage §D-CL.5 verbatim ('use AST inspection, not sys.modules').
    Guards against: a Warrior accidentally importing from
    ``bonfire.dispatch`` or ``bonfire.engine`` inside ``tiers.py``,
    breaking the leaf-primitive layering (BON-348 §D2).
    """

    def test_tiers_module_does_not_import_from_dispatch_or_engine(self):
        # Locate the source file via the package.
        import bonfire.agent.tiers as tiers_module

        source_path = Path(tiers_module.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        forbidden_prefixes = ("bonfire.dispatch", "bonfire.engine")
        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                for prefix in forbidden_prefixes:
                    if node.module == prefix or node.module.startswith(prefix + "."):
                        violations.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        if alias.name == prefix or alias.name.startswith(prefix + "."):
                            violations.append(alias.name)

        assert violations == [], (
            "bonfire.agent.tiers must not import from bonfire.dispatch / "
            f"bonfire.engine (BON-348 layering); violations: {violations}"
        )
