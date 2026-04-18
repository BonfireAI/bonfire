"""RED tests for bonfire.events.consumers — BON-333 W2.3 canonical suite.

Four consumers land in the public bus package:

* ``SessionLoggerConsumer`` (``bonfire.events.consumers.logger``) — subscribes
  globally; persists every event via ``persistence.append_event(session_id, event)``.
* ``DisplayConsumer`` (``bonfire.events.consumers.display``) — subscribes to
  four event types and formats each into a human-readable message for a
  caller-supplied callback (sync or async).
* ``CostTracker`` (``bonfire.events.consumers.cost``) — accumulates cost from
  ``DispatchCompleted`` events and emits budget warning / exceeded events at
  80% / 100% thresholds (each latched — fires at most once).
* ``VaultIngestConsumer`` (``bonfire.events.consumers.vault_ingest``) — public
  surface only in W2.3: constructor + ``register(bus)`` that subscribes to
  the four event types. Deep storage semantics (hashing, dedup, backend
  protocol) are OUT of W2.3 scope — they belong to the future
  ``bonfire.vault`` transfer wave.

A ``wire_consumers(*, bus, persistence, cost_tracker, display_callback,
vault_backend)`` helper at ``bonfire.events.consumers`` registers all four
consumers with a single keyword-only call.

Public v0.1 adaptations vs. the hardened v1 engine:

* No imports from ``bonfire.session.persistence`` (module is a placeholder in
  public v0.1). Persistence is stubbed via ``MagicMock``.
* No imports from ``bonfire.vault.*`` (does not exist in public v0.1). A
  minimal in-memory backend stub is defined inline where needed.
* No ``CostLedgerConsumer`` wiring — ``bonfire.costs`` is not part of W2.3.
* No ``persona`` branch in ``DisplayConsumer`` — that wiring arrives with
  ``bonfire.persona``.

Every test is RED via a per-file import shim plus an autouse fixture that
re-raises the captured import error while the modules are missing.

Adjudication: ``docs/audit/sage-decisions/bon-333-sage-20260418T004958Z.md``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bonfire.models.events import (
    BonfireEvent,
    CostBudgetExceeded,
    CostBudgetWarning,
    DispatchCompleted,
    DispatchFailed,
    PipelineStarted,
    QualityFailed,
    SessionEnded,
    StageCompleted,
    StageFailed,
    StageStarted,
)

# RED-phase import shim: consumer modules do not exist yet. Tests still
# reference real names; each test fails via the autouse fixture while the
# modules are missing. Collection succeeds because the import error is
# swallowed at module load time.
try:
    from bonfire.events.bus import EventBus
    from bonfire.events.consumers import wire_consumers
    from bonfire.events.consumers.cost import CostTracker
    from bonfire.events.consumers.display import DisplayConsumer
    from bonfire.events.consumers.logger import SessionLoggerConsumer
    from bonfire.events.consumers.vault_ingest import VaultIngestConsumer
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    EventBus = None  # type: ignore[assignment,misc]
    wire_consumers = None  # type: ignore[assignment]
    CostTracker = None  # type: ignore[assignment,misc]
    DisplayConsumer = None  # type: ignore[assignment,misc]
    SessionLoggerConsumer = None  # type: ignore[assignment,misc]
    VaultIngestConsumer = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_modules():
    """Fail every test while the consumer modules are missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.events.consumers not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Event factories
# ---------------------------------------------------------------------------

_SESSION = "test-session-001"


def _stage_completed(**overrides) -> StageCompleted:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "stage_name": "scout",
        "agent_name": "scout-alpha",
        "duration_seconds": 1.5,
        "cost_usd": 0.02,
    }
    defaults.update(overrides)
    return StageCompleted(**defaults)


def _stage_failed(**overrides) -> StageFailed:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "stage_name": "knight",
        "agent_name": "knight-bravo",
        "error_message": "Model returned empty response",
    }
    defaults.update(overrides)
    return StageFailed(**defaults)


