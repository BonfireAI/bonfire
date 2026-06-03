"""RED tests for BON-1407 §Defect-2 — runner retry/terminal classification is TYPE-SOURCED.

Phase 3 of the failure-architecture epic replaces the runner's hand-maintained
``_TERMINAL_ERROR_TYPES`` string-set membership check
(``src/bonfire/dispatch/runner.py:38-46`` and the ``if error_type in
_TERMINAL_ERROR_TYPES`` classification at ``:133``) with a read of the typed
failure vocabulary — ``BonfireError.is_terminal`` / ``.retryable``
(``src/bonfire/errors.py:27-90``).

This is a **behavior-preserving** refactor. The observable retry/terminal
outcomes MUST stay byte-identical: the string-set and the typed taxonomy
currently agree exactly on which codes are terminal
(``{config, AgentError, RateLimitError, CLINotFoundError, executor}``), so the
regression suite below pins that observable behavior and must remain GREEN
across the change. The point of Phase 3 is that the *source of truth* for the
decision is the one shared vocabulary, not a duplicated frozenset that can
silently drift from the taxonomy.

Two kinds of test live here:

1. **Regression (behavior-preserving).** Drive the runner with FAILED
   envelopes whose ``error_type`` equals each typed error's ``.code`` and
   assert terminal codes do NOT retry while retryable codes DO. The
   *expectations are generated from* ``bonfire.errors`` at collection time, so
   a type-sourced classifier and the test's expectations are guaranteed to
   track the same source of truth. (These pass on current ``main`` too — that
   is the proof the refactor is behavior-preserving.)

2. **Mechanism proof (RED on current ``main``).** A structural read of the
   runner source: the classifier must consult the typed ``.is_terminal`` /
   ``.retryable`` vocabulary and must NOT classify via a duplicated
   ``_TERMINAL_ERROR_TYPES`` string-set membership test. These FAIL on current
   ``main`` because the string-set classification is present and the typed
   read is absent.
"""

from __future__ import annotations

import inspect

import pytest

import bonfire.errors as errors_mod
from bonfire.dispatch.runner import execute_with_retry
from bonfire.errors import BonfireError
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# Taxonomy enumeration — the single source of truth the runner must read
# ---------------------------------------------------------------------------


def _typed_error_classes() -> list[type[BonfireError]]:
    return sorted(
        (
            cls
            for _, cls in inspect.getmembers(errors_mod, inspect.isclass)
            if issubclass(cls, BonfireError) and cls is not BonfireError
        ),
        key=lambda c: c.__name__,
    )


