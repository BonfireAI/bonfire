"""Phase-1 contract tests for the shared timeout resolver (ADR-002).

These tests are RED until the Warrior adds ``src/bonfire/timeouts.py`` and
refactors ``bonfire.mcp.retrieval_server`` and ``bonfire.prompt.precompose`` to
delegate their ``DEFAULT_RETRIEVE_TIMEOUT_S`` / ``_retrieve_timeout`` to the
shared resolver.

Collection-safety: ``bonfire.timeouts`` does not exist yet, so the import is
guarded with a module-level ``try/except ImportError`` (matching the idiom in
``tests/unit/test_errors.py``). When the module is absent, the symbols are set
to ``None`` and a module-level skip flag is raised so collection succeeds and
each test fails (or skips) cleanly rather than erroring at import time.
"""

import pytest

try:
    from bonfire.timeouts import DEFAULT_TIMEOUTS, resolve_timeout

    _IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover - RED phase only
    DEFAULT_TIMEOUTS = None  # type: ignore[assignment]
    resolve_timeout = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

# Skip-on-missing so collection succeeds while the module is absent, but the
# absence is still surfaced loudly (xfail-strict-style) by failing the import
# guard test below. The skip keeps the rest of the file from erroring.
_requires_timeouts = pytest.mark.skipif(
    _IMPORT_ERROR is not None,
    reason=f"bonfire.timeouts not importable yet: {_IMPORT_ERROR}",
)

_RETRIEVE_ENV = "BONFIRE_RETRIEVE_TIMEOUT_S"


def test_timeouts_module_importable():
    """RED: bonfire.timeouts does not exist yet -> this assertion fails."""
    assert _IMPORT_ERROR is None, (
        "bonfire.timeouts must be importable with DEFAULT_TIMEOUTS + "
        f"resolve_timeout; got: {_IMPORT_ERROR}"
    )


# --- defaults table -------------------------------------------------------


@_requires_timeouts
def test_default_timeouts_table_values():
    assert DEFAULT_TIMEOUTS["version"] == 5.0
    assert DEFAULT_TIMEOUTS["capability"] == 2.0
    assert DEFAULT_TIMEOUTS["git"] == 5.0
    assert DEFAULT_TIMEOUTS["pytest"] == 300.0
    assert DEFAULT_TIMEOUTS["retrieve"] == 30.0
    assert DEFAULT_TIMEOUTS["dispatch"] is None


# --- default path (no override, no env_var) -------------------------------


@_requires_timeouts
def test_resolve_default_path_retrieve(monkeypatch):
    monkeypatch.delenv(_RETRIEVE_ENV, raising=False)
    assert resolve_timeout("retrieve") == 30.0


@_requires_timeouts
def test_resolve_default_path_dispatch_is_none(monkeypatch):
    monkeypatch.delenv(_RETRIEVE_ENV, raising=False)
    assert resolve_timeout("dispatch") is None


# --- env override + float coercion ----------------------------------------


@_requires_timeouts
def test_resolve_env_override_and_float_coercion(monkeypatch):
    monkeypatch.setenv(_RETRIEVE_ENV, "5")
    result = resolve_timeout("retrieve", env_var=_RETRIEVE_ENV)
    assert result == 5.0
    assert isinstance(result, float)


# --- env ignored when env_var not passed ----------------------------------


@_requires_timeouts
def test_resolve_env_ignored_without_env_var_arg(monkeypatch):
    monkeypatch.setenv(_RETRIEVE_ENV, "5")
    # No env_var arg -> env must NOT be consulted; falls back to default.
    assert resolve_timeout("retrieve") == 30.0


# --- override wins over env and default -----------------------------------


@_requires_timeouts
def test_resolve_override_wins_over_env_and_default(monkeypatch):
    monkeypatch.setenv(_RETRIEVE_ENV, "5")
    assert resolve_timeout("retrieve", override=1.5, env_var=_RETRIEVE_ENV) == 1.5


# --- override is keyword-only ---------------------------------------------


@_requires_timeouts
def test_override_is_keyword_only():
    with pytest.raises(TypeError):
        resolve_timeout("retrieve", 1.5)  # type: ignore[misc]


# --- unknown kind ---------------------------------------------------------


@_requires_timeouts
def test_unknown_kind_raises_keyerror(monkeypatch):
    monkeypatch.delenv(_RETRIEVE_ENV, raising=False)
    with pytest.raises(KeyError):
        resolve_timeout("nope")


@_requires_timeouts
def test_unknown_kind_resolvable_via_override():
    assert resolve_timeout("nope", override=2.0) == 2.0


# --- delegation cross-check (behavior-preserving dedup guard) --------------


@_requires_timeouts
def test_retrieval_server_delegates_to_shared_resolver(monkeypatch):
    from bonfire.mcp import retrieval_server

    monkeypatch.delenv(_RETRIEVE_ENV, raising=False)
    assert retrieval_server.DEFAULT_RETRIEVE_TIMEOUT_S == DEFAULT_TIMEOUTS["retrieve"]
    assert retrieval_server._retrieve_timeout() == resolve_timeout("retrieve")


@_requires_timeouts
def test_precompose_delegates_to_shared_resolver(monkeypatch):
    from bonfire.prompt import precompose

    monkeypatch.delenv(_RETRIEVE_ENV, raising=False)
    assert precompose.DEFAULT_RETRIEVE_TIMEOUT_S == DEFAULT_TIMEOUTS["retrieve"]
    assert precompose._retrieve_timeout() == resolve_timeout("retrieve")