def _dispatch_completed(**overrides) -> DispatchCompleted:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "agent_name": "warrior-charlie",
        "cost_usd": 1.50,
        "duration_seconds": 3.2,
    }
    defaults.update(overrides)
    return DispatchCompleted(**defaults)


def _dispatch_failed(**overrides) -> DispatchFailed:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "agent_name": "warrior-charlie",
        "error_message": "API key expired",
    }
    defaults.update(overrides)
    return DispatchFailed(**defaults)


def _quality_failed(**overrides) -> QualityFailed:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "gate_name": "lint",
        "stage_name": "warrior",
        "severity": "error",
        "message": "ruff found 3 violations",
    }
    defaults.update(overrides)
    return QualityFailed(**defaults)


def _cost_budget_warning(**overrides) -> CostBudgetWarning:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "current_usd": 8.0,
        "budget_usd": 10.0,
        "percent": 80.0,
    }
    defaults.update(overrides)
    return CostBudgetWarning(**defaults)


def _session_ended(**overrides) -> SessionEnded:
    defaults = {
        "session_id": _SESSION,
        "sequence": 0,
        "status": "completed",
        "total_cost_usd": 0.35,
    }
    defaults.update(overrides)
    return SessionEnded(**defaults)


# ---------------------------------------------------------------------------
# Inline stubs (public v0.1 adaptation)
# ---------------------------------------------------------------------------