_TERMINAL_CODES = sorted({c.code for c in _typed_error_classes() if c.is_terminal})
_RETRYABLE_CODES = sorted({c.code for c in _typed_error_classes() if not c.is_terminal})


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class ScriptedBackend:
    """Pops pre-configured envelopes; counts calls for cardinality assertions."""

    def __init__(self, responses: list[Envelope]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.call_count += 1
        if not self._responses:
            return envelope.with_error(
                ErrorDetail(error_type="exhausted", message="no more scripted responses")
            )
        return self._responses.pop(0)

    async def health_check(self) -> bool:
        return True


def _envelope() -> Envelope:
    return Envelope(task="t", agent_name="a", model="claude-sonnet")


def _options() -> DispatchOptions:
    return DispatchOptions(model="claude-sonnet", max_budget_usd=1.0)


def _failed(error_type: str) -> Envelope:
    env = _envelope()
    return env.with_error(ErrorDetail(error_type=error_type, message=f"{error_type} failure"))


# ---------------------------------------------------------------------------
# Sanity: the enumeration found a non-trivial taxonomy split
# ---------------------------------------------------------------------------


def test_taxonomy_split_is_nontrivial():
    """Guard the generator — both buckets must be populated or the parametrize is empty."""
    assert _TERMINAL_CODES, "expected at least one terminal BonfireError code"
    assert _RETRYABLE_CODES, "expected at least one retryable BonfireError code"
    # The historically-hardcoded terminal names must all be present in the
    # taxonomy-derived terminal set (the source the runner must now read).
    assert {"config", "AgentError", "RateLimitError", "CLINotFoundError", "executor"} <= set(
        _TERMINAL_CODES
    )


# ---------------------------------------------------------------------------
# Behavior-preserving regression — terminal codes do not retry
# ---------------------------------------------------------------------------


class TestTerminalCodesFromTaxonomyNoRetry:
    """Every terminal BonfireError code (sourced from the taxonomy) → no retry."""

    @pytest.mark.parametrize("code", _TERMINAL_CODES)
    async def test_terminal_code_returns_immediately(self, code: str):
        env = _envelope()
        backend = ScriptedBackend([_failed(code)])
        result = await execute_with_retry(backend, env, _options(), max_retries=5, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 0, f"terminal code {code!r} must not be retried"
        assert backend.call_count == 1, f"terminal code {code!r} must make exactly one call"

    @pytest.mark.parametrize("code", _TERMINAL_CODES)
    async def test_terminal_code_preserves_error_detail(self, code: str):
        env = _envelope()
        backend = ScriptedBackend([_failed(code)])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == code


# ---------------------------------------------------------------------------
# Behavior-preserving regression — retryable codes DO retry
# ---------------------------------------------------------------------------


class TestRetryableCodesFromTaxonomyDoRetry:
    """Every non-terminal BonfireError code (sourced from the taxonomy) → retries."""

    @pytest.mark.parametrize("code", _RETRYABLE_CODES)
    async def test_retryable_code_is_retried_then_succeeds(self, code: str):
        env = _envelope()
        success = env.with_result("ok", cost_usd=0.01)
        backend = ScriptedBackend([_failed(code), success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 1, f"retryable code {code!r} must be retried"
        assert backend.call_count == 2

    @pytest.mark.parametrize("code", _RETRYABLE_CODES)
    async def test_retryable_code_exhausts_to_failed(self, code: str):
        env = _envelope()
        crash = _failed(code)
        backend = ScriptedBackend([crash, crash])
        result = await execute_with_retry(backend, env, _options(), max_retries=1, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 1


# ---------------------------------------------------------------------------
# Behavior-preserving regression — unknown error types default to retryable
# ---------------------------------------------------------------------------


class TestUnknownErrorTypeStaysRetryable:
    """An error_type with no taxonomy entry must default to retryable (safer)."""

    async def test_unknown_error_type_retried(self):
        env = _envelope()
        crash = _failed("SomeExoticErrorNotInTaxonomy")
        success = env.with_result("ok", cost_usd=0.01)
        backend = ScriptedBackend([crash, success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 1


# ---------------------------------------------------------------------------
# Mechanism proof — classification reads the typed vocabulary (RED on main)
# ---------------------------------------------------------------------------


class TestClassificationIsTypeSourced:
    """The runner must classify terminal/retryable via the typed BonfireError
    vocabulary (``is_terminal`` / ``retryable``), not a duplicated string-set.

    These are structural reads of ``runner.py`` source on disk. They FAIL on
    current ``main`` because the classifier is the ``if error_type in
    _TERMINAL_ERROR_TYPES`` string-membership test and the typed read is
    absent. They pass once the decision is sourced from the typed vocabulary.
    """

    def _runner_source(self) -> str:
        import bonfire.dispatch.runner as mod

        path = mod.__file__
        assert path is not None
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_classifier_does_not_use_terminal_string_set_membership(self):
        """No ``error_type in _TERMINAL_ERROR_TYPES`` string-set classification."""
        src = self._runner_source()
        assert "in _TERMINAL_ERROR_TYPES" not in src, (
            "runner still classifies via the _TERMINAL_ERROR_TYPES string-set "
            "membership test — Phase 3 sources terminality from the typed "
            "BonfireError vocabulary (.is_terminal / .retryable)"
        )

    def test_classifier_reads_typed_terminality(self):
        """The classifier reads ``.is_terminal`` or ``.retryable`` from a typed error."""
        src = self._runner_source()
        assert (".is_terminal" in src) or (".retryable" in src), (
            "runner classification must read the typed failure vocabulary "
            "(BonfireError.is_terminal / .retryable) — neither attribute is "
            "referenced in runner.py"
        )

    def test_runner_imports_the_failure_vocabulary(self):
        """The runner must depend on ``bonfire.errors`` to source terminality."""
        src = self._runner_source()
        assert "bonfire.errors" in src, (
            "runner must import from bonfire.errors to source terminal/retryable "
            "classification from the typed vocabulary"
        )
