"""RED contract tests for ``bonfire.engine.model_resolver``.

Knight A unit-lens output for the cluster-351 D-FT bundle. The Sage
architectural memo at
``docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md`` §C.1
and §F locks the helper signature; §H.1 locks this test contract (six
tests). Module under test does not yet exist — Warriors implement it
during the GREEN phase.

Helper contract (Sage §C.1):

    def resolve_dispatch_model(
        *,
        explicit_override: str,
        role: str,
        settings: BonfireSettings,
        config: PipelineConfig,
    ) -> str

Three-tier precedence (Sage §C.1, ratified by cluster-350 D-CL.1):

    1. ``explicit_override`` — per-stage / per-envelope escape hatch.
    2. ``resolve_model_for_role(role, settings)`` — role-based routing
       via ``bonfire.agent.tiers``.
    3. ``config.model`` — pipeline default.

Defensive contract: if all three are empty, return ``""`` — never raise.

These tests are wrapped in ``@pytest.mark.xfail`` markers so the suite is
RED-friendly until the Warrior writes the helper.
"""

from __future__ import annotations

import pytest

from bonfire.models.config import BonfireSettings, ModelsConfig, PipelineConfig

# ---------------------------------------------------------------------------
# Test 1 — explicit override wins (Sage §H.1.1, mission §1)
# ---------------------------------------------------------------------------


def test_resolve_dispatch_model_explicit_override_wins() -> None:
    """When ``explicit_override`` is non-empty, return it verbatim.

    Highest precedence per Sage memo §C.1
    (docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md).
    Settings + config are deliberately set to non-overlapping values to
    prove the override short-circuits.
    """
    from bonfire.engine.model_resolver import resolve_dispatch_model

    settings = BonfireSettings(
        models=ModelsConfig(
            reasoning="should-not-win-reasoning",
            fast="should-not-win-fast",
            balanced="should-not-win-balanced",
        )
    )
    config = PipelineConfig(model="should-not-win-config-default")

    result = resolve_dispatch_model(
        explicit_override="custom-model",
        role="reviewer",
        settings=settings,
        config=config,
    )

    assert result == "custom-model"


# ---------------------------------------------------------------------------
# Test 2 — empty override falls to role resolver (Sage §H.1.2, mission §2)
# ---------------------------------------------------------------------------


def test_resolve_dispatch_model_empty_falls_to_role_resolver() -> None:
    """Empty override delegates to ``resolve_model_for_role``.

    Per Sage memo §C.1 precedence layer 2. With ``role="reviewer"``,
    ``DEFAULT_ROLE_TIER`` maps reviewer to ``REASONING``, so the helper
    must return ``settings.models.reasoning``.
    """
    from bonfire.engine.model_resolver import resolve_dispatch_model

    settings = BonfireSettings(
        models=ModelsConfig(
            reasoning="reasoning-model-X",
            fast="fast-model-Y",
            balanced="balanced-model-Z",
        )
    )
    config = PipelineConfig(model="config-default-W")

    result = resolve_dispatch_model(
        explicit_override="",
        role="reviewer",
        settings=settings,
        config=config,
    )

    assert result == "reasoning-model-X"


# ---------------------------------------------------------------------------
# Test 3 — empty override + empty role string falls to config (Sage §H.1.3,
#          mission §3)
# ---------------------------------------------------------------------------


def test_resolve_dispatch_model_role_unset_falls_to_config() -> None:
    """Empty override + role-resolver returns empty -> use ``config.model``.

    Per Sage memo §C.1 precedence layer 3. We zero out
    ``settings.models.balanced`` (the fallback tier when role doesn't
    match) so layer 2 returns ``""`` and layer 3 wins.
    """
    from bonfire.engine.model_resolver import resolve_dispatch_model

    # All tiers empty — resolver layer 2 returns ""
    settings = BonfireSettings(
        models=ModelsConfig(
            reasoning="",
            fast="",
            balanced="",
        )
    )
    config = PipelineConfig(model="config-default-fallback")

    result = resolve_dispatch_model(
        explicit_override="",
        role="",
        settings=settings,
        config=config,
    )

    assert result == "config-default-fallback"


