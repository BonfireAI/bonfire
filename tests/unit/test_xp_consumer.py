"""RED tests for bonfire.xp.consumer — BON-344 W5.5 (CONTRACT-LOCKED).

Sage decision log: docs/audit/sage-decisions/bon-344-contract-lock-20260425T192700Z.md
Authority memo:   docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md

Floor (13 tests, per Sage §D6 Row 3): port v1 `test_xp_consumer.py` verbatim.
Pins auto-subscription to PipelineCompleted + PipelineFailed, calculator/tracker
delegation, XPAwarded/XPPenalty/XPRespawn emit contracts, and the bus-handler
regression guard from Session 033 (XP-shows-0 bug). Sage §D8 locks
XPConsumer.__init__ as keyword-only (tracker, calculator, bus) with
auto-subscribe; Sage §D8 locks on_pipeline_completed(event, *, success,
stages_failed) mixed signature. Appendix §2 locks PipelineFailed synthesis
path (compat PipelineCompleted, stages_failed=1).

Innovations adopted from Knight B (2 tests, drift-guards):
  * `test_emit_keyword_shape_locked` — exact-keyword-shape pin on outbound
    XPRespawn(session_id, sequence, checkpoint, reason). Specifically locks
    `checkpoint=""` per Appendix §6 + sequence forwarding from incoming event.
    Cites Sage §D8 + Appendix §6 + consumer.py:104-137.
  * `test_idempotent_handler_under_replay` — bus-replay produces independent
    emissions (no caching, no early-return). Direct mirror of Session 033
    regression where _handle_pipeline_completed once cached results. Cites
    Sage Appendix §2 + consumer.py:42-50.

Imports are RED — `bonfire.xp.consumer` does not exist until Warriors port
v1 source per Sage §D9.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bonfire.events.bus import EventBus
from bonfire.models.events import (
    PipelineCompleted,
    PipelineFailed,
    XPAwarded,
    XPPenalty,
    XPRespawn,
)
from bonfire.xp.calculator import XPCalculator, XPResult
from bonfire.xp.consumer import XPConsumer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION = "test-session-xp"
_SEQ = 0


def _pipeline_completed(**overrides) -> PipelineCompleted:
    defaults = {
        "session_id": _SESSION,
        "sequence": _SEQ,
        "total_cost_usd": 0.50,
        "duration_seconds": 120.0,
        "stages_completed": 5,
    }
    defaults.update(overrides)
    return PipelineCompleted(**defaults)


def _make_tracker_mock(
    *,
    total_xp: int = 500,
    level: tuple[int, str] = (1, "Ember"),
    level_changed: bool = False,
) -> MagicMock:
    """Create a mock XPTracker with sensible defaults."""
    tracker = MagicMock()
    tracker.total_xp.return_value = total_xp
    tracker.level.return_value = level
    tracker.level_changed.return_value = level_changed
    return tracker


def _make_calculator_result(
    *,
    xp_total: int = 100,
    respawn: bool = False,
    respawn_reason: str | None = None,
    xp_penalty: int = 0,
) -> XPResult:
    return XPResult(
        xp_base=100 if not respawn else 0,
        xp_bonus=0,
        xp_penalty=xp_penalty,
        xp_total=xp_total,
        respawn=respawn,
        respawn_reason=respawn_reason,
    )


# ---------------------------------------------------------------------------
# 1. Subscription
# ---------------------------------------------------------------------------


class TestXPConsumerSubscription:
    """XPConsumer auto-subscribes to PipelineCompleted on the bus."""

    def test_subscribes_to_pipeline_completed(self) -> None:
        """Creating XPConsumer registers a handler for PipelineCompleted."""
        bus = EventBus()
        tracker = _make_tracker_mock()
        calculator = XPCalculator()

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        # The bus should have a typed handler registered for PipelineCompleted
        assert PipelineCompleted in bus._typed
        assert len(bus._typed[PipelineCompleted]) == 1


# ---------------------------------------------------------------------------
# 2. Success path — XPAwarded
# ---------------------------------------------------------------------------


class TestXPConsumerSuccess:
    """PipelineCompleted with success=True emits XPAwarded."""

    @pytest.fixture()
    def setup(self):
        """Common setup for success tests."""
        bus = EventBus()
        tracker = _make_tracker_mock()
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=150)
        consumer = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        # Capture emitted XP events
        captured: list = []

        async def capture_xp_awarded(event: XPAwarded) -> None:
            captured.append(event)

        bus.subscribe(XPAwarded, capture_xp_awarded)

        return bus, tracker, calculator, consumer, captured

    @pytest.mark.asyncio()
    async def test_success_emits_xp_awarded(self, setup) -> None:
        """PipelineCompleted(success=True) causes XPAwarded to be emitted."""
        bus, tracker, calculator, consumer, captured = setup

        event = _pipeline_completed()
        await consumer.on_pipeline_completed(event, success=True, stages_failed=0)

        assert len(captured) == 1
        assert isinstance(captured[0], XPAwarded)

    @pytest.mark.asyncio()
    async def test_success_records_to_tracker(self, setup) -> None:
        """PipelineCompleted(success=True) records XP to tracker."""
        bus, tracker, calculator, consumer, captured = setup

        event = _pipeline_completed()
        await consumer.on_pipeline_completed(event, success=True, stages_failed=0)

        tracker.record.assert_called_once()
        call_args = tracker.record.call_args
        # Verify xp_total=150 was passed (positional or keyword)
        xp_val = call_args[1].get("xp_total", call_args[0][0])
        assert xp_val == 150
        # Verify success=True was passed
        success_val = call_args[1].get(
            "success",
            call_args[0][1] if len(call_args[0]) > 1 else None,
        )
        assert success_val is True


# ---------------------------------------------------------------------------
# 3. Failure path — XPPenalty
# ---------------------------------------------------------------------------


class TestXPConsumerFailurePenalty:
    """PipelineCompleted with failure and few stages emits XPPenalty."""

    @pytest.mark.asyncio()
    async def test_failure_few_stages_emits_penalty(self) -> None:
        """PipelineCompleted(success=False, stages_failed<3) emits XPPenalty."""
        bus = EventBus()
        tracker = _make_tracker_mock()
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=0, xp_penalty=20)

        consumer = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture_penalty(event: XPPenalty) -> None:
            captured.append(event)

        bus.subscribe(XPPenalty, capture_penalty)

        event = _pipeline_completed(stages_completed=2)
        await consumer.on_pipeline_completed(event, success=False, stages_failed=2)

        assert len(captured) == 1
        assert isinstance(captured[0], XPPenalty)


# ---------------------------------------------------------------------------
# 4. Respawn path — XPRespawn
# ---------------------------------------------------------------------------


class TestXPConsumerRespawn:
    """PipelineCompleted with many failures emits XPRespawn."""

    @pytest.mark.asyncio()
    async def test_failure_many_stages_emits_respawn(self) -> None:
        """PipelineCompleted(success=False, stages_failed>=3) emits XPRespawn."""
        bus = EventBus()
        tracker = _make_tracker_mock()
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(
            xp_total=0,
            respawn=True,
            respawn_reason="Too many stage failures: 4 stages failed",
        )

        consumer = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture_respawn(event: XPRespawn) -> None:
            captured.append(event)

        bus.subscribe(XPRespawn, capture_respawn)

        event = _pipeline_completed(stages_completed=1)
        await consumer.on_pipeline_completed(event, success=False, stages_failed=4)

        assert len(captured) == 1
        assert isinstance(captured[0], XPRespawn)
        assert "stages failed" in captured[0].reason.lower()


# ---------------------------------------------------------------------------
# 5. XP amount matches calculator
# ---------------------------------------------------------------------------


class TestXPConsumerCalculation:
    """Emitted event amounts must match XPCalculator output."""

    @pytest.mark.asyncio()
    async def test_xp_amount_matches_calculator(self) -> None:
        """The emitted XPAwarded event's amount matches calculator result."""
        bus = EventBus()
        tracker = _make_tracker_mock()
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=175)

        consumer = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture_awarded(event: XPAwarded) -> None:
            captured.append(event)

        bus.subscribe(XPAwarded, capture_awarded)

        event = _pipeline_completed()
        await consumer.on_pipeline_completed(event, success=True, stages_failed=0)

        assert len(captured) == 1
        assert captured[0].amount == 175


