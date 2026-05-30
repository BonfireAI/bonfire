# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for the ``bonfire.errors`` taxonomy — Phase 0 (ADR-002).

The failure-architecture epic introduces a single base exception,
``BonfireError``, and a taxonomy of subclasses that pin two cross-cutting
contracts the runner depends on:

- ``is_terminal`` (ClassVar) — whether a failure is non-recoverable. The
  derived ``retryable`` property is simply ``not is_terminal``.
- ``code`` (ClassVar) — a stable wire-string. The terminal subset of codes
  must equal ``runner.py``'s ``_TERMINAL_ERROR_TYPES`` so Phase 3 can source
  the set from the taxonomy instead of duplicating it.

Two pre-existing custom exceptions are *reparented* onto the new base without
moving them or changing their constructors:

- ``PathGuardError`` (in ``git/path_guard.py``) becomes an ``IsolationError``.
  It keeps its ``(message, violations)`` ctor and ``.violations`` attribute and
  its ``bonfire.git`` re-export — see ``test_git.py`` for the back-compat
  contract those tests already pin.
- ``PersonaSchemaError`` (in ``persona/loader.py``) becomes
  ``PersonaSchemaError(SchemaError, ValueError)``. It keeps its single-positional
  ctor and stays catchable as ``ValueError`` — see
  ``test_persona_toml_schema.py`` for the ``ValueError`` lineage those tests
  already pin.

Finally, ``ErrorDetail`` (in ``models/envelope.py``) grows a
``from_exception`` classmethod so failed envelopes get structured error info.