class _StubVaultBackend:
    """Minimal vault backend stub — records store invocations."""

    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def store(self, entry: Any) -> None:
        self.entries.append(entry)

    async def exists(self, content_hash: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> Any:
    return EventBus()


@pytest.fixture
def mock_persistence() -> MagicMock:
    """Persistence stub with ``append_event(session_id, event)`` method."""
    return MagicMock()


@pytest.fixture
def mock_callback() -> AsyncMock:
    """Async callback for DisplayConsumer."""
    return AsyncMock()


@pytest.fixture
def vault_backend() -> _StubVaultBackend:
    return _StubVaultBackend()


# ===========================================================================
# 1. Module-level imports — every consumer module reachable
# ===========================================================================


class TestConsumerImports:
    """Each consumer lives at its canonical module path."""

    def test_cost_tracker_importable(self):
        from bonfire.events.consumers.cost import CostTracker as _CT

        assert _CT is not None

    def test_display_consumer_importable(self):
        from bonfire.events.consumers.display import DisplayConsumer as _DC

        assert _DC is not None

    def test_session_logger_importable(self):
        from bonfire.events.consumers.logger import SessionLoggerConsumer as _SL

        assert _SL is not None

    def test_vault_ingest_importable(self):
        from bonfire.events.consumers.vault_ingest import VaultIngestConsumer as _VI

        assert _VI is not None

    def test_wire_consumers_importable(self):
        from bonfire.events.consumers import wire_consumers as _wire

        assert callable(_wire)


# ===========================================================================
# 2. SessionLoggerConsumer — global subscriber, positional append_event args
# ===========================================================================


class TestSessionLoggerConsumerContract:
    """Contract: subscribes globally; persists every event via append_event."""

    def test_constructor_accepts_persistence(self, mock_persistence):
        consumer = SessionLoggerConsumer(persistence=mock_persistence)
        assert consumer is not None

    async def test_on_event_calls_append_event_with_session_id_positional(self, mock_persistence):
        """append_event is called with the session_id as the FIRST positional arg.

        V1 calls ``self._persistence.append_event(event.session_id, event)`` —
        positional. The canonical contract is positional, in that order.
        """
        consumer = SessionLoggerConsumer(persistence=mock_persistence)
        event = _stage_completed()
        await consumer.on_event(event)

        mock_persistence.append_event.assert_called_once()
        call_args = mock_persistence.append_event.call_args
        assert call_args.args[0] == _SESSION

    async def test_on_event_calls_append_event_with_event_second_positional(self, mock_persistence):
        """The event object itself is passed as the SECOND positional arg."""
        consumer = SessionLoggerConsumer(persistence=mock_persistence)
        event = _stage_completed()
        await consumer.on_event(event)

        call_args = mock_persistence.append_event.call_args
        assert call_args.args[1] is event

    def test_register_uses_subscribe_all(self, mock_persistence, bus):
        """register(bus) uses bus.subscribe_all to catch every event type."""
        consumer = SessionLoggerConsumer(persistence=mock_persistence)
        consumer.register(bus)
        # Global subscriber list is populated with exactly one entry.
        assert len(bus._global) == 1
        # No typed subscriptions.
        assert all(len(v) == 0 for v in bus._typed.values())

    async def test_register_and_emit_triggers_append_event(self, mock_persistence, bus):
        consumer = SessionLoggerConsumer(persistence=mock_persistence)
        consumer.register(bus)
        await bus.emit(_stage_completed())

        mock_persistence.append_event.assert_called_once()

    async def test_logger_receives_all_event_types(self, mock_persistence, bus):
        """As a subscribe_all consumer, it persists heterogeneous event types."""
        consumer = SessionLoggerConsumer(persistence=mock_persistence)
        consumer.register(bus)

        await bus.emit(_stage_completed())
        await bus.emit(_stage_failed())
        await bus.emit(_dispatch_completed())

        assert mock_persistence.append_event.call_count == 3

    async def test_logger_never_raises_on_persistence_failure(self, bus):
        """If persistence.append_event raises, the consumer MUST swallow it."""
        broken = MagicMock()
        broken.append_event.side_effect = RuntimeError("disk full")

        consumer = SessionLoggerConsumer(persistence=broken)
        consumer.register(bus)

        # Must not raise — pipeline survives persistence errors.
        await bus.emit(_stage_completed())

    async def test_persistence_exception_does_not_stop_next_event(self, bus):
        """After a persistence failure, the next emit still attempts append_event."""
        persistence = MagicMock()
        call_count = {"n": 0}

        def failing_append(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first call failed")

        persistence.append_event.side_effect = failing_append

        consumer = SessionLoggerConsumer(persistence=persistence)
        consumer.register(bus)

        await bus.emit(_stage_completed())
        await bus.emit(_stage_failed())

        # Both attempts made — the first raised but the second still fired.
        assert call_count["n"] == 2


# ===========================================================================
# 3. DisplayConsumer — four typed subscriptions, sync or async callback
# ===========================================================================


class TestDisplayConsumerContract:
    """Contract: formats four event types into strings for a callback."""

    def test_constructor_accepts_async_callback(self, mock_callback):
        consumer = DisplayConsumer(callback=mock_callback)
        assert consumer is not None

    def test_constructor_accepts_sync_callback(self):
        def sync_cb(msg: str) -> None:
            pass

        consumer = DisplayConsumer(callback=sync_cb)
        assert consumer is not None

    def test_register_subscribes_to_exactly_four_event_types(self, mock_callback, bus):
        """Exactly four event types receive a display handler."""
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        expected = {StageCompleted, StageFailed, QualityFailed, CostBudgetWarning}
        assert subscribed_types == expected


class TestDisplayConsumerFormatting:
    """Each of the four event types produces a specific, non-empty message."""

    async def test_stage_completed_callback_contains_stage_name(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_stage_completed(stage_name="scout"))

        mock_callback.assert_called_once()
        message = mock_callback.call_args.args[0]
        assert isinstance(message, str)
        assert "scout" in message

    async def test_stage_completed_callback_contains_duration(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_stage_completed(duration_seconds=2.7))

        message = mock_callback.call_args.args[0]
        assert "2.7" in message

    async def test_stage_completed_callback_contains_cost(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_stage_completed(cost_usd=0.05))

        message = mock_callback.call_args.args[0]
        assert "0.05" in message

    async def test_stage_failed_callback_mentions_failed(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_stage_failed())

        mock_callback.assert_called_once()
        message = mock_callback.call_args.args[0]
        assert isinstance(message, str)
        assert "FAILED" in message.upper()

    async def test_stage_failed_callback_contains_error_message(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_stage_failed(error_message="API timeout"))

        message = mock_callback.call_args.args[0]
        assert "API timeout" in message

    async def test_quality_failed_callback_contains_gate_name(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_quality_failed(gate_name="lint"))

        mock_callback.assert_called_once()
        message = mock_callback.call_args.args[0]
        assert "lint" in message

    async def test_quality_failed_callback_contains_message(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_quality_failed(message="ruff found 3 violations"))

        message = mock_callback.call_args.args[0]
        assert "ruff found 3 violations" in message

    async def test_cost_budget_warning_callback_contains_percent(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(_cost_budget_warning(percent=80.0))

        mock_callback.assert_called_once()
        message = mock_callback.call_args.args[0]
        assert "80" in message


class TestDisplayConsumerCallbackModes:
    """DisplayConsumer accepts both sync and async callbacks."""

    async def test_async_callback_awaited(self, bus):
        calls: list[str] = []

        async def callback(msg: str) -> None:
            calls.append(msg)

        consumer = DisplayConsumer(callback=callback)
        consumer.register(bus)
        await bus.emit(_stage_completed())

        assert len(calls) == 1
        assert isinstance(calls[0], str)

    async def test_sync_callback_invoked(self, bus):
        calls: list[str] = []

        def callback(msg: str) -> None:
            calls.append(msg)

        consumer = DisplayConsumer(callback=callback)
        consumer.register(bus)
        await bus.emit(_stage_completed())

        assert len(calls) == 1
        assert isinstance(calls[0], str)


class TestDisplayConsumerIgnoresUnrelated:
    """Display subscribes to four types only — nothing else triggers the callback."""

    async def test_stage_started_not_displayed(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(StageStarted(session_id="s", sequence=0, stage_name="s", agent_name="a"))

        mock_callback.assert_not_called()

    async def test_pipeline_started_not_displayed(self, mock_callback, bus):
        consumer = DisplayConsumer(callback=mock_callback)
        consumer.register(bus)
        await bus.emit(PipelineStarted(session_id="s", sequence=0, plan_name="p", budget_usd=1.0))

        mock_callback.assert_not_called()


class TestDisplayConsumerResilience:
    """A failing callback must not crash the pipeline."""

    async def test_sync_callback_exception_does_not_propagate(self, bus):
        def broken(msg: str) -> None:
            raise RuntimeError("display broken")

        consumer = DisplayConsumer(callback=broken)
        consumer.register(bus)

        # Must not raise — isolation is preserved.
        await bus.emit(_stage_completed())

    async def test_async_callback_exception_does_not_propagate(self, bus):
        async def broken(msg: str) -> None:
            raise RuntimeError("async display broken")

        consumer = DisplayConsumer(callback=broken)
        consumer.register(bus)

        # Must not raise.
        await bus.emit(_stage_completed())


# ===========================================================================
# 4. CostTracker — accumulates, latches warning @ 80%, exceeded @ 100%
# ===========================================================================


class TestCostTrackerContract:
    """Contract: accumulates cost, emits warning @ 80%, exceeded @ 100%."""

    def test_constructor_accepts_budget_and_bus(self, bus):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        assert tracker is not None

    def test_total_cost_starts_at_zero_as_float(self, bus):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        assert tracker.total_cost_usd == 0.0
        assert isinstance(tracker.total_cost_usd, float)

    def test_register_subscribes_only_to_dispatch_completed(self, bus):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        assert subscribed_types == {DispatchCompleted}


class TestCostTrackerAccumulation:
    """Running total comes from DispatchCompleted.cost_usd."""

    async def test_single_dispatch_updates_total_cost(self, bus):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=1.5))
        assert tracker.total_cost_usd == pytest.approx(1.5)

    async def test_multiple_dispatches_accumulate(self, bus):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=1.5))
        await bus.emit(_dispatch_completed(cost_usd=2.3))
        assert tracker.total_cost_usd == pytest.approx(3.8)

    async def test_non_dispatch_events_do_not_contribute(self, bus):
        """Only DispatchCompleted contributes to the total."""
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_stage_completed(cost_usd=99.0))
        await bus.emit(_stage_failed())

        assert tracker.total_cost_usd == 0.0