# ---------------------------------------------------------------------------
# 6. Level-up detection
# ---------------------------------------------------------------------------


class TestXPConsumerLevelUp:
    """Level transitions are detected and reported in emitted events."""

    @pytest.mark.asyncio()
    async def test_level_up_detected(self) -> None:
        """When tracker.level_changed() returns True, emitted event has level_up metadata."""
        bus = EventBus()
        tracker = _make_tracker_mock(
            total_xp=1000,
            level=(2, "Flame"),
            level_changed=True,
        )
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=200)

        consumer = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture_awarded(event: XPAwarded) -> None:
            captured.append(event)

        bus.subscribe(XPAwarded, capture_awarded)

        event = _pipeline_completed()
        await consumer.on_pipeline_completed(event, success=True, stages_failed=0)

        assert len(captured) == 1
        # The reason field should contain level-up information
        assert "level" in captured[0].reason.lower()
        assert "Flame" in captured[0].reason

    @pytest.mark.asyncio()
    async def test_no_level_up_when_same_level(self) -> None:
        """When tracker.level_changed() returns False, no level-up info in event."""
        bus = EventBus()
        tracker = _make_tracker_mock(
            total_xp=500,
            level=(1, "Ember"),
            level_changed=False,
        )
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=100)

        consumer = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture_awarded(event: XPAwarded) -> None:
            captured.append(event)

        bus.subscribe(XPAwarded, capture_awarded)

        event = _pipeline_completed()
        await consumer.on_pipeline_completed(event, success=True, stages_failed=0)

        assert len(captured) == 1
        # Should NOT contain level-up information
        reason_lower = captured[0].reason.lower()
        assert "level_up" not in reason_lower
        assert "leveled up" not in reason_lower


