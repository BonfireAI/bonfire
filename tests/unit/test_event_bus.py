"""RED tests for bonfire.events.bus — BON-333 W2.3 canonical suite.

The EventBus is the pipeline's nervous system. Contract — derived from the
hardened v1 engine and adjudicated in
``docs/audit/sage-decisions/bon-333-sage-20260418T004958Z.md``:

- Two subscriber tiers: typed (``subscribe(EventType, handler)``) and global
  (``subscribe_all(handler)``).
- **C7 ordering:** typed handlers always fire BEFORE global handlers,
  regardless of registration order. Within each tier: registration order.
- All handlers awaited **sequentially** — correctness over performance.
- **Consumer isolation:** each handler wrapped in try/except — one
  consumer's failure does not break others. Errors are logged, never raised.
- **Sequence stamping:** monotonic counter, stamped via
  ``model_copy(update={"sequence": n})``. Original event is frozen and
  never mutated.
- **Exact-type filter:** ``type(event) is event_type`` — subclasses do NOT
  trigger parent-type handlers. Global delivery goes through subscribe_all.

Public v0.1 consumes ``BonfireEvent`` and subclasses from
``bonfire.models.events`` (transferred in W2.1).

All tests MUST fail while ``bonfire.events.bus`` does not exist yet — the
autouse fixture re-raises the import error captured at collection time.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from bonfire.models.events import (
    BonfireEvent,
    CostAccrued,
    DispatchCompleted,
    PipelineCompleted,
    PipelineStarted,
    StageCompleted,
    StageFailed,
    StageStarted,
)

# RED-phase import shim: bonfire.events.bus does not exist yet. Collection
# succeeds because the ImportError is swallowed; every test then fails via
# the autouse fixture until GREEN lands.
try:
    from bonfire.events import BonfireEvent as _ReexportedBonfireEvent
    from bonfire.events import EventBus as _ReexportedEventBus
    from bonfire.events.bus import EventBus
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    EventBus = None  # type: ignore[assignment,misc]
    _ReexportedEventBus = None  # type: ignore[assignment]
    _ReexportedBonfireEvent = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.events.bus is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.events.bus not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Event factories — keep tests short and intention-revealing.
# ---------------------------------------------------------------------------


def _stage_started(**overrides) -> StageStarted:
    defaults = {
        "session_id": "sess-1",
        "sequence": 0,
        "stage_name": "scout",
        "agent_name": "scout-alpha",
    }
    defaults.update(overrides)
    return StageStarted(**defaults)


def _pipeline_started(**overrides) -> PipelineStarted:
    defaults = {
        "session_id": "sess-1",
        "sequence": 0,
        "plan_name": "plan-a",
        "budget_usd": 10.0,
    }
    defaults.update(overrides)
    return PipelineStarted(**defaults)


def _stage_completed(**overrides) -> StageCompleted:
    defaults = {
        "session_id": "sess-1",
        "sequence": 0,
        "stage_name": "scout",
        "agent_name": "scout-alpha",
        "duration_seconds": 12.5,
        "cost_usd": 0.03,
    }
    defaults.update(overrides)
    return StageCompleted(**defaults)


# ---------------------------------------------------------------------------
# 1. Imports + public surface
# ---------------------------------------------------------------------------


class TestEventBusImports:
    """EventBus is reachable from canonical and convenience paths."""

    def test_import_from_bus_module(self):
        """``from bonfire.events.bus import EventBus`` works."""
        assert EventBus is not None

    def test_import_from_events_package(self):
        """``from bonfire.events import EventBus`` works (re-export)."""
        assert _ReexportedEventBus is not None

    def test_events_package_reexports_bonfire_event(self):
        """``bonfire.events`` re-exports ``BonfireEvent`` for consumer convenience."""
        assert _ReexportedBonfireEvent is BonfireEvent

    def test_reexport_is_same_eventbus_class(self):
        """The package-level ``EventBus`` is the same symbol as ``bus.EventBus``."""
        assert _ReexportedEventBus is EventBus


# ---------------------------------------------------------------------------
# 2. Construction
# ---------------------------------------------------------------------------


class TestEventBusConstruction:
    """EventBus() creates an empty bus with a zeroed counter."""

    def test_creates_instance(self):
        bus = EventBus()
        assert bus is not None

    def test_construction_takes_no_required_arguments(self):
        """Zero-argument construction is the documented surface."""
        bus = EventBus()
        assert isinstance(bus, EventBus)

    def test_two_instances_are_independent(self):
        """Each bus maintains its own sequence counter and subscriber lists."""
        bus_a = EventBus()
        bus_b = EventBus()
        assert bus_a is not bus_b

    async def test_initial_sequence_is_zero_observed_via_first_emit(self):
        """The internal counter starts at 0; the first emit stamps sequence=1."""
        bus = EventBus()
        received: list[StageStarted] = []

        async def handler(event: StageStarted) -> None:
            received.append(event)

        bus.subscribe(StageStarted, handler)
        await bus.emit(_stage_started())
        assert received[0].sequence == 1


# ---------------------------------------------------------------------------
# 3. Typed subscribe + emit — handler receives matching events
# ---------------------------------------------------------------------------


class TestTypedSubscribe:
    """subscribe(type, handler) delivers matching events."""

    async def test_typed_subscriber_receives_matching_event(self):
        bus = EventBus()
        received: list[StageStarted] = []

        async def handler(event: StageStarted) -> None:
            received.append(event)

        bus.subscribe(StageStarted, handler)
        await bus.emit(_stage_started(stage_name="warrior"))

        assert len(received) == 1
        assert received[0].stage_name == "warrior"

    async def test_handler_receives_event_with_all_fields(self):
        bus = EventBus()
        received: list[StageCompleted] = []

        async def handler(event: StageCompleted) -> None:
            received.append(event)

        bus.subscribe(StageCompleted, handler)
        await bus.emit(_stage_completed(cost_usd=0.42, duration_seconds=7.1))

        assert received[0].cost_usd == 0.42
        assert received[0].duration_seconds == 7.1

    async def test_multiple_types_each_filtered(self):
        """Two typed subscribers each receive only their own type."""
        bus = EventBus()
        stages: list[StageStarted] = []
        pipelines: list[PipelineStarted] = []

        async def on_stage(event: StageStarted) -> None:
            stages.append(event)

        async def on_pipeline(event: PipelineStarted) -> None:
            pipelines.append(event)

        bus.subscribe(StageStarted, on_stage)
        bus.subscribe(PipelineStarted, on_pipeline)

        await bus.emit(_stage_started())
        await bus.emit(_pipeline_started())

        assert len(stages) == 1
        assert len(pipelines) == 1


# ---------------------------------------------------------------------------
# 4. Exact-type filter — type(event) is event_type, NOT isinstance
# ---------------------------------------------------------------------------


class TestExactTypeFilter:
    """Bus uses ``type(event) is event_type`` — no polymorphic dispatch."""

    async def test_base_handler_does_not_receive_subclass(self):
        """Handler registered for BonfireEvent does NOT receive StageStarted.

        Per the v1 docstring: ``type(event) is event_type``. Subclasses do
        not trigger parent-type handlers. Use subscribe_all for
        receive-everything semantics.
        """
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe(BonfireEvent, handler)
        await bus.emit(_stage_started())

        assert received == []

    async def test_unrelated_type_does_not_deliver(self):
        bus = EventBus()
        received: list[StageStarted] = []

        async def handler(event: StageStarted) -> None:
            received.append(event)

        bus.subscribe(StageStarted, handler)
        await bus.emit(_pipeline_started())

        assert received == []

    async def test_sibling_types_isolated(self):
        """StageStarted and StageCompleted are siblings; handlers do not cross."""
        bus = EventBus()
        stage_started: list[StageStarted] = []
        stage_completed: list[StageCompleted] = []

        async def on_started(event: StageStarted) -> None:
            stage_started.append(event)

        async def on_completed(event: StageCompleted) -> None:
            stage_completed.append(event)

        bus.subscribe(StageStarted, on_started)
        bus.subscribe(StageCompleted, on_completed)

        await bus.emit(_stage_started())
        await bus.emit(_stage_completed())

        assert len(stage_started) == 1
        assert len(stage_completed) == 1


# ---------------------------------------------------------------------------
# 5. Global subscribers — subscribe_all receives every event
# ---------------------------------------------------------------------------


class TestGlobalSubscribe:
    """subscribe_all delivers every event regardless of type."""

    async def test_global_receives_multiple_types(self):
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)

        await bus.emit(_stage_started())
        await bus.emit(_pipeline_started())
        await bus.emit(_stage_completed())

        assert len(received) == 3
        event_types = [e.event_type for e in received]
        assert event_types == ["stage.started", "pipeline.started", "stage.completed"]

    async def test_global_receives_when_no_typed_registered(self):
        """Global delivery does not require a typed subscriber for the same type."""
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(_stage_started())

        assert len(received) == 1

    async def test_multiple_global_subscribers_all_receive(self):
        bus = EventBus()
        a: list[BonfireEvent] = []
        b: list[BonfireEvent] = []

        async def handler_a(event: BonfireEvent) -> None:
            a.append(event)

        async def handler_b(event: BonfireEvent) -> None:
            b.append(event)

        bus.subscribe_all(handler_a)
        bus.subscribe_all(handler_b)
        await bus.emit(_stage_started())

        assert len(a) == 1
        assert len(b) == 1


# ---------------------------------------------------------------------------
# 6. C7 ordering — typed always fires before global
# ---------------------------------------------------------------------------


class TestC7Ordering:
    """Per C7: typed handlers always fire BEFORE global handlers."""

    async def test_typed_before_global_when_global_registered_first(self):
        """Registration order does NOT trump C7 — typed still fires first."""
        bus = EventBus()
        order: list[str] = []

        async def typed_h(event: StageStarted) -> None:
            order.append("typed")

        async def global_h(event: BonfireEvent) -> None:
            order.append("global")

        # Register global FIRST deliberately.
        bus.subscribe_all(global_h)
        bus.subscribe(StageStarted, typed_h)

        await bus.emit(_stage_started())
        assert order == ["typed", "global"]

    async def test_all_typed_before_any_global(self):
        """Two typed + two global, interleaved registration — both typed first."""
        bus = EventBus()
        order: list[str] = []

        async def t1(event: StageStarted) -> None:
            order.append("t1")

        async def t2(event: StageStarted) -> None:
            order.append("t2")

        async def g1(event: BonfireEvent) -> None:
            order.append("g1")

        async def g2(event: BonfireEvent) -> None:
            order.append("g2")

        # Intentionally scrambled registration.
        bus.subscribe_all(g1)
        bus.subscribe(StageStarted, t1)
        bus.subscribe_all(g2)
        bus.subscribe(StageStarted, t2)

        await bus.emit(_stage_started())

        # Typed tier first (registration order within tier), then global tier.
        assert order == ["t1", "t2", "g1", "g2"]

    async def test_typed_registration_order_preserved(self):
        """Within the typed tier, handlers fire in registration order."""
        bus = EventBus()
        order: list[str] = []

        async def first(event: StageStarted) -> None:
            order.append("first")

        async def second(event: StageStarted) -> None:
            order.append("second")

        async def third(event: StageStarted) -> None:
            order.append("third")

        bus.subscribe(StageStarted, first)
        bus.subscribe(StageStarted, second)
        bus.subscribe(StageStarted, third)

        await bus.emit(_stage_started())

        assert order == ["first", "second", "third"]

    async def test_global_registration_order_preserved(self):
        """Within the global tier, handlers fire in registration order."""
        bus = EventBus()
        order: list[str] = []

        async def g1(event: BonfireEvent) -> None:
            order.append("g1")

        async def g2(event: BonfireEvent) -> None:
            order.append("g2")

        async def g3(event: BonfireEvent) -> None:
            order.append("g3")

        bus.subscribe_all(g1)
        bus.subscribe_all(g2)
        bus.subscribe_all(g3)

        await bus.emit(_stage_started())

        assert order == ["g1", "g2", "g3"]


# ---------------------------------------------------------------------------
# 7. Sequential execution — one handler at a time, never concurrent
# ---------------------------------------------------------------------------


class TestSequentialAsyncExecution:
    """Handlers are awaited sequentially — C7 correctness over performance."""

    async def test_slow_handler_blocks_fast_handler(self):
        """Fast handler must not interleave with a slow handler that precedes it."""
        bus = EventBus()
        log: list[str] = []

        async def slow(event: StageStarted) -> None:
            log.append("slow-start")
            await asyncio.sleep(0.03)
            log.append("slow-end")

        async def fast(event: StageStarted) -> None:
            log.append("fast-start")
            log.append("fast-end")

        bus.subscribe(StageStarted, slow)
        bus.subscribe(StageStarted, fast)

        await bus.emit(_stage_started())

        # Strict sequential: slow completes before fast starts.
        assert log == ["slow-start", "slow-end", "fast-start", "fast-end"]

    async def test_emit_awaits_all_handlers_before_returning(self):
        """emit() does not resolve until the last handler has returned."""
        bus = EventBus()
        completed: list[bool] = []

        async def handler(event: StageStarted) -> None:
            await asyncio.sleep(0.02)
            completed.append(True)

        bus.subscribe(StageStarted, handler)
        await bus.emit(_stage_started())

        # The handler body must have finished when await returns.
        assert completed == [True]

    async def test_typed_completes_before_global_runs(self):
        """Global handlers see the world after typed handlers have fully completed."""
        bus = EventBus()
        log: list[str] = []

        async def typed_slow(event: StageStarted) -> None:
            log.append("typed-start")
            await asyncio.sleep(0.02)
            log.append("typed-end")

        async def global_h(event: BonfireEvent) -> None:
            log.append("global-run")

        bus.subscribe(StageStarted, typed_slow)
        bus.subscribe_all(global_h)

        await bus.emit(_stage_started())

        assert log == ["typed-start", "typed-end", "global-run"]

    async def test_concurrent_emits_produce_monotonic_sequences(self):
        """Two concurrent emits still produce monotonic stamps.

        The sequential-per-emit contract guarantees that within a single
        emit, handlers do not interleave. The event loop is free to
        schedule emit-A vs emit-B work; we assert only monotonic stamping.
        """
        bus = EventBus()
        seen_sequences: list[int] = []

        async def handler(event: BonfireEvent) -> None:
            seen_sequences.append(event.sequence)

        bus.subscribe_all(handler)

        await asyncio.gather(
            bus.emit(_stage_started()),
            bus.emit(_pipeline_started()),
        )

        # Sequence counter is monotonic: exactly {1, 2}, regardless of order.
        assert sorted(seen_sequences) == [1, 2]


# ---------------------------------------------------------------------------
# 8. Sequence stamping — monotonic, via model_copy, original never mutated
# ---------------------------------------------------------------------------


class TestSequenceStamping:
    """The bus stamps a monotonic sequence on each emission."""

    async def test_first_emit_stamps_one(self):
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(_stage_started(sequence=0))

        assert received[0].sequence == 1

    async def test_successive_emits_increment(self):
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        for _ in range(5):
            await bus.emit(_stage_started())

        assert [e.sequence for e in received] == [1, 2, 3, 4, 5]

    async def test_sequence_counter_is_global_across_types(self):
        """A single monotonic counter spans ALL event types."""
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(_stage_started())
        await bus.emit(_pipeline_started())
        await bus.emit(_stage_completed())

        assert [e.sequence for e in received] == [1, 2, 3]

    async def test_stamp_overwrites_caller_provided_value(self):
        """Bus authority wins — caller's sequence field is replaced."""
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(_stage_started(sequence=999))

        assert received[0].sequence == 1

    async def test_original_event_is_not_mutated(self):
        """BonfireEvent is frozen; the bus must never mutate inputs."""
        bus = EventBus()

        async def noop(event: BonfireEvent) -> None:
            pass

        bus.subscribe_all(noop)

        original = _stage_started(sequence=0)
        await bus.emit(original)

        assert original.sequence == 0

    async def test_handler_receives_stamped_copy_not_original(self):
        """The handler's argument is the stamped copy, not ``is`` the original."""
        bus = EventBus()
        captured: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            captured.append(event)

        bus.subscribe_all(handler)

        original = _stage_started(sequence=0)
        await bus.emit(original)

        assert captured[0] is not original
        assert captured[0].sequence == 1
        assert original.sequence == 0

    async def test_all_handlers_receive_same_sequence_value(self):
        """Typed and global handlers see the same sequence stamp (one copy per emit)."""
        bus = EventBus()
        typed_seq: list[int] = []
        global_seq: list[int] = []

        async def typed_h(event: StageStarted) -> None:
            typed_seq.append(event.sequence)

        async def global_h(event: BonfireEvent) -> None:
            global_seq.append(event.sequence)

        bus.subscribe(StageStarted, typed_h)
        bus.subscribe_all(global_h)
        await bus.emit(_stage_started())

        assert typed_seq == [1]
        assert global_seq == [1]

    async def test_stamped_copy_preserves_other_fields(self):
        """model_copy only updates sequence — other fields are preserved."""
        bus = EventBus()
        received: list[StageCompleted] = []

        async def handler(event: StageCompleted) -> None:
            received.append(event)

        bus.subscribe(StageCompleted, handler)
        original = _stage_completed(
            session_id="xyz",
            stage_name="sage",
            agent_name="sage-k",
            duration_seconds=99.0,
            cost_usd=1.23,
        )
        await bus.emit(original)

        assert received[0].session_id == "xyz"
        assert received[0].stage_name == "sage"
        assert received[0].agent_name == "sage-k"
        assert received[0].duration_seconds == 99.0
        assert received[0].cost_usd == 1.23
        assert received[0].event_id == original.event_id