class TestCostTrackerThresholds:
    """Budget warning at >=80%, exceeded at >=100%, each latched to fire once."""

    async def test_no_warning_below_80_percent(self, bus):
        captured: list[BonfireEvent] = []

        async def capture(event: BonfireEvent) -> None:
            captured.append(event)

        bus.subscribe_all(capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        # 7.9 / 10.0 = 79% → no warning.
        await bus.emit(_dispatch_completed(cost_usd=7.9))
        warnings = [e for e in captured if isinstance(e, CostBudgetWarning)]
        assert len(warnings) == 0

    async def test_warning_emitted_at_eighty_percent(self, bus):
        captured: list[CostBudgetWarning] = []

        async def capture(event: CostBudgetWarning) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetWarning, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        # 8.0 / 10.0 = 80% → trigger warning.
        await bus.emit(_dispatch_completed(cost_usd=8.0))

        assert len(captured) == 1
        assert captured[0].percent == pytest.approx(80.0)
        assert captured[0].current_usd == pytest.approx(8.0)
        assert captured[0].budget_usd == pytest.approx(10.0)

    async def test_warning_latched_emits_at_most_once(self, bus):
        """Crossing 80% twice only fires one warning event."""
        captured: list[CostBudgetWarning] = []

        async def capture(event: CostBudgetWarning) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetWarning, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=8.0))
        await bus.emit(_dispatch_completed(cost_usd=0.5))

        assert len(captured) == 1

    async def test_exceeded_emitted_at_hundred_percent(self, bus):
        captured: list[CostBudgetExceeded] = []

        async def capture(event: CostBudgetExceeded) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetExceeded, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=10.0))

        assert len(captured) == 1
        assert captured[0].current_usd == pytest.approx(10.0)
        assert captured[0].budget_usd == pytest.approx(10.0)

    async def test_exceeded_latched_emits_at_most_once(self, bus):
        """Crossing 100% twice only fires one exceeded event."""
        captured: list[CostBudgetExceeded] = []

        async def capture(event: CostBudgetExceeded) -> None:
            captured.append(event)

        bus.subscribe(CostBudgetExceeded, capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=10.0))
        await bus.emit(_dispatch_completed(cost_usd=5.0))

        assert len(captured) == 1

    async def test_single_large_dispatch_crosses_both_thresholds(self, bus):
        """One huge dispatch crossing 80% and 100% emits BOTH events."""
        captured: list[BonfireEvent] = []

        async def capture(event: BonfireEvent) -> None:
            captured.append(event)

        bus.subscribe_all(capture)

        tracker = CostTracker(budget_usd=10.0, bus=bus)
        tracker.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=50.0))

        warnings = [e for e in captured if isinstance(e, CostBudgetWarning)]
        exceeded = [e for e in captured if isinstance(e, CostBudgetExceeded)]
        assert len(warnings) == 1
        assert len(exceeded) == 1


