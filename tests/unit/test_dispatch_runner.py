"""RED tests for ``bonfire.dispatch.runner`` — W3.2 execute_with_retry.

Canonical Sage synthesis of Knight-A (resilience) + Knight-B (fidelity).

The dispatch runner sits between the pipeline engine and agent backends.
It wraps every ``backend.execute()`` call with:

* Retry with exponential backoff for infrastructure AND transient agent
  failures.
* Per-attempt timeout enforcement via ``asyncio.timeout``.
* Wall-clock duration and cost tracking across all attempts.
* Event emission (started, completed, failed, retry) through an optional bus.

Contract locked by this suite (Warrior hands this back GREEN):

* ``execute_with_retry(backend, envelope, options, *, max_retries=3,
  retry_delay=1.0, timeout_seconds=None, event_bus=None) -> DispatchResult``.
* ``DispatchResult(envelope, duration_seconds, retries, cost_usd)`` — frozen.
* Terminal error ``error_type`` set (no retry):
  ``{"AgentError", "RateLimitError", "config", "CLINotFoundError", "executor"}``.
* Backoff formula: deterministic ``retry_delay * (2 ** attempt_index)``.
  No jitter.
* ``retries`` counts retries, not total attempts. First-attempt success =
  ``retries == 0``; two retries then success = ``retries == 2``; total
  exhaustion with ``max_retries=3`` = ``retries == 3``.
* Cost accumulates across every attempt whose envelope was received
  (terminal + success + retryable-failure all carry cost).
* Exception-only exhaustion: final envelope carries
  ``ErrorDetail(error_type='infrastructure', message=str(exc))``.
* ``event_bus=None`` is the documented default — never crashes.
* Session id on every emitted event equals ``envelope.envelope_id``.

Public v0.1 surface — per-file import shim per ``tests/unit/test_envelope.py``.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from bonfire.events.bus import EventBus
from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus
from bonfire.models.events import (
    BonfireEvent,
    DispatchCompleted,
    DispatchFailed,
    DispatchRetry,
    DispatchStarted,
)
from bonfire.protocols import DispatchOptions

try:
    from bonfire.dispatch import DispatchResult as _PackageDispatchResult
    from bonfire.dispatch import execute_with_retry as _package_execute_with_retry
    from bonfire.dispatch.result import DispatchResult
    from bonfire.dispatch.runner import execute_with_retry
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    DispatchResult = None  # type: ignore[assignment,misc]
    execute_with_retry = None  # type: ignore[assignment]
    _PackageDispatchResult = None  # type: ignore[assignment,misc]
    _package_execute_with_retry = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test while ``bonfire.dispatch.runner`` is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.runner not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class ScriptedBackend:
    """Fake ``AgentBackend`` that returns pre-configured responses.

    Pass a list of ``Envelope`` or ``Exception`` objects. Each call to
    ``execute()`` pops the next response. If the response is an
    ``Exception``, it is raised (simulating infrastructure failure). If
    it is an ``Envelope``, it is returned.

    ``health_check()`` always returns ``True``. ``call_count`` tracks
    cardinality for attempt-count assertions.
    """

    def __init__(self, responses: list[Envelope | Exception]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        self.call_count += 1
        if not self._responses:
            return envelope.with_error(
                ErrorDetail(error_type="exhausted", message="no more scripted responses")
            )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def health_check(self) -> bool:
        return True


class SlowBackend:
    """Fake ``AgentBackend`` that sleeps for ``delay`` seconds before returning."""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
        await asyncio.sleep(self._delay)
        return envelope.with_result("slow done", cost_usd=0.01)

    async def health_check(self) -> bool:
        return True


class EventCapture:
    """Collects emitted events for ordering / cardinality assertions."""

    def __init__(self) -> None:
        self.events: list[BonfireEvent] = []

    async def handler(self, event: BonfireEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: type) -> list[BonfireEvent]:
        return [e for e in self.events if type(e) is event_type]


def _envelope(
    task: str = "test task", agent_name: str = "test-agent", model: str = "claude-sonnet"
) -> Envelope:
    return Envelope(task=task, agent_name=agent_name, model=model)


def _options(model: str = "claude-sonnet", max_budget_usd: float = 1.0) -> DispatchOptions:
    return DispatchOptions(model=model, max_budget_usd=max_budget_usd)


def _bus_with_capture(*event_types: type) -> tuple[EventBus, EventCapture]:
    bus = EventBus()
    capture = EventCapture()
    for et in event_types:
        bus.subscribe(et, capture.handler)
    return bus, capture


# ---------------------------------------------------------------------------
# Imports — canonical paths AND package re-exports
# ---------------------------------------------------------------------------


class TestImports:
    """``DispatchResult`` and ``execute_with_retry`` resolve from both paths."""

    def test_import_execute_with_retry_from_runner_module(self):
        from bonfire.dispatch.runner import execute_with_retry as _fn

        assert _fn is not None

    def test_import_execute_with_retry_from_dispatch_package(self):
        """Package re-export must surface ``execute_with_retry``."""
        from bonfire.dispatch import execute_with_retry as _fn

        assert _fn is not None

    def test_package_reexport_is_same_callable(self):
        """Re-exports must be the same objects as the canonical ones."""
        assert _package_execute_with_retry is execute_with_retry
        assert _PackageDispatchResult is DispatchResult

    def test_dispatch_all_contains_expected_symbols(self):
        """``bonfire.dispatch.__all__`` lists the transferred surface."""
        import bonfire.dispatch as mod

        exported = set(mod.__all__)
        assert {"DispatchResult", "TierGate", "execute_with_retry"} <= exported


# ---------------------------------------------------------------------------
# Return-type contract — never raises
# ---------------------------------------------------------------------------


class TestReturnsDispatchResult:
    """execute_with_retry always returns DispatchResult — never raises."""

    async def test_success_returns_dispatch_result(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert isinstance(result, DispatchResult)

    async def test_failure_returns_dispatch_result(self):
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("infra")])
        result = await execute_with_retry(backend, env, _options(), max_retries=0, retry_delay=0.0)
        assert isinstance(result, DispatchResult)

    async def test_never_raises_on_unexpected_exception(self):
        """A pathological exception that is neither timeout nor connection
        error still becomes a FAILED DispatchResult — the runner MUST NOT
        let it escape."""
        env = _envelope()

        class WeirdError(Exception):
            pass

        backend = ScriptedBackend([WeirdError("unknown category")])
        result = await execute_with_retry(backend, env, _options(), max_retries=0, retry_delay=0.0)
        assert isinstance(result, DispatchResult)
        assert result.envelope.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """First-attempt success — no retry, cost from envelope, status COMPLETED."""

    async def test_status_is_completed(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("done", cost_usd=0.05)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.envelope.result == "done"

    async def test_retries_zero_on_first_success(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("done", cost_usd=0.05)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.retries == 0

    async def test_call_count_is_one_on_first_success(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("done", cost_usd=0.05)])
        await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert backend.call_count == 1

    async def test_cost_from_envelope(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("done", cost_usd=0.42)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.cost_usd == pytest.approx(0.42)

    async def test_duration_non_negative(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("done", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# Attempt cardinality — fence-post hunter
# ---------------------------------------------------------------------------


class TestAttemptCardinality:
    """The #1 brittle invariant: exactly ``max_retries + 1`` total calls."""

    async def test_zero_retries_makes_one_call(self):
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("boom")])
        await execute_with_retry(backend, env, _options(), max_retries=0, retry_delay=0.0)
        assert backend.call_count == 1

    async def test_one_retry_makes_two_calls_on_exhaustion(self):
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("1"), RuntimeError("2")])
        await execute_with_retry(backend, env, _options(), max_retries=1, retry_delay=0.0)
        assert backend.call_count == 2

    async def test_three_retries_makes_four_calls_on_exhaustion(self):
        env = _envelope()
        backend = ScriptedBackend(
            [RuntimeError("1"), RuntimeError("2"), RuntimeError("3"), RuntimeError("4")]
        )
        await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert backend.call_count == 4

    async def test_recovery_on_last_attempt_no_extra_call(self):
        """Success on attempt N must not trigger attempt N+1."""
        env = _envelope()
        backend = ScriptedBackend(
            [
                RuntimeError("1"),
                RuntimeError("2"),
                env.with_result("ok", cost_usd=0.01),
            ]
        )
        await execute_with_retry(backend, env, _options(), max_retries=5, retry_delay=0.0)
        assert backend.call_count == 3


