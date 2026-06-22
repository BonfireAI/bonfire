# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""BON-1757 — narrowed-except contract for ``load_settings_or_default``.

The factory previously caught a broad ``except Exception`` with a
``# noqa: BLE001`` blessing. BON-1757 narrows that to the EXACT set of
load-failure types empirically observed when ``BonfireSettings()`` reads
``bonfire.toml`` / ``BONFIRE_*`` env vars:

    (pydantic.ValidationError, tomllib.TOMLDecodeError, OSError)

Empirical basis (pydantic-settings ``TomlConfigSettingsSource``):
  * malformed TOML -> ``tomllib.load`` raises ``tomllib.TOMLDecodeError``
    directly (the source does NOT wrap it);
  * an invalid field value -> ``pydantic.ValidationError``;
  * an unreadable file -> ``OSError``;
  * a missing file is skipped (no exception).

These tests pin the in-set catch (real failure conditions) AND that an
out-of-set exception now propagates rather than being silently swallowed
— the whole point of the narrowing.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from bonfire.models.config import BonfireSettings


def _scrub_bonfire_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``BONFIRE_*`` env var so the factory sees a clean env."""
    import os

    for key in list(os.environ):
        if key.startswith("BONFIRE_"):
            monkeypatch.delenv(key, raising=False)


def test_malformed_toml_is_tomldecodeerror_and_caught(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed TOML raises ``TOMLDecodeError``; the narrowed except catches it.

    Asserts the EMPIRICAL precondition (the real exception class) and the
    warn-and-return-defaults outcome in one test.
    """
    _scrub_bonfire_env(monkeypatch)
    (tmp_path / "bonfire.toml").write_text("nope = = =\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Empirical: constructing directly raises the concrete narrowed type.
    with pytest.raises(tomllib.TOMLDecodeError):
        BonfireSettings()

    caplog.set_level(logging.WARNING, logger="bonfire.engine.factory")
    from bonfire.engine.factory import load_settings_or_default

    settings = load_settings_or_default()

    assert isinstance(settings, BonfireSettings)
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Failed to load BonfireSettings" in m for m in msgs)


def test_invalid_value_is_validationerror_and_caught(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An invalid field value raises ``ValidationError``; the narrowed except catches it."""
    _scrub_bonfire_env(monkeypatch)
    # Negative budget trips PipelineConfig._budget_non_negative on load.
    (tmp_path / "bonfire.toml").write_text("[bonfire]\nmax_budget_usd = -1.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Empirical: constructing directly raises the concrete narrowed type.
    with pytest.raises(ValidationError):
        BonfireSettings()

    caplog.set_level(logging.WARNING, logger="bonfire.engine.factory")
    from bonfire.engine.factory import load_settings_or_default

    settings = load_settings_or_default()

    assert isinstance(settings, BonfireSettings)
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Failed to load BonfireSettings" in m for m in msgs)


def test_out_of_set_exception_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-load exception (e.g. ``RuntimeError``) is NOT swallowed any more.

    This is the load-bearing assertion for the narrowing: the broad
    ``except Exception`` would have hidden this; the narrowed tuple must
    let it through so genuine bugs surface.
    """
    _scrub_bonfire_env(monkeypatch)

    def _boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("unexpected boom")

    monkeypatch.setattr(BonfireSettings, "__init__", _boom)
    from bonfire.engine.factory import load_settings_or_default

    with pytest.raises(RuntimeError, match="unexpected boom"):
        load_settings_or_default()