# ===========================================================================
# 5. VaultIngestConsumer — surface contract only (deep storage OUT of scope)
# ===========================================================================


class TestVaultIngestConsumerSurface:
    """Surface-level contract — full storage semantics are OUT of W2.3 scope.

    See ``docs/audit/sage-decisions/bon-333-sage-20260418T004958Z.md`` §2 for
    rationale. The real ``VaultIngestConsumer`` lives at
    ``bonfire.vault.consumer`` (not in public v0.1). In public v0.1, this
    namespace exposes the class surface — enough for ``wire_consumers`` to
    construct and register it — but hashing / dedup / backend-protocol
    details are covered in the future vault-transfer wave.
    """

    def test_class_is_importable(self):
        assert VaultIngestConsumer is not None

    def test_constructor_accepts_backend_and_project_name(self, vault_backend):
        consumer = VaultIngestConsumer(backend=vault_backend, project_name="bonfire")
        assert consumer is not None

    def test_register_is_a_method(self):
        """The consumer exposes a register(bus) method used by wire_consumers."""
        assert hasattr(VaultIngestConsumer, "register")
        assert callable(VaultIngestConsumer.register)

    def test_register_subscribes_to_four_expected_event_types(self, vault_backend, bus):
        """register subscribes to StageCompleted, StageFailed, DispatchFailed, SessionEnded."""
        consumer = VaultIngestConsumer(backend=vault_backend, project_name="bonfire")
        consumer.register(bus)

        subscribed_types = {k for k, v in bus._typed.items() if len(v) > 0}
        expected = {StageCompleted, StageFailed, DispatchFailed, SessionEnded}
        assert expected.issubset(subscribed_types)
        # Nothing else should be subscribed by this consumer alone.
        assert subscribed_types == expected

    async def test_register_and_emit_does_not_raise(self, vault_backend, bus):
        """End-to-end: emit each supported event type, no exceptions propagate."""
        consumer = VaultIngestConsumer(backend=vault_backend, project_name="bonfire")
        consumer.register(bus)

        # None of these should raise — they may or may not touch the backend.
        await bus.emit(_stage_completed())
        await bus.emit(_stage_failed())
        await bus.emit(_dispatch_failed())
        await bus.emit(_session_ended())