# ---------------------------------------------------------------------------
# Retry on raw exception
# ---------------------------------------------------------------------------


class TestRetryOnException:
    """Arbitrary exceptions trigger retry up to max_retries."""

    async def test_runtime_error_retried(self):
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("net"), env.with_result("ok", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 1

    async def test_connection_error_retried(self):
        env = _envelope()
        backend = ScriptedBackend([ConnectionError(), env.with_result("ok", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED

    async def test_multiple_exceptions_retried(self):
        env = _envelope()
        backend = ScriptedBackend(
            [
                ConnectionError("network"),
                TimeoutError("slow"),
                env.with_result("ok", cost_usd=0.01),
            ]
        )
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 2

    async def test_exhausted_exceptions_become_failed_envelope(self):
        env = _envelope()
        backend = ScriptedBackend(
            [RuntimeError("a"), RuntimeError("b"), RuntimeError("c"), RuntimeError("d")]
        )
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 3


# ---------------------------------------------------------------------------
# Exception-path error_type preservation
# ---------------------------------------------------------------------------


class TestExceptionPathErrorTypePreservation:
    """When retries exhaust via the exception path, the final envelope's
    ``error.error_type`` MUST equal the raised exception's class name
    (``exc.__class__.__name__``), not the literal string ``"infrastructure"``.

    Downstream observability consumers read ``envelope.error.error_type`` to
    discriminate failure modes — a network timeout, a connection drop, a
    backend bug, and a value error are different failure shapes that must
    not collapse into a single opaque label. Keeping the exception class
    name preserves the discrimination at zero added cost.

    The boundary test locks the FAILED-path early-return is unchanged: a
    backend that *returns* a FAILED envelope (rather than *raising*) with
    a rich ``error_type`` keeps that rich type all the way through retry
    exhaustion via the early-return at the FAILED-path branch.
    """

    async def test_timeout_error_class_name_preserved(self):
        """``TimeoutError`` raised on every attempt → error_type='TimeoutError'."""
        env = _envelope()
        backend = ScriptedBackend(
            [TimeoutError("attempt 1"), TimeoutError("attempt 2"), TimeoutError("attempt 3")]
        )
        result = await execute_with_retry(backend, env, _options(), max_retries=2, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 2
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "TimeoutError"
        assert "attempt 3" in result.envelope.error.message

    async def test_connection_error_class_name_preserved(self):
        """``ConnectionError`` raised on every attempt → error_type='ConnectionError'."""
        env = _envelope()
        backend = ScriptedBackend(
            [
                ConnectionError("dropped 1"),
                ConnectionError("dropped 2"),
                ConnectionError("dropped 3"),
            ]
        )
        result = await execute_with_retry(backend, env, _options(), max_retries=2, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 2
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "ConnectionError"
        assert "dropped 3" in result.envelope.error.message

    async def test_runtime_error_class_name_preserved(self):
        """``RuntimeError`` raised on every attempt → error_type='RuntimeError'."""
        env = _envelope()
        backend = ScriptedBackend(
            [RuntimeError("boom 1"), RuntimeError("boom 2"), RuntimeError("boom 3")]
        )
        result = await execute_with_retry(backend, env, _options(), max_retries=2, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 2
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "RuntimeError"
        assert "boom 3" in result.envelope.error.message

    async def test_value_error_class_name_preserved(self):
        """``ValueError`` raised on every attempt → error_type='ValueError'."""
        env = _envelope()
        backend = ScriptedBackend([ValueError("bad 1"), ValueError("bad 2"), ValueError("bad 3")])
        result = await execute_with_retry(backend, env, _options(), max_retries=2, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 2
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "ValueError"
        assert "bad 3" in result.envelope.error.message

    async def test_failed_envelope_path_preserves_rich_error_type(self):
        """Boundary: a backend that RETURNS a FAILED envelope with a rich
        error_type (e.g. ``"auth_denied"``) keeps that error_type through
        retry exhaustion. The FAILED-path early-return path is unchanged
        by the exception-path fix — this test pins that invariant.
        """
        env = _envelope()
        failed = env.with_error(
            ErrorDetail(error_type="auth_denied", message="bearer token rejected")
        )
        # Three identical FAILED responses — non-terminal so they get retried,
        # then exhausted on the third attempt with max_retries=2.
        backend = ScriptedBackend([failed, failed, failed])
        result = await execute_with_retry(backend, env, _options(), max_retries=2, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 2
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "auth_denied"
        assert result.envelope.error.message == "bearer token rejected"


# ---------------------------------------------------------------------------
# Terminal errors — no retry
# ---------------------------------------------------------------------------


class TestTerminalErrors:
    """AgentError / RateLimitError / config / CLINotFoundError / executor
    must NOT be retried — they are deterministic, not transient."""

    @pytest.mark.parametrize(
        "error_type",
        ["AgentError", "RateLimitError", "config", "CLINotFoundError", "executor"],
    )
    async def test_terminal_error_no_retry(self, error_type: str):
        env = _envelope()
        failed = env.with_error(ErrorDetail(error_type=error_type, message=f"{error_type} msg"))
        backend = ScriptedBackend([failed])
        result = await execute_with_retry(backend, env, _options(), max_retries=5, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 0
        assert backend.call_count == 1

    async def test_terminal_error_preserves_error_detail(self):
        env = _envelope()
        err = ErrorDetail(error_type="RateLimitError", message="exceeded")
        failed = env.with_error(err)
        backend = ScriptedBackend([failed])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "RateLimitError"
        assert result.envelope.error.message == "exceeded"

    async def test_terminal_error_emits_only_one_failed_event(self):
        """One DispatchStarted, zero DispatchRetry, one DispatchFailed."""
        bus, capture = _bus_with_capture(DispatchStarted, DispatchRetry, DispatchFailed)

        env = _envelope(agent_name="scout")
        failed = env.with_error(ErrorDetail(error_type="AgentError", message="refused"))
        backend = ScriptedBackend([failed])
        await execute_with_retry(
            backend, env, _options(), max_retries=5, event_bus=bus, retry_delay=0.0
        )

        assert len(capture.of_type(DispatchStarted)) == 1
        assert len(capture.of_type(DispatchRetry)) == 0
        assert len(capture.of_type(DispatchFailed)) == 1


# ---------------------------------------------------------------------------
# Retryable FAILED envelopes (non-terminal error types)
# ---------------------------------------------------------------------------


class TestRetryableFailedEnvelope:
    """FAILED envelopes with non-terminal error types ARE retried."""

    async def test_subprocess_crash_retried_then_succeeds(self):
        env = _envelope()
        crash = env.with_error(ErrorDetail(error_type="ProcessError", message="exit 1"))
        success = env.with_result("ok", cost_usd=0.05)
        backend = ScriptedBackend([crash, success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 1
        assert backend.call_count == 2

    async def test_unknown_error_type_retried(self):
        """Unknown error types default to retryable (safer than false-terminal)."""
        env = _envelope()
        crash = env.with_error(ErrorDetail(error_type="NewExoticError", message="who knows"))
        success = env.with_result("ok", cost_usd=0.01)
        backend = ScriptedBackend([crash, success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 1

    async def test_retryable_failure_exhaust_preserves_last_error(self):
        env = _envelope()
        crash = env.with_error(ErrorDetail(error_type="ProcessError", message="died"))
        backend = ScriptedBackend([crash, crash])
        result = await execute_with_retry(backend, env, _options(), max_retries=1, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "ProcessError"
        assert "died" in result.envelope.error.message


# ---------------------------------------------------------------------------
# Cost accumulation across retries
# ---------------------------------------------------------------------------


class TestCostAccumulation:
    """Cost from every attempt whose envelope is received must accrue."""

    async def test_cost_accumulates_from_failed_to_success(self):
        env = _envelope()
        crash = env.with_error(ErrorDetail(error_type="ProcessError", message="crash")).model_copy(
            update={"cost_usd": 0.10}
        )
        success = env.with_result("ok", cost_usd=0.05)
        backend = ScriptedBackend([crash, success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.cost_usd == pytest.approx(0.15)

    async def test_cost_accumulates_across_multiple_retries(self):
        env = _envelope()
        crash_a = env.with_error(ErrorDetail(error_type="ProcessError", message="a")).model_copy(
            update={"cost_usd": 0.07}
        )
        crash_b = env.with_error(ErrorDetail(error_type="ProcessError", message="b")).model_copy(
            update={"cost_usd": 0.03}
        )
        success = env.with_result("ok", cost_usd=0.05)
        backend = ScriptedBackend([crash_a, crash_b, success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.cost_usd == pytest.approx(0.15)

    async def test_cost_zero_when_all_attempts_raise(self):
        """Exceptions before backend.execute() returns — no envelope cost."""
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("1"), RuntimeError("2")])
        result = await execute_with_retry(backend, env, _options(), max_retries=1, retry_delay=0.0)
        assert result.cost_usd == 0.0


# ---------------------------------------------------------------------------
# Exponential backoff — deterministic, no jitter
# ---------------------------------------------------------------------------


class TestExponentialBackoff:
    """Delay doubles each retry: ``retry_delay * 2 ** attempt_index``. No jitter."""

    async def test_total_delay_lower_bound(self):
        """With retry_delay=0.05 and 3 retries: >= 0.05 + 0.10 + 0.20 = 0.35s."""
        env = _envelope()
        backend = ScriptedBackend(
            [
                RuntimeError("1"),
                RuntimeError("2"),
                RuntimeError("3"),
                env.with_result("ok", cost_usd=0.01),
            ]
        )
        start = time.monotonic()
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.05)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.30
        assert result.envelope.status == TaskStatus.COMPLETED

    async def test_zero_retry_delay_does_not_sleep(self):
        """``retry_delay=0.0`` short-circuits the backoff — suite runs fast."""
        env = _envelope()
        backend = ScriptedBackend(
            [RuntimeError("1"), RuntimeError("2"), env.with_result("ok", cost_usd=0.01)]
        )
        start = time.monotonic()
        await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    async def test_no_sleep_before_first_attempt(self):
        """First attempt must fire immediately — backoff applies AFTER failure."""
        env = _envelope()
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.01)])
        start = time.monotonic()
        await execute_with_retry(backend, env, _options(), retry_delay=1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    async def test_no_sleep_after_final_failed_attempt(self):
        """After max_retries exhausted, don't sleep before returning — wasted burn."""
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("1"), RuntimeError("2")])
        start = time.monotonic()
        await execute_with_retry(backend, env, _options(), max_retries=1, retry_delay=0.05)
        elapsed = time.monotonic() - start
        # Expected delay: exactly one backoff of 0.05s before the 2nd attempt.
        # If an extra sleep happened after the final attempt, elapsed >= ~0.10.
        assert elapsed < 0.2


# ---------------------------------------------------------------------------
# Per-attempt timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    """``timeout_seconds`` wraps each individual attempt, not the total."""

    async def test_slow_backend_times_out_and_retries(self):
        """All attempts time out — returns FAILED result, never raises."""
        env = _envelope()
        backend = SlowBackend(delay=5.0)  # Way too slow.
        result = await execute_with_retry(
            backend,
            env,
            _options(),
            max_retries=1,
            retry_delay=0.0,
            timeout_seconds=0.05,
        )
        assert result.envelope.status == TaskStatus.FAILED

    async def test_timeout_then_success_recovers(self):
        env = _envelope()
        backend = ScriptedBackend([TimeoutError(), env.with_result("fast", cost_usd=0.01)])
        result = await execute_with_retry(
            backend,
            env,
            _options(),
            max_retries=3,
            retry_delay=0.0,
            timeout_seconds=0.1,
        )
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 1

    async def test_no_timeout_never_raises_timeout(self):
        """``timeout_seconds=None`` → no per-attempt timeout enforced."""
        env = _envelope()
        backend = SlowBackend(delay=0.02)  # Tiny delay.
        result = await execute_with_retry(
            backend, env, _options(), max_retries=0, retry_delay=0.0, timeout_seconds=None
        )
        assert result.envelope.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Duration tracking across retries
# ---------------------------------------------------------------------------


class TestDurationTracking:
    """Duration covers the wall-clock time of all attempts combined."""

    async def test_duration_includes_retry_time(self):
        env = _envelope()
        success = env.with_result("ok", cost_usd=0.01)
        backend = ScriptedBackend([RuntimeError("fail"), success])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.05)
        # At least the backoff delay should be reflected in duration.
        assert result.duration_seconds >= 0.04


# ---------------------------------------------------------------------------
# Event emission — cardinality + ordering
# ---------------------------------------------------------------------------


class TestEventEmission:
    """The runner's event surface is the sole observability handle.

    Cardinality and ordering must be exact — drift means consumers log the
    wrong thing, or worse, double-count costs.
    """

    async def test_success_emits_started_and_completed_exactly_once(self):
        bus, capture = _bus_with_capture(
            DispatchStarted, DispatchRetry, DispatchFailed, DispatchCompleted
        )
        env = _envelope(agent_name="scout")
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.10)])
        await execute_with_retry(
            backend, env, _options(model="claude-sonnet"), event_bus=bus, retry_delay=0.0
        )

        assert len(capture.of_type(DispatchStarted)) == 1
        assert len(capture.of_type(DispatchRetry)) == 0
        assert len(capture.of_type(DispatchFailed)) == 0
        assert len(capture.of_type(DispatchCompleted)) == 1

    async def test_failure_emits_started_and_failed_exactly_once(self):
        bus, capture = _bus_with_capture(
            DispatchStarted, DispatchRetry, DispatchFailed, DispatchCompleted
        )
        env = _envelope(agent_name="warrior")
        backend = ScriptedBackend([RuntimeError("infra"), RuntimeError("infra")])
        await execute_with_retry(
            backend, env, _options(), max_retries=1, event_bus=bus, retry_delay=0.0
        )

        assert len(capture.of_type(DispatchStarted)) == 1
        assert len(capture.of_type(DispatchCompleted)) == 0
        assert len(capture.of_type(DispatchFailed)) == 1

    async def test_retry_event_count_matches_retries_field(self):
        """N retries → exactly N DispatchRetry events."""
        bus, capture = _bus_with_capture(DispatchRetry)
        env = _envelope()
        backend = ScriptedBackend(
            [RuntimeError("1"), RuntimeError("2"), env.with_result("ok", cost_usd=0.01)]
        )
        result = await execute_with_retry(
            backend, env, _options(), max_retries=3, event_bus=bus, retry_delay=0.0
        )
        retry_events = capture.of_type(DispatchRetry)
        assert len(retry_events) == result.retries == 2

    async def test_retry_attempt_numbers_are_one_indexed_and_monotonic(self):
        bus, capture = _bus_with_capture(DispatchRetry)
        env = _envelope()
        backend = ScriptedBackend(
            [
                RuntimeError("1"),
                RuntimeError("2"),
                RuntimeError("3"),
                env.with_result("ok", cost_usd=0.01),
            ]
        )
        await execute_with_retry(
            backend, env, _options(), max_retries=3, event_bus=bus, retry_delay=0.0
        )
        retry_events = capture.of_type(DispatchRetry)
        assert [e.attempt for e in retry_events] == [1, 2, 3]  # type: ignore[attr-defined]

    async def test_retry_event_carries_reason(self):
        """``DispatchRetry.reason`` must include the error that triggered the retry."""
        bus, capture = _bus_with_capture(DispatchRetry)
        env = _envelope(agent_name="sage-1")
        backend = ScriptedBackend(
            [
                RuntimeError("fail-1"),
                ConnectionError("fail-2"),
                env.with_result("ok", cost_usd=0.01),
            ]
        )
        await execute_with_retry(
            backend, env, _options(), max_retries=3, event_bus=bus, retry_delay=0.0
        )
        retry_events = capture.of_type(DispatchRetry)
        assert len(retry_events) == 2
        assert "fail-1" in retry_events[0].reason  # type: ignore[attr-defined]
        assert "fail-2" in retry_events[1].reason  # type: ignore[attr-defined]

    async def test_retry_event_emitted_for_retryable_failed_envelope(self):
        """``DispatchRetry`` fires when a retryable FAILED envelope triggers retry,
        and the reason includes the envelope's error_type."""
        bus, capture = _bus_with_capture(DispatchRetry)
        env = _envelope(agent_name="scout-crash")
        crash = env.with_error(ErrorDetail(error_type="CLIConnectionError", message="pipe broken"))
        success = env.with_result("ok", cost_usd=0.01)
        backend = ScriptedBackend([crash, success])
        await execute_with_retry(
            backend, env, _options(), max_retries=3, event_bus=bus, retry_delay=0.0
        )
        retry_events = capture.of_type(DispatchRetry)
        assert len(retry_events) == 1
        assert retry_events[0].agent_name == "scout-crash"  # type: ignore[attr-defined]
        assert "CLIConnectionError" in retry_events[0].reason  # type: ignore[attr-defined]

    async def test_started_event_carries_agent_and_model(self):
        bus, capture = _bus_with_capture(DispatchStarted)
        env = _envelope(agent_name="knight")
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.01)])
        await execute_with_retry(
            backend, env, _options(model="claude-opus-4"), event_bus=bus, retry_delay=0.0
        )
        started = capture.of_type(DispatchStarted)
        assert len(started) == 1
        assert started[0].agent_name == "knight"  # type: ignore[attr-defined]
        assert started[0].model == "claude-opus-4"  # type: ignore[attr-defined]

    async def test_completed_event_carries_cost_and_duration(self):
        bus, capture = _bus_with_capture(DispatchCompleted)
        env = _envelope(agent_name="sage")
        backend = ScriptedBackend([env.with_result("done", cost_usd=0.25)])
        await execute_with_retry(backend, env, _options(), event_bus=bus, retry_delay=0.0)
        completed = capture.of_type(DispatchCompleted)
        assert len(completed) == 1
        assert completed[0].cost_usd == pytest.approx(0.25)  # type: ignore[attr-defined]
        assert completed[0].duration_seconds >= 0.0  # type: ignore[attr-defined]

    async def test_failed_event_carries_error_message(self):
        bus, capture = _bus_with_capture(DispatchFailed)
        env = _envelope(agent_name="bard")
        backend = ScriptedBackend([RuntimeError("catastrophic")])
        await execute_with_retry(
            backend, env, _options(), max_retries=0, event_bus=bus, retry_delay=0.0
        )
        failed = capture.of_type(DispatchFailed)
        assert len(failed) == 1
        assert "catastrophic" in failed[0].error_message  # type: ignore[attr-defined]

    async def test_session_id_equals_envelope_id(self):
        """Events must tag themselves with the ENVELOPE id, not a fresh id,
        so external consumers can correlate across the full session."""
        bus, capture = _bus_with_capture(DispatchStarted, DispatchCompleted)
        env = _envelope()
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.01)])
        await execute_with_retry(backend, env, _options(), event_bus=bus, retry_delay=0.0)
        for event in capture.events:
            assert event.session_id == env.envelope_id

    # -- BON-351 D4 -- DispatchCompleted carries options.model ------------------
    #
    # The runner now passes ``model=options.model`` into the
    # DispatchCompleted event so downstream consumers (CostLedgerConsumer
    # per D7, CostAnalyzer.model_costs() per D8) can attribute spend
    # per-model. Symmetric with the existing DispatchStarted.model field.

    async def test_dispatch_completed_carries_options_model(self):
        """Sage memo D4 — DispatchCompleted MUST carry the model string from
        the DispatchOptions, so cost attribution by model is observable on
        completion. The runner has ``options.model`` in scope at the
        emission site (runner.py:184-193) — no new wiring beyond a single
        keyword pass-through.
        """
        bus, capture = _bus_with_capture(DispatchCompleted)
        env = _envelope()
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.05)])
        await execute_with_retry(
            backend,
            env,
            _options(model="claude-haiku-4-5"),
            event_bus=bus,
            retry_delay=0.0,
        )
        completed = capture.of_type(DispatchCompleted)
        assert len(completed) == 1
        assert completed[0].model == "claude-haiku-4-5"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# No event bus — must not crash
