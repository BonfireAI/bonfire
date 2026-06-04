# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract tests for the shared timeout resolver (``bonfire.timeouts``)."""

from __future__ import annotations

import pytest

from bonfire.timeouts import (
    DEFAULT_RETRIEVE_TIMEOUT_S,
    DEFAULT_TIMEOUTS,
    RETRIEVE_TIMEOUT_ENV,
    resolve_timeout,
    retrieve_timeout,
)


def test_default_timeouts_values() -> None:
    """The default table carries the expected per-kind values."""
    assert DEFAULT_TIMEOUTS == {
        "version": 5.0,
        "capability": 2.0,
        "git": 5.0,
        "pytest": 300.0,
        "retrieve": 30.0,
        "dispatch": None,
    }


def test_default_retrieve_alias_matches_table() -> None:
    """``DEFAULT_RETRIEVE_TIMEOUT_S`` mirrors the ``retrieve`` default."""
    assert DEFAULT_RETRIEVE_TIMEOUT_S == DEFAULT_TIMEOUTS["retrieve"]
    assert RETRIEVE_TIMEOUT_ENV == "BONFIRE_RETRIEVE_TIMEOUT_S"


def test_resolve_timeout_default() -> None:
    """With no override/env, the default for the kind is returned."""
    assert resolve_timeout("version") == 5.0
    assert resolve_timeout("capability") == 2.0
    assert resolve_timeout("git") == 5.0
    assert resolve_timeout("dispatch") is None


def test_resolve_timeout_override_beats_default() -> None:
    """An explicit override wins over the default table value."""
    assert resolve_timeout("version", override=99.0) == 99.0


def test_resolve_timeout_override_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit override wins even when the env var is set."""
    monkeypatch.setenv("BONFIRE_VERSION_TIMEOUT_S", "12.0")
    assert resolve_timeout("version", override=99.0, env_var="BONFIRE_VERSION_TIMEOUT_S") == 99.0


def test_resolve_timeout_env_beats_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A set env var (float-coerced) wins over the default table value."""
    monkeypatch.setenv("BONFIRE_GIT_TIMEOUT_S", "7.5")
    assert resolve_timeout("git", env_var="BONFIRE_GIT_TIMEOUT_S") == 7.5


def test_resolve_timeout_env_unset_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env_var name that is not set falls back to the default value."""
    monkeypatch.delenv("BONFIRE_GIT_TIMEOUT_S", raising=False)
    assert resolve_timeout("git", env_var="BONFIRE_GIT_TIMEOUT_S") == 5.0


def test_resolve_timeout_env_float_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """An integer-looking env value is coerced to ``float``."""
    monkeypatch.setenv("BONFIRE_GIT_TIMEOUT_S", "9")
    resolved = resolve_timeout("git", env_var="BONFIRE_GIT_TIMEOUT_S")
    assert resolved == 9.0
    assert isinstance(resolved, float)


def test_resolve_timeout_unknown_kind_raises_keyerror() -> None:
    """An unknown kind with no override/env raises ``KeyError``."""
    with pytest.raises(KeyError):
        resolve_timeout("nonexistent")


def test_resolve_timeout_unknown_kind_with_override_returns_override() -> None:
    """An override short-circuits the unknown-kind lookup (no ``KeyError``)."""
    assert resolve_timeout("nonexistent", override=3.0) == 3.0


def test_resolve_timeout_unknown_kind_with_env_returns_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A set env var short-circuits the unknown-kind lookup (no ``KeyError``)."""
    monkeypatch.setenv("BONFIRE_MYSTERY_TIMEOUT_S", "4.0")
    assert resolve_timeout("nonexistent", env_var="BONFIRE_MYSTERY_TIMEOUT_S") == 4.0


def test_retrieve_timeout_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``retrieve_timeout()`` honors the retrieval env override."""
    monkeypatch.setenv(RETRIEVE_TIMEOUT_ENV, "45.0")
    assert retrieve_timeout() == 45.0


def test_retrieve_timeout_default_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """``retrieve_timeout()`` falls back to the default when env is unset."""
    monkeypatch.delenv(RETRIEVE_TIMEOUT_ENV, raising=False)
    assert retrieve_timeout() == DEFAULT_RETRIEVE_TIMEOUT_S
    assert retrieve_timeout() == 30.0