# ---------------------------------------------------------------------------
# 7. Bus handler delegation (regression test for XP-shows-0 bug)
# ---------------------------------------------------------------------------


class TestBusHandlerDelegation:
    """The bus handler must actually delegate to on_pipeline_completed.

    Regression: Session 033 discovered that _handle_pipeline_completed was
    a no-op, so the bus subscription existed but never drove XP calculation.
    """

    @pytest.mark.asyncio()
    async def test_bus_emit_triggers_xp_recording(self) -> None:
        """Emitting PipelineCompleted on the bus records XP via the tracker."""
        bus = EventBus()
        tracker = _make_tracker_mock(total_xp=0, level_changed=False)
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=100)

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        # Emit through the bus — NOT calling on_pipeline_completed directly
        await bus.emit(_pipeline_completed())

        # The tracker must have been called — proof the handler delegates
        tracker.record.assert_called_once()
        calculator.calculate.assert_called_once_with(
            success=True,
            stages_completed=5,
            stages_failed=0,
        )

    @pytest.mark.asyncio()
    async def test_bus_emit_emits_xp_awarded(self) -> None:
        """Bus-driven PipelineCompleted produces an XPAwarded event."""
        bus = EventBus()
        tracker = _make_tracker_mock(total_xp=0, level_changed=False)
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=100)

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture(event: XPAwarded) -> None:
            captured.append(event)

        bus.subscribe(XPAwarded, capture)

        await bus.emit(_pipeline_completed())

        assert len(captured) == 1
        assert captured[0].amount == 100


# ---------------------------------------------------------------------------
# 8. PipelineFailed wiring
# ---------------------------------------------------------------------------


class TestXPConsumerPipelineFailed:
    """PipelineFailed event triggers XP penalty via the bus."""

    def test_subscribes_to_pipeline_failed(self) -> None:
        """Creating XPConsumer registers a handler for PipelineFailed."""
        bus = EventBus()
        tracker = _make_tracker_mock()
        calculator = XPCalculator()

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        assert PipelineFailed in bus._typed
        assert len(bus._typed[PipelineFailed]) == 1

    @pytest.mark.asyncio()
    async def test_pipeline_failed_emits_penalty(self) -> None:
        """Emitting PipelineFailed on the bus produces an XPPenalty event."""
        bus = EventBus()
        tracker = _make_tracker_mock(total_xp=500, level_changed=False)
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=0, xp_penalty=25)

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list = []

        async def capture(event: XPPenalty) -> None:
            captured.append(event)

        bus.subscribe(XPPenalty, capture)

        await bus.emit(
            PipelineFailed(
                session_id=_SESSION,
                sequence=_SEQ,
                failed_stage="warrior",
                error_message="tests failed",
            )
        )

        assert len(captured) == 1
        assert isinstance(captured[0], XPPenalty)

    @pytest.mark.asyncio()
    async def test_pipeline_failed_records_to_tracker(self) -> None:
        """PipelineFailed drives XP recording through the tracker."""
        bus = EventBus()
        tracker = _make_tracker_mock(total_xp=500, level_changed=False)
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=0, xp_penalty=25)

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        await bus.emit(
            PipelineFailed(
                session_id=_SESSION,
                sequence=_SEQ,
                failed_stage="warrior",
                error_message="tests failed",
            )
        )

        tracker.record.assert_called_once()
        calculator.calculate.assert_called_once_with(
            success=False,
            stages_completed=0,
            stages_failed=1,
        )