# ---------------------------------------------------------------------------
# 9. Consumer isolation — one failing handler does not break others
# ---------------------------------------------------------------------------


class TestConsumerIsolation:
    """Handler exceptions are trapped; peer handlers still execute."""

    async def test_first_typed_raises_second_still_fires(self):
        bus = EventBus()
        ran: list[str] = []

        async def broken(event: StageStarted) -> None:
            ran.append("broken")
            raise RuntimeError("kaboom")

        async def healthy(event: StageStarted) -> None:
            ran.append("healthy")

        bus.subscribe(StageStarted, broken)
        bus.subscribe(StageStarted, healthy)

        # emit must not raise — isolation is the whole point.
        await bus.emit(_stage_started())

        assert ran == ["broken", "healthy"]

    async def test_later_handler_raises_earlier_still_ran(self):
        bus = EventBus()
        ran: list[str] = []

        async def healthy(event: StageStarted) -> None:
            ran.append("healthy")

        async def broken(event: StageStarted) -> None:
            ran.append("broken")
            raise ValueError("boom")

        bus.subscribe(StageStarted, healthy)
        bus.subscribe(StageStarted, broken)

        await bus.emit(_stage_started())

        assert ran == ["healthy", "broken"]

    async def test_typed_exception_does_not_block_global(self):
        """A typed handler raising must not prevent global handlers from running."""
        bus = EventBus()
        ran: list[str] = []

        async def typed_broken(event: StageStarted) -> None:
            raise RuntimeError("typed blew up")

        async def global_h(event: BonfireEvent) -> None:
            ran.append("global")

        bus.subscribe(StageStarted, typed_broken)
        bus.subscribe_all(global_h)

        await bus.emit(_stage_started())

        assert ran == ["global"]

    async def test_global_exception_does_not_block_peer_global(self):
        bus = EventBus()
        ran: list[str] = []

        async def bad(event: BonfireEvent) -> None:
            raise RuntimeError("bad global")

        async def good(event: BonfireEvent) -> None:
            ran.append("good")

        bus.subscribe_all(bad)
        bus.subscribe_all(good)

        await bus.emit(_stage_started())

        assert ran == ["good"]

    async def test_emit_never_raises_even_if_all_handlers_fail(self):
        bus = EventBus()

        async def h1(event: BonfireEvent) -> None:
            raise RuntimeError("1")

        async def h2(event: BonfireEvent) -> None:
            raise ValueError("2")

        bus.subscribe_all(h1)
        bus.subscribe_all(h2)

        # Must not raise, must not propagate any exception.
        await bus.emit(_stage_started())

    async def test_handler_exception_is_logged(self, caplog: pytest.LogCaptureFixture):
        """Errors are logged (not re-raised) so operators can diagnose."""
        bus = EventBus()

        async def broken(event: StageStarted) -> None:
            raise RuntimeError("inspect me")

        bus.subscribe(StageStarted, broken)

        with caplog.at_level(logging.ERROR, logger="bonfire.events.bus"):
            await bus.emit(_stage_started())

        # Some log record must mention the failure, the exception text, or
        # attach exc_info. The caller's diagnostic signal is the assertion.
        assert any(
            "inspect me" in record.getMessage()
            or "failed" in record.getMessage().lower()
            or record.exc_info is not None
            for record in caplog.records
        )

    async def test_counter_still_advances_on_handler_failure(self):
        """A handler exception must not unroll the sequence counter."""
        bus = EventBus()
        received: list[int] = []

        async def broken(event: BonfireEvent) -> None:
            raise RuntimeError("nope")

        async def recorder(event: BonfireEvent) -> None:
            received.append(event.sequence)

        bus.subscribe_all(broken)
        bus.subscribe_all(recorder)

        await bus.emit(_stage_started())
        await bus.emit(_stage_started())

        assert received == [1, 2]