# ===========================================================================
# 6. Consumer coexistence — multiple consumers on one bus, isolation holds
# ===========================================================================


class TestConsumerCoexistence:
    """Several consumers on the same bus, each receiving matching events."""

    async def test_cost_and_logger_both_receive_dispatch(self, bus, mock_persistence):
        cost = CostTracker(budget_usd=10.0, bus=bus)
        cost.register(bus)

        logger = SessionLoggerConsumer(persistence=mock_persistence)
        logger.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=0.5))

        assert cost.total_cost_usd == pytest.approx(0.5)
        assert mock_persistence.append_event.call_count == 1

    async def test_display_and_logger_both_receive_stage_completed(self, bus, mock_persistence):
        calls: list[str] = []

        display = DisplayConsumer(callback=lambda msg: calls.append(msg))
        display.register(bus)

        logger = SessionLoggerConsumer(persistence=mock_persistence)
        logger.register(bus)

        await bus.emit(_stage_completed())

        assert len(calls) == 1
        assert mock_persistence.append_event.call_count == 1

    async def test_broken_display_does_not_block_logger(self, bus, mock_persistence):
        """A broken DisplayConsumer must not prevent SessionLogger from running.

        This is the core distributed-systems invariant of the event bus:
        peer consumers remain healthy when one fails.
        """

        def broken(msg: str) -> None:
            raise RuntimeError("display blew up")

        display = DisplayConsumer(callback=broken)
        display.register(bus)

        logger = SessionLoggerConsumer(persistence=mock_persistence)
        logger.register(bus)

        await bus.emit(_stage_completed())

        assert mock_persistence.append_event.call_count == 1

    async def test_broken_logger_does_not_block_display(self, bus):
        """A failing persistence.append_event must not prevent DisplayConsumer."""
        calls: list[str] = []

        persistence = MagicMock()
        persistence.append_event.side_effect = RuntimeError("disk full")

        logger = SessionLoggerConsumer(persistence=persistence)
        logger.register(bus)

        display = DisplayConsumer(callback=lambda msg: calls.append(msg))
        display.register(bus)

        await bus.emit(_stage_completed())

        # Display still runs despite logger failure.
        assert len(calls) == 1

    async def test_cost_tracker_threshold_feeds_display(self, bus):
        """CostTracker re-emits CostBudgetWarning — DisplayConsumer picks it up.

        End-to-end: DispatchCompleted → CostTracker → emit CostBudgetWarning
        → DisplayConsumer formats it. Proves the bus is re-entrant (a
        consumer emitting through the same bus from inside a handler).
        """
        calls: list[str] = []

        cost = CostTracker(budget_usd=10.0, bus=bus)
        cost.register(bus)

        display = DisplayConsumer(callback=lambda msg: calls.append(msg))
        display.register(bus)

        await bus.emit(_dispatch_completed(cost_usd=9.0))

        # Display received the re-emitted warning — the message contains the
        # percent (>=80%).
        assert len(calls) == 1
        assert "80" in calls[0] or "90" in calls[0]


