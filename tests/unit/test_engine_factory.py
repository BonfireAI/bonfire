"""RED contract tests for ``bonfire.engine.factory``.

Knight A unit-lens output for the cluster-351 D-FT bundle. The Sage
architectural memo at
``docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md`` §C.2
and §G locks the factory signature; §H.2 locks this test contract (four
tests). Module under test does not yet exist — Warriors implement it
during the GREEN phase.

Factory contract (Sage §C.2):

    def load_settings_or_default() -> BonfireSettings:
        '''Build a BonfireSettings instance for a pipeline run.

        Reads bonfire.toml from cwd and BONFIRE_* env vars per
        pydantic-settings source priority. On a *load* failure
        (malformed TOML, env-var coercion error, validator failure),
        emits a stderr warning and falls back to a defaults-only
        BonfireSettings via model_construct (bypasses validation;
        safe for the alpha).

        NEVER raises. Catches (ValidationError, TOMLDecodeError, OSError).
        '''

These tests are wrapped in ``@pytest.mark.xfail`` markers so the suite is
RED-friendly until the Warrior writes the factory.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from bonfire.models.config import BonfireSettings

# ---------------------------------------------------------------------------
# Helper — strip BONFIRE_* env vars so tests are deterministic
# ---------------------------------------------------------------------------


def _scrub_bonfire_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``BONFIRE_*`` env var so the factory sees a clean env."""
    import os

    for key in list(os.environ):
        if key.startswith("BONFIRE_"):
            monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Test 1 — clean env happy path (Sage §H.2.1, mission §1)
# ---------------------------------------------------------------------------


def test_load_settings_clean_env_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Clean env + no bonfire.toml -> full BonfireSettings, no warning.

    Per Sage memo §C.2: "On the happy path (no bonfire.toml, no
    BONFIRE_* env vars) it returns a fresh ``BonfireSettings()``
    exactly as before."
    """
    _scrub_bonfire_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    caplog.set_level(logging.WARNING, logger="bonfire.engine.factory")

    from bonfire.engine.factory import load_settings_or_default

    settings = load_settings_or_default()

    assert isinstance(settings, BonfireSettings)
    # Default fields populated from BonfireSettings model defaults
    assert settings.models.reasoning != ""
    assert settings.models.fast != ""
    assert settings.models.balanced != ""
    # Clean path -> no warning
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records == [], (
        f"clean env happy path emitted warnings: {[r.getMessage() for r in warning_records]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — malformed TOML warns + returns defaults (Sage §H.2.2, mission §2)
# ---------------------------------------------------------------------------


def test_load_settings_malformed_toml_warns_and_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed bonfire.toml -> warning + ``model_construct`` defaults.

    Per Sage memo §C.2: "On a *load* failure (malformed TOML, env-var
    coercion error, validator failure), emits a stderr warning and
    falls back to a defaults-only ``BonfireSettings`` via
    ``model_construct``." Per §E: "wrap+warn at the three constructor
    fallback sites."
    """
    _scrub_bonfire_env(monkeypatch)
    bad_toml = tmp_path / "bonfire.toml"
    bad_toml.write_text("this is { not valid toml = =\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    caplog.set_level(logging.WARNING, logger="bonfire.engine.factory")

    from bonfire.engine.factory import load_settings_or_default

    settings = load_settings_or_default()

    assert isinstance(settings, BonfireSettings), (
        "factory must NEVER raise — must return a BonfireSettings even on "
        "TOML decode failure (Sage §C.2)"
    )
    # Default-bearing instance from model_construct
    assert hasattr(settings, "models")

    # A WARNING-level record was emitted by the factory's logger
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Failed to load BonfireSettings" in msg for msg in warning_messages), (
        "factory must emit a 'Failed to load BonfireSettings' warning on "
        f"malformed TOML (Sage §C.2). got: {warning_messages!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — invalid env var warns + returns defaults (Sage §H.2.3, mission §3)
# ---------------------------------------------------------------------------


def test_load_settings_invalid_env_var_warns_and_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid BONFIRE_* env var -> warning + defaults; no raise.

    Per Sage memo §C.2 caught-types pin: ``ValidationError``.
    A negative ``max_budget_usd`` triggers ``PipelineConfig`` validator
    (config.py:48-54); the factory must catch and warn.
    """
    _scrub_bonfire_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    # The env-nested-delimiter is "__" (config.py:153). Negative budget
    # triggers PipelineConfig._budget_non_negative validator.
    monkeypatch.setenv("BONFIRE_BONFIRE__MAX_BUDGET_USD", "-1")

    caplog.set_level(logging.WARNING, logger="bonfire.engine.factory")

    from bonfire.engine.factory import load_settings_or_default

    settings = load_settings_or_default()

    assert isinstance(settings, BonfireSettings), (
        "factory must NEVER raise — must return a BonfireSettings even on "
        "ValidationError from env coercion (Sage §C.2)"
    )

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Failed to load BonfireSettings" in msg for msg in warning_messages), (
        "factory must emit a 'Failed to load BonfireSettings' warning on "
        f"invalid env var (Sage §C.2). got: {warning_messages!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — never raises, parametrized over three failure modes
#          (Sage §H.2.4, mission §4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc_factory,label",
    [
        (lambda: RuntimeError("toml decode boom"), "toml-decode"),
        (lambda: ValueError("validation boom"), "validation-error"),
        (lambda: OSError("io boom"), "os-error"),
    ],
)
def test_load_settings_never_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc_factory,  # type: ignore[no-untyped-def]
    label: str,
) -> None:
    """Factory MUST always return a BonfireSettings, never propagate.

    Per Sage memo §C.2: "NEVER raises. Catches ``(ValidationError,
    TOMLDecodeError, OSError)``." This test exercises the never-raise
    contract by patching ``BonfireSettings.__init__`` to raise each
    of the three exception families.

    Parametrized over the three failure modes named in the contract.
    """
    _scrub_bonfire_env(monkeypatch)

    def _boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise exc_factory()

    monkeypatch.setattr(BonfireSettings, "__init__", _boom)
    caplog.set_level(logging.WARNING, logger="bonfire.engine.factory")

    from bonfire.engine.factory import load_settings_or_default

    # MUST NOT raise
    settings = load_settings_or_default()

    assert isinstance(settings, BonfireSettings), (
        f"factory propagated {label} instead of falling back to "
        "model_construct (Sage §C.2 never-raise contract)"
    )

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_messages, (
        f"factory must warn when falling back on {label} (Sage §E loud-fail-soft doctrine)"
    )