# ---------------------------------------------------------------------------
# Adopted innovations (drift-guards)
# ---------------------------------------------------------------------------


class TestEmitKeywordShape:
    """Drift-guard: outbound bus emissions use the exact Sage-locked keyword sets.

    Sage §D8 (consumer.py:104-137) locks the three outbound emit-shapes:
        XPAwarded(session_id, sequence, amount, reason)
        XPPenalty(session_id, sequence, amount, reason)
        XPRespawn(session_id, sequence, checkpoint, reason)

    These tests pin the keyword identity AND the per-field source: amount comes
    from result.xp_total / result.xp_penalty (NOT mixed up), checkpoint defaults
    to "" per Appendix note 6, sequence + session_id are forwarded from the
    incoming event verbatim. If a Warrior swaps `amount` with `xp_total` on the
    Pydantic field, or forgets the empty-string checkpoint, this fires.
    """

    @pytest.mark.asyncio()
    async def test_emit_keyword_shape_locked(self) -> None:
        bus = EventBus()
        tracker = _make_tracker_mock(total_xp=300, level_changed=False)
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(
            xp_total=42,
            respawn=True,
            respawn_reason="3 failed",
            xp_penalty=10,
        )

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        respawn_captured: list[XPRespawn] = []

        async def capture(event: XPRespawn) -> None:
            respawn_captured.append(event)

        bus.subscribe(XPRespawn, capture)

        # Use a non-zero sequence to detect any drop/swap.
        nonzero_event = _pipeline_completed(sequence=99)
        consumer_inst = XPConsumer(tracker=tracker, calculator=calculator, bus=bus)
        await consumer_inst.on_pipeline_completed(
            nonzero_event, success=True, stages_failed=3
        )

        # Sage §D8: XPRespawn(session_id, sequence, checkpoint, reason)
        assert len(respawn_captured) >= 1
        emitted = respawn_captured[-1]
        # session_id forwarded verbatim
        assert emitted.session_id == _SESSION
        # sequence forwarded verbatim
        assert emitted.sequence == 99
        # checkpoint locked to "" per Appendix note 6 + consumer.py:108
        assert emitted.checkpoint == ""
        # reason wired from result.respawn_reason fallback path
        assert "3 failed" in emitted.reason


class TestIdempotentHandlerUnderReplay:
    """Drift-guard: bus replay produces independent emissions, not cached results.

    Sage Appendix note 2 + consumer.py:42-50 lock the auto-subscription pattern.
    Session 033's regression was that `_handle_pipeline_completed` once became a
    no-op (cached early-return), so emitting the same event twice produced ZERO
    XPAwarded events instead of two.

    This pin: emitting the SAME PipelineCompleted twice through `bus.emit` must
    produce EXACTLY two XPAwarded events with matching amounts. Both must trigger
    `tracker.record` and `calculator.calculate` — no internal short-circuit.
    """

    @pytest.mark.asyncio()
    async def test_idempotent_handler_under_replay(self) -> None:
        bus = EventBus()
        tracker = _make_tracker_mock(total_xp=0, level_changed=False)
        calculator = MagicMock(spec=XPCalculator)
        calculator.calculate.return_value = _make_calculator_result(xp_total=50)

        XPConsumer(tracker=tracker, calculator=calculator, bus=bus)

        captured: list[XPAwarded] = []

        async def capture(event: XPAwarded) -> None:
            captured.append(event)

        bus.subscribe(XPAwarded, capture)

        # Emit the same event twice through the bus.
        ev = _pipeline_completed()
        await bus.emit(ev)
        await bus.emit(ev)

        # Two independent emissions, not one (no cache, no early-return).
        assert len(captured) == 2, (
            f"Bus replay drift: expected 2 XPAwarded emissions for 2 emits, "
            f"got {len(captured)}. Session 033 regression — handler must not "
            f"cache or short-circuit on identical input."
        )
        assert captured[0].amount == 50
        assert captured[1].amount == 50
        # Both calls drove the tracker and calculator (no skip).
        assert tracker.record.call_count == 2
        assert calculator.calculate.call_count == 2