# ---------------------------------------------------------------------------


class TestNoEventBus:
    """``event_bus=None`` is a supported state — no crashes on any path."""

    async def test_success_no_bus(self):
        env = _envelope()
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED

    async def test_failure_no_bus(self):
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("boom")])
        result = await execute_with_retry(backend, env, _options(), max_retries=0, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED

    async def test_retry_no_bus(self):
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("fail"), env.with_result("ok", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.retries == 1

    async def test_terminal_error_no_bus(self):
        env = _envelope()
        failed = env.with_error(ErrorDetail(error_type="RateLimitError", message="limited"))
        backend = ScriptedBackend([failed])
        result = await execute_with_retry(backend, env, _options(), max_retries=3, retry_delay=0.0)
        assert result.envelope.status == TaskStatus.FAILED
        assert result.retries == 0


# ---------------------------------------------------------------------------
# Concurrent dispatches
# ---------------------------------------------------------------------------


class TestConcurrentDispatches:
    """Two coroutines running the runner must not corrupt each other's counters."""

    async def test_two_concurrent_success_dispatches_independent_results(self):
        env_a = _envelope(task="a", agent_name="alpha")
        env_b = _envelope(task="b", agent_name="beta")
        backend_a = ScriptedBackend([env_a.with_result("A", cost_usd=0.10)])
        backend_b = ScriptedBackend([env_b.with_result("B", cost_usd=0.20)])

        result_a, result_b = await asyncio.gather(
            execute_with_retry(backend_a, env_a, _options(), retry_delay=0.0),
            execute_with_retry(backend_b, env_b, _options(), retry_delay=0.0),
        )
        assert result_a.envelope.result == "A"
        assert result_b.envelope.result == "B"
        assert result_a.cost_usd == pytest.approx(0.10)
        assert result_b.cost_usd == pytest.approx(0.20)

    async def test_concurrent_events_do_not_duplicate(self):
        """Shared EventBus — each dispatch emits its own started+completed."""
        bus = EventBus()
        capture = EventCapture()
        bus.subscribe(DispatchStarted, capture.handler)
        bus.subscribe(DispatchCompleted, capture.handler)

        env_a = _envelope(task="a", agent_name="alpha")
        env_b = _envelope(task="b", agent_name="beta")
        backend_a = ScriptedBackend([env_a.with_result("A", cost_usd=0.10)])
        backend_b = ScriptedBackend([env_b.with_result("B", cost_usd=0.20)])

        await asyncio.gather(
            execute_with_retry(backend_a, env_a, _options(), event_bus=bus, retry_delay=0.0),
            execute_with_retry(backend_b, env_b, _options(), event_bus=bus, retry_delay=0.0),
        )

        assert len(capture.of_type(DispatchStarted)) == 2
        assert len(capture.of_type(DispatchCompleted)) == 2


# ---------------------------------------------------------------------------
# Options pass-through
# ---------------------------------------------------------------------------


class TestOptionsPassthrough:
    """The runner hands the caller's ``DispatchOptions`` verbatim to the backend."""

    async def test_options_reach_backend(self):
        observed: dict[str, DispatchOptions] = {}

        class ObservingBackend:
            async def execute(
                self,
                envelope: Envelope,
                *,
                options: DispatchOptions,
            ) -> Envelope:
                observed["options"] = options
                return envelope.with_result("ok", cost_usd=0.01)

            async def health_check(self) -> bool:
                return True

        env = _envelope()
        opts = DispatchOptions(
            model="claude-opus-4",
            max_turns=7,
            max_budget_usd=2.5,
            thinking_depth="ultrathink",
        )
        await execute_with_retry(ObservingBackend(), env, opts, retry_delay=0.0)

        assert observed["options"] is opts
        assert observed["options"].model == "claude-opus-4"
        assert observed["options"].thinking_depth == "ultrathink"

    async def test_envelope_reaches_backend_unchanged(self):
        observed: dict[str, Envelope] = {}

        class ObservingBackend:
            async def execute(
                self,
                envelope: Envelope,
                *,
                options: DispatchOptions,
            ) -> Envelope:
                observed["envelope"] = envelope
                return envelope.with_result("ok", cost_usd=0.01)

            async def health_check(self) -> bool:
                return True

        env = _envelope(task="exact-task", agent_name="exact-agent")
        await execute_with_retry(ObservingBackend(), env, _options(), retry_delay=0.0)

        assert observed["envelope"].task == "exact-task"
        assert observed["envelope"].agent_name == "exact-agent"
        assert observed["envelope"].envelope_id == env.envelope_id


# ---------------------------------------------------------------------------
# Default parameters
# ---------------------------------------------------------------------------


class TestDefaults:
    """Documented defaults keep the runner callable without every knob spelled out."""

    async def test_default_max_retries_allows_some_recovery(self):
        """Default must permit at least one retry — zero-retry default would
        make the runner equivalent to raw backend.execute on error paths."""
        env = _envelope()
        backend = ScriptedBackend([RuntimeError("transient"), env.with_result("ok", cost_usd=0.01)])
        # Do not pass max_retries — use the shipped default.
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries >= 1

    async def test_default_event_bus_is_none(self):
        """Omitting ``event_bus`` MUST NOT crash."""
        env = _envelope()
        backend = ScriptedBackend([env.with_result("ok", cost_usd=0.01)])
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED

    async def test_default_timeout_is_none(self):
        """Omitting ``timeout_seconds`` MUST NOT enforce a timeout."""
        env = _envelope()
        backend = SlowBackend(delay=0.05)  # Tiny delay, no timeout should crash it.
        result = await execute_with_retry(backend, env, _options(), retry_delay=0.0)
        assert result.envelope.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# BON-351 Knight B — model identity preservation across retries.
#
# Sage memo D4 (DispatchCompleted gains `model: str = ""`) + D4 AMBIG
# resolution (the model on Completed reflects the model the dispatch was
# REQUESTED with -- the START model -- not whatever the last retry happened
# to mutate to).
#
# The runner does NOT mutate `options.model` between attempts.  Because
# `cumulative_cost` aggregates retries indiscriminately (Scout report §A
# line 82), the model identifier MUST be the start identifier so the
# ledger row attributes the full retry-burn to one model.  These tests
# pin that invariant before warriors get a chance to drift it.
#
# Knight A's spine test (`test_dispatch_completed_carries_options_model`)
# covers the happy single-attempt case.  Knight B locks the retry corner.
# ---------------------------------------------------------------------------


class TestModelOnRetry:
    """BON-351 D4 — model on Completed equals start model across retries."""

    async def test_model_unchanged_across_retries(self):
        """Backend sees the same `options.model` string on every attempt.

        Locks Sage D4: the runner does not rewrite `options.model` between
        attempts. A future "fallback to cheaper model on rate-limit"
        feature would be a separate, explicit ticket (D-FT F).
        """
        env = _envelope()

        observed_models: list[str] = []

        class _ObservingBackend:
            call_count = 0

            async def execute(self, envelope: Envelope, *, options: DispatchOptions) -> Envelope:
                observed_models.append(options.model)
                _ObservingBackend.call_count += 1
                if _ObservingBackend.call_count < 3:
                    raise RuntimeError(f"transient {_ObservingBackend.call_count}")
                return envelope.with_result("ok", cost_usd=0.01)

            async def health_check(self) -> bool:
                return True

        opts = DispatchOptions(model="claude-opus-4-7", max_budget_usd=1.0)
        result = await execute_with_retry(
            _ObservingBackend(), env, opts, max_retries=3, retry_delay=0.0
        )

        assert result.envelope.status == TaskStatus.COMPLETED
        assert result.retries == 2
        assert len(observed_models) == 3
        # Same model on every attempt — runner does NOT mutate options.model.
        assert observed_models == ["claude-opus-4-7"] * 3

    async def test_completed_model_equals_started_model(self):
        """`DispatchCompleted.model` equals `DispatchStarted.model` for one dispatch.

        Locks Sage D4 AMBIG resolution: Completed reflects the START model.
        Across a multi-retry success, the Started event fires once at
        attempt 1, the Completed event fires once at success — both must
        carry the same model string.

        This test ALSO locks the new `model` field on `DispatchCompleted`
        (D4): without the field, the assertion below resolves to
        AttributeError -> RED.
        """
        bus, capture = _bus_with_capture(DispatchStarted, DispatchCompleted)

        env = _envelope(agent_name="warrior")
        success = env.with_result("ok", cost_usd=0.01)
        backend = ScriptedBackend([RuntimeError("net"), RuntimeError("net2"), success])

        opts = DispatchOptions(model="claude-haiku-4-5", max_budget_usd=1.0)
        await execute_with_retry(backend, env, opts, max_retries=3, event_bus=bus, retry_delay=0.0)

        started = capture.of_type(DispatchStarted)
        completed = capture.of_type(DispatchCompleted)
        assert len(started) == 1
        assert len(completed) == 1
        # The new field on DispatchCompleted (BON-351 D4) carries the start model.
        assert completed[0].model == started[0].model  # type: ignore[attr-defined]
        assert completed[0].model == "claude-haiku-4-5"  # type: ignore[attr-defined]