# ---------------------------------------------------------------------------
# 10. Edge cases — no subscribers, duplicates, empty paths
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Empty buses, no subscribers, double-registration, etc."""

    async def test_emit_with_no_subscribers_is_noop(self):
        bus = EventBus()
        # Should simply return — no error.
        await bus.emit(_stage_started())

    async def test_emit_with_no_matching_typed_and_no_global(self):
        bus = EventBus()

        async def handler(event: PipelineStarted) -> None:
            pass  # pragma: no cover

        bus.subscribe(PipelineStarted, handler)
        # StageStarted has no matching subscriber and no global — silent.
        await bus.emit(_stage_started())

    async def test_emit_with_no_subscribers_still_increments_sequence(self):
        """Even with zero subscribers, the sequence counter advances."""
        bus = EventBus()
        await bus.emit(_stage_started())
        await bus.emit(_stage_started())

        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(_stage_started())

        assert received[0].sequence == 3

    async def test_same_typed_handler_registered_twice_fires_twice(self):
        """Registration is list-based: duplicates fire both times."""
        bus = EventBus()
        calls: list[int] = []

        async def handler(event: StageStarted) -> None:
            calls.append(1)

        bus.subscribe(StageStarted, handler)
        bus.subscribe(StageStarted, handler)

        await bus.emit(_stage_started())

        assert len(calls) == 2

    async def test_same_global_handler_registered_twice_fires_twice(self):
        bus = EventBus()
        calls: list[int] = []

        async def handler(event: BonfireEvent) -> None:
            calls.append(1)

        bus.subscribe_all(handler)
        bus.subscribe_all(handler)

        await bus.emit(_stage_started())

        assert len(calls) == 2


# ---------------------------------------------------------------------------
# 11. Long session — state integrity across many emits
# ---------------------------------------------------------------------------


class TestLongSession:
    """Bus behavior under many emits with mixed subscribers."""

    async def test_thirty_emits_monotonic_sequence(self):
        bus = EventBus()
        received: list[int] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event.sequence)

        bus.subscribe_all(handler)
        for _ in range(30):
            await bus.emit(_stage_started())

        assert received == list(range(1, 31))

    async def test_mixed_types_and_subscribers_each_accounted(self):
        bus = EventBus()
        stages: list[StageStarted] = []
        pipelines: list[PipelineStarted] = []
        all_events: list[BonfireEvent] = []

        async def on_stage(event: StageStarted) -> None:
            stages.append(event)

        async def on_pipeline(event: PipelineStarted) -> None:
            pipelines.append(event)

        async def on_all(event: BonfireEvent) -> None:
            all_events.append(event)

        bus.subscribe(StageStarted, on_stage)
        bus.subscribe(PipelineStarted, on_pipeline)
        bus.subscribe_all(on_all)

        # 4 stages + 2 pipelines + 1 stage_completed = 7 global deliveries.
        await bus.emit(_stage_started())
        await bus.emit(_pipeline_started())
        await bus.emit(_stage_started())
        await bus.emit(_stage_started())
        await bus.emit(_pipeline_started())
        await bus.emit(_stage_started())
        await bus.emit(_stage_completed())

        assert len(stages) == 4
        assert len(pipelines) == 2
        assert len(all_events) == 7


# ---------------------------------------------------------------------------
# 12. Concrete event flow — representative downstream consumer path
# ---------------------------------------------------------------------------


class TestConcreteEventFlow:
    """Downstream-consumer representative flows — smoke for the bus contract."""

    async def test_cost_accrued_dispatches_through_bus(self):
        """A CostAccrued event round-trips through a typed handler."""
        bus = EventBus()
        received: list[CostAccrued] = []

        async def handler(event: CostAccrued) -> None:
            received.append(event)

        bus.subscribe(CostAccrued, handler)

        event = CostAccrued(
            session_id="sess-rt",
            sequence=0,
            amount_usd=0.42,
            source="knight",
            running_total_usd=1.12,
        )
        await bus.emit(event)

        assert len(received) == 1
        assert received[0].amount_usd == 0.42
        assert received[0].source == "knight"

    async def test_dispatch_completed_reaches_global_listener(self):
        """DispatchCompleted (key event for the cost consumer) is deliverable."""
        bus = EventBus()
        received: list[BonfireEvent] = []

        async def handler(event: BonfireEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)

        await bus.emit(
            DispatchCompleted(
                session_id="sess-rt",
                sequence=0,
                agent_name="scout-alpha",
                cost_usd=0.09,
                duration_seconds=5.0,
            )
        )

        assert len(received) == 1
        assert received[0].event_type == "dispatch.completed"

    async def test_stage_failed_reaches_typed_handler(self):
        """StageFailed is routed to its typed handler (used by display consumer)."""
        bus = EventBus()
        received: list[StageFailed] = []

        async def handler(event: StageFailed) -> None:
            received.append(event)

        bus.subscribe(StageFailed, handler)

        event = StageFailed(
            session_id="sess",
            sequence=0,
            stage_name="warrior",
            agent_name="w1",
            error_message="tests failed",
        )
        await bus.emit(event)

        assert received[0].error_message == "tests failed"

    async def test_pipeline_completed_sequence_captured(self):
        """PipelineCompleted carries through stamping end-to-end."""
        bus = EventBus()
        received: list[PipelineCompleted] = []

        async def handler(event: PipelineCompleted) -> None:
            received.append(event)

        bus.subscribe(PipelineCompleted, handler)

        # Warm up the counter.
        await bus.emit(_stage_started())
        await bus.emit(_stage_started())

        await bus.emit(
            PipelineCompleted(
                session_id="sess",
                sequence=0,
                total_cost_usd=1.23,
                duration_seconds=120.0,
                stages_completed=4,
            )
        )

        assert received[0].sequence == 3
        assert received[0].total_cost_usd == 1.23


# ---------------------------------------------------------------------------
# 13. Dependency constraints — bus.py imports only stdlib + models.events
# ---------------------------------------------------------------------------


class TestDependencyConstraints:
    """bus.py lives in the cold-side foundation — no heavy imports."""

    def test_bus_module_has_no_third_party_imports(self):
        import ast
        from pathlib import Path

        bus_path = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "events" / "bus.py"
        source = bus_path.read_text()
        tree = ast.parse(source)

        allowed_top_level = {
            "bonfire",  # internal
            "__future__",
            "typing",
            "collections",
            "asyncio",
            "abc",
            "dataclasses",
            "enum",
            "functools",
            "logging",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top in allowed_top_level, (
                        f"bus.py imports disallowed package: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top in allowed_top_level, f"bus.py imports disallowed package: {node.module}"

    def test_bus_does_not_import_pydantic_directly(self):
        """bus.py depends on BonfireEvent transitively, not pydantic directly.

        Keeps the hot-path cold-side of the boundary clean — pydantic lives
        with ``bonfire.models.events``; the bus only receives instances.
        """
        from pathlib import Path

        bus_path = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "events" / "bus.py"
        source = bus_path.read_text()

        assert "import pydantic" not in source
        assert "from pydantic" not in source