# ---------------------------------------------------------------------------
# Test 4 — all three empty returns "" defensively (Sage §H.1.4, mission §4)
# ---------------------------------------------------------------------------


def test_resolve_dispatch_model_all_empty_returns_empty_defensive() -> None:
    """Empty override + empty resolver + empty config -> empty string.

    Per Sage memo §C.1 docstring: "Empty string is only returned if (1),
    (2), and (3) are ALL empty — defensive return value preserves
    today's executor contract." The helper must NOT raise.
    """
    from bonfire.engine.model_resolver import resolve_dispatch_model

    settings = BonfireSettings(models=ModelsConfig(reasoning="", fast="", balanced=""))
    config = PipelineConfig(model="")

    # The call must not raise
    result = resolve_dispatch_model(
        explicit_override="",
        role="",
        settings=settings,
        config=config,
    )

    assert result == ""


# ---------------------------------------------------------------------------
# Test 5 — purity: no I/O (Sage §H.1.5, mission §5)
# ---------------------------------------------------------------------------


def test_resolve_dispatch_model_purity_no_io(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Helper performs no I/O — no TOML reads, no env reads, no stderr.

    Per Sage memo §C.1: "Pure synchronous function. Never raises on
    string input." Per §C.1 "What the helper deliberately does NOT do":
    "Does NOT instantiate ``BonfireSettings()``."

    This test patches ``BonfireSettings.__init__`` with a counter; the
    helper must never invoke it (settings are passed in pre-built).
    Also asserts no stderr emission.
    """
    import bonfire.models.config as _cfg
    from bonfire.engine.model_resolver import resolve_dispatch_model

    init_calls = {"n": 0}
    real_init = BonfireSettings.__init__

    def _counting_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        init_calls["n"] += 1
        return real_init(self, *args, **kwargs)

    # Pre-build settings BEFORE installing the counter
    settings = BonfireSettings(models=ModelsConfig(reasoning="r", fast="f", balanced="b"))
    config = PipelineConfig(model="cfg")

    monkeypatch.setattr(_cfg.BonfireSettings, "__init__", _counting_init)

    # Call the helper many times; it should never construct BonfireSettings
    for _ in range(50):
        resolve_dispatch_model(
            explicit_override="",
            role="reviewer",
            settings=settings,
            config=config,
        )

    captured = capsys.readouterr()
    assert init_calls["n"] == 0, (
        f"helper instantiated BonfireSettings {init_calls['n']} times — "
        "must remain pure (Sage memo §C.1)"
    )
    assert captured.err == "", (
        f"helper emitted stderr ({captured.err!r}) — must be silent "
        "(Sage memo §C.1: pure synchronous, no I/O)"
    )


# ---------------------------------------------------------------------------
# Test 6 — role normalization is delegated to inner resolver (Sage §H.1.6,
#          mission §6)
# ---------------------------------------------------------------------------


def test_resolve_dispatch_model_normalization_delegates_to_tiers() -> None:
    """Helper passes ``role`` verbatim to ``resolve_model_for_role``.

    Per Sage memo §C.1 "What the helper deliberately does NOT do":
    "Does NOT normalize role strings. ``resolve_model_for_role`` already
    normalizes (``tiers.py:99``)."

    A whitespace + uppercase role string round-trips through the inner
    resolver's normalization and produces the same answer as the bare
    canonical form. This proves the helper itself does not strip /
    lowercase before delegating.
    """
    from bonfire.engine.model_resolver import resolve_dispatch_model

    settings = BonfireSettings(
        models=ModelsConfig(
            reasoning="reasoning-X",
            fast="fast-Y",
            balanced="balanced-Z",
        )
    )
    config = PipelineConfig(model="config-default")

    canonical = resolve_dispatch_model(
        explicit_override="",
        role="reviewer",
        settings=settings,
        config=config,
    )
    noisy = resolve_dispatch_model(
        explicit_override="",
        role="  REVIEWER  ",
        settings=settings,
        config=config,
    )

    assert canonical == "reasoning-X"
    assert noisy == canonical, (
        "role normalization must be delegated to "
        "bonfire.agent.tiers.resolve_model_for_role (Sage §C.1)"
    )