The ``bonfire.errors`` imports are wrapped in ``try/except ImportError`` so
pytest can collect this file while the module does not yet exist — matching the
deferred-import idiom in ``test_git.py``. Each test re-imports the name it uses
so RED output is per-test rather than a single collection error.
"""

from __future__ import annotations

import pytest

# Deferred import shim — collection-safe while src/bonfire/errors.py is absent.
# Each test re-imports the name(s) it uses so RED output is per-test.
try:
    from bonfire.errors import (
        AgentError,
        BonfireError,
        CLINotFoundError,
        ConfigError,
        ExecutorError,
        IsolationError,
        NetworkError,
        RateLimitError,
        RetrievalError,
        SchemaError,
        SubprocessError,
        TimeoutError_,
        ValidationError,
    )
except ImportError:  # pragma: no cover - expected RED before Warrior builds src
    pass


# ---------------------------------------------------------------------------
# Convenience groupings (module-level so parametrize can reference them).
# Guarded so collection does not fail before bonfire.errors exists.
# ---------------------------------------------------------------------------

try:
    _TERMINAL_CLASSES = [
        ConfigError,
        AgentError,
        RateLimitError,
        CLINotFoundError,
        ExecutorError,
    ]
    _OPERATIONAL_CLASSES = [
        RetrievalError,
        SubprocessError,
        TimeoutError_,
        NetworkError,
    ]
    _DATA_CLASSES = [ValidationError, SchemaError, IsolationError]
    _ALL_TAXONOMY = _TERMINAL_CLASSES + _OPERATIONAL_CLASSES + _DATA_CLASSES
except NameError:  # pragma: no cover - expected RED before Warrior builds src
    _TERMINAL_CLASSES = []
    _OPERATIONAL_CLASSES = []
    _DATA_CLASSES = []
    _ALL_TAXONOMY = []


# ===========================================================================
# BonfireError — base contract
# ===========================================================================


class TestBonfireErrorBase:
    """BonfireError is the taxonomy root: message, context, retryability."""

    def test_message_is_str(self) -> None:
        assert str(BonfireError("boom")) == "boom"

    def test_default_context_is_empty_dict(self) -> None:
        assert BonfireError("x").context == {}

    def test_context_kwarg_preserved(self) -> None:
        assert BonfireError("x", context={"k": 1}).context == {"k": 1}

    def test_context_is_keyword_only(self) -> None:
        """``context`` is keyword-only — a second positional must not bind it."""
        with pytest.raises(TypeError):
            BonfireError("x", {"k": 1})  # type: ignore[misc]

    def test_base_is_not_terminal(self) -> None:
        assert BonfireError.is_terminal is False

    def test_base_is_retryable(self) -> None:
        assert BonfireError("x").retryable is True

    def test_default_code(self) -> None:
        assert BonfireError.code == "bonfire_error"

    def test_is_exception_subclass(self) -> None:
        assert issubclass(BonfireError, Exception)


# ===========================================================================
# Taxonomy membership
# ===========================================================================


class TestTaxonomyMembership:
    """Every taxonomy class is a BonfireError subclass."""

    @pytest.mark.parametrize("cls", _ALL_TAXONOMY)
    def test_subclasses_bonfire_error(self, cls: type) -> None:
        assert issubclass(cls, BonfireError)


# ===========================================================================
# Terminal vs operational flags
# ===========================================================================


class TestTerminalFlags:
    """Terminal classes are non-retryable; operational classes are retryable."""

    @pytest.mark.parametrize("cls", _TERMINAL_CLASSES)
    def test_terminal_is_terminal_true(self, cls: type) -> None:
        assert cls.is_terminal is True

    @pytest.mark.parametrize("cls", _TERMINAL_CLASSES)
    def test_terminal_not_retryable(self, cls: type) -> None:
        # retryable is an instance property; construct a minimal instance.
        assert cls("x").retryable is False

    @pytest.mark.parametrize("cls", _OPERATIONAL_CLASSES)
    def test_operational_is_terminal_false(self, cls: type) -> None:
        assert cls.is_terminal is False

    @pytest.mark.parametrize("cls", _OPERATIONAL_CLASSES)
    def test_operational_retryable(self, cls: type) -> None:
        assert cls("x").retryable is True


# ===========================================================================
# Codes locked — forward-compat with runner._TERMINAL_ERROR_TYPES (Phase 3)
# ===========================================================================


class TestCodesLocked:
    """The terminal code set must equal runner.py's _TERMINAL_ERROR_TYPES.

    Phase 3 sources the terminal set from the taxonomy, so this exact set is
    a forward-compat contract — not cosmetic.
    """

    def test_terminal_code_set_locked(self) -> None:
        codes = {
            ConfigError.code,
            AgentError.code,
            RateLimitError.code,
            CLINotFoundError.code,
            ExecutorError.code,
        }
        assert codes == {
            "config",
            "AgentError",
            "RateLimitError",
            "CLINotFoundError",
            "executor",
        }

    def test_config_code(self) -> None:
        assert ConfigError.code == "config"

    def test_executor_code(self) -> None:
        assert ExecutorError.code == "executor"


# ===========================================================================
# SchemaError lineage
# ===========================================================================


class TestSchemaErrorLineage:
    """SchemaError is a ValidationError, which is a BonfireError."""

    def test_schema_is_validation_error(self) -> None:
        assert issubclass(SchemaError, ValidationError)

    def test_schema_is_bonfire_error(self) -> None:
        assert issubclass(SchemaError, BonfireError)


# ===========================================================================
# PathGuardError reparent (defined in git/path_guard.py, unchanged ctor)
# ===========================================================================


class TestPathGuardErrorReparent:
    """PathGuardError becomes an IsolationError without losing its shape."""

    def test_is_isolation_error(self) -> None:
        from bonfire.errors import IsolationError
        from bonfire.git.path_guard import PathGuardError

        assert issubclass(PathGuardError, IsolationError)

    def test_is_bonfire_error(self) -> None:
        from bonfire.errors import BonfireError as _BonfireError
        from bonfire.git.path_guard import PathGuardError

        assert issubclass(PathGuardError, _BonfireError)

    def test_ctor_unchanged_message_and_violations(self) -> None:
        """The ``(message, violations)`` ctor and ``.violations`` survive."""
        from bonfire.git.path_guard import PathGuardError

        err = PathGuardError("blocked", [])
        assert err.violations == []
        assert str(err) == "blocked"


# ===========================================================================
# PersonaSchemaError reparent (defined in persona/loader.py, unchanged ctor)
# ===========================================================================


class TestPersonaSchemaErrorReparent:
    """PersonaSchemaError gains the BonfireError base, keeps ValueError."""

    def test_is_bonfire_error(self) -> None:
        from bonfire.errors import BonfireError as _BonfireError
        from bonfire.persona import PersonaSchemaError

        assert issubclass(PersonaSchemaError, _BonfireError)

    def test_is_value_error(self) -> None:
        from bonfire.persona import PersonaSchemaError

        assert issubclass(PersonaSchemaError, ValueError)

    def test_is_schema_error(self) -> None:
        from bonfire.errors import SchemaError as _SchemaError
        from bonfire.persona import PersonaSchemaError

        assert issubclass(PersonaSchemaError, _SchemaError)

    def test_single_positional_ctor(self) -> None:
        from bonfire.persona import PersonaSchemaError

        assert str(PersonaSchemaError("bad")) == "bad"

    def test_catchable_as_value_error(self) -> None:
        from bonfire.persona import PersonaSchemaError

        with pytest.raises(ValueError):
            raise PersonaSchemaError("bad")

    def test_catchable_as_bonfire_error(self) -> None:
        from bonfire.errors import BonfireError as _BonfireError
        from bonfire.persona import PersonaSchemaError

        with pytest.raises(_BonfireError):
            raise PersonaSchemaError("bad")


# ===========================================================================
# ErrorDetail.from_exception classmethod
# ===========================================================================


class TestErrorDetailFromException:
    """ErrorDetail.from_exception captures type, message, traceback, stage."""

    def test_captures_type_message_and_traceback(self) -> None:
        from bonfire.models.envelope import ErrorDetail

        try:
            raise ValueError("nope")
        except ValueError as exc:
            detail = ErrorDetail.from_exception(exc)
        assert detail.error_type == "ValueError"
        assert detail.message == "nope"
        assert isinstance(detail.traceback, str)
        assert detail.traceback != ""
        assert "ValueError" in detail.traceback

    def test_stage_name_passthrough(self) -> None:
        from bonfire.models.envelope import ErrorDetail

        try:
            raise ValueError("nope")
        except ValueError as exc:
            detail = ErrorDetail.from_exception(exc, stage_name="s")
        assert detail.stage_name == "s"

    def test_stage_name_defaults_none(self) -> None:
        from bonfire.models.envelope import ErrorDetail

        try:
            raise ValueError("nope")
        except ValueError as exc:
            detail = ErrorDetail.from_exception(exc)
        assert detail.stage_name is None