# ===========================================================================
# 7. wire_consumers — single keyword-only factory that wires all four
# ===========================================================================


class TestWireConsumersContract:
    """Contract: wire_consumers(*, bus, persistence, cost_tracker,
    display_callback, vault_backend) wires all four consumers with one call.

    See ``docs/audit/sage-decisions/bon-333-sage-20260418T004958Z.md`` §3 for
    signature adjudication vs. V1.
    """

    def test_wire_consumers_is_callable(self):
        assert callable(wire_consumers)

    def test_wire_consumers_is_keyword_only(self, bus, mock_persistence, mock_callback):
        """wire_consumers rejects positional invocation — all params keyword-only."""
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        backend = _StubVaultBackend()

        with pytest.raises(TypeError):
            # Positional call MUST fail — keyword-only enforcement.
            wire_consumers(bus, mock_persistence, tracker, mock_callback, backend)  # type: ignore[misc]

    def test_wire_consumers_accepts_all_five_kwargs(self, bus, mock_persistence, mock_callback):
        """All five kwargs accepted; returns None; does not raise."""
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        backend = _StubVaultBackend()

        result = wire_consumers(
            bus=bus,
            persistence=mock_persistence,
            cost_tracker=tracker,
            display_callback=mock_callback,
            vault_backend=backend,
        )
        assert result is None

    async def test_wired_stage_completed_triggers_display(
        self, bus, mock_persistence, mock_callback
    ):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        backend = _StubVaultBackend()
        wire_consumers(
            bus=bus,
            persistence=mock_persistence,
            cost_tracker=tracker,
            display_callback=mock_callback,
            vault_backend=backend,
        )

        await bus.emit(_stage_completed())
        mock_callback.assert_called()

    async def test_wired_any_event_triggers_logger(self, bus, mock_persistence, mock_callback):
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        backend = _StubVaultBackend()
        wire_consumers(
            bus=bus,
            persistence=mock_persistence,
            cost_tracker=tracker,
            display_callback=mock_callback,
            vault_backend=backend,
        )

        await bus.emit(_stage_completed())
        mock_persistence.append_event.assert_called()

    async def test_wired_cost_tracker_accumulates(self, bus, mock_persistence, mock_callback):
        """After wiring: DispatchCompleted accumulates on the tracker."""
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        backend = _StubVaultBackend()
        wire_consumers(
            bus=bus,
            persistence=mock_persistence,
            cost_tracker=tracker,
            display_callback=mock_callback,
            vault_backend=backend,
        )

        await bus.emit(_dispatch_completed(cost_usd=0.75))
        assert tracker.total_cost_usd == pytest.approx(0.75)

    async def test_wired_vault_ingest_is_registered(
        self, bus, mock_persistence, mock_callback, vault_backend
    ):
        """After wiring: StageCompleted, StageFailed, DispatchFailed, SessionEnded
        all have at least one typed subscriber (VaultIngestConsumer)."""
        tracker = CostTracker(budget_usd=10.0, bus=bus)
        wire_consumers(
            bus=bus,
            persistence=mock_persistence,
            cost_tracker=tracker,
            display_callback=mock_callback,
            vault_backend=vault_backend,
        )

        subscribed = {k for k, v in bus._typed.items() if len(v) > 0}
        # VaultIngest + Display contribute these types; the intersection
        # is the vault set. Every vault-expected type MUST be present.
        for t in (StageCompleted, StageFailed, DispatchFailed, SessionEnded):
            assert t in subscribed, f"{t.__name__} not subscribed after wire_consumers"
