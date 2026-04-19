"""RED tests for bonfire.cost.consumer::CostLedgerConsumer — W5.7 transfer.

CostLedgerConsumer subscribes to DispatchCompleted and PipelineCompleted
events and appends JSONL records to a ledger file on disk. It is a
DIFFERENT seam from ``bonfire.events.consumers.cost::CostTracker`` (the
in-memory budget watcher). This ledger consumer is the persistence layer
that feeds the CostAnalyzer.

Target location after Warrior GREEN: ``src/bonfire/cost/consumer.py``.

Knight-A innovative lens: focus on filesystem edges the happy-path tests
miss — concurrent appenders, large bursts, existing-file idempotency,
parent-directory races, and timestamp preservation from the event.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.events.bus import EventBus
from bonfire.models.events import DispatchCompleted, PipelineCompleted

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "cost" / "cost_ledger.jsonl"


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def consumer(ledger_path: Path, bus: EventBus) -> CostLedgerConsumer:
    c = CostLedgerConsumer(ledger_path=ledger_path)
    c.register(bus)
    return c


# ---------------------------------------------------------------------------
# Canonical consumer suite — mirror of private v1 with rename.
# ---------------------------------------------------------------------------


class TestCostLedgerConsumer:
    async def test_writes_dispatch_record_on_dispatch_completed(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        event = DispatchCompleted(
            session_id="ses_001",
            sequence=1,
            agent_name="scout_innovative",
            cost_usd=0.09,
            duration_seconds=23.4,
        )
        await bus.emit(event)

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "dispatch"
        assert data["agent_name"] == "scout_innovative"
        assert data["cost_usd"] == 0.09
        assert data["session_id"] == "ses_001"

    async def test_writes_pipeline_record_on_pipeline_completed(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        event = PipelineCompleted(
            session_id="ses_001",
            sequence=2,
            total_cost_usd=0.13,
            duration_seconds=54.3,
            stages_completed=2,
        )
        await bus.emit(event)

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "pipeline"
        assert data["total_cost_usd"] == 0.13
        assert data["stages_completed"] == 2

    async def test_creates_parent_directories(self, bus: EventBus, tmp_path: Path) -> None:
        deep_path = tmp_path / "a" / "b" / "c" / "ledger.jsonl"
        consumer = CostLedgerConsumer(ledger_path=deep_path)
        consumer.register(bus)

        event = DispatchCompleted(
            session_id="ses_001",
            sequence=1,
            agent_name="scout",
            cost_usd=0.01,
            duration_seconds=1.0,
        )
        await bus.emit(event)

        assert deep_path.exists()
        assert len(deep_path.read_text().strip().split("\n")) == 1

    async def test_appends_multiple_records(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        for i in range(3):
            await bus.emit(
                DispatchCompleted(
                    session_id="ses_001",
                    sequence=i,
                    agent_name=f"agent_{i}",
                    cost_usd=0.01 * (i + 1),
                    duration_seconds=10.0,
                )
            )

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 3
        agents = [json.loads(line)["agent_name"] for line in lines]
        assert agents == ["agent_0", "agent_1", "agent_2"]

    async def test_dispatch_record_has_timestamp_from_event(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        event = DispatchCompleted(
            session_id="ses_001",
            sequence=1,
            agent_name="scout",
            cost_usd=0.05,
            duration_seconds=10.0,
        )
        await bus.emit(event)

        data = json.loads(ledger_path.read_text().strip())
        assert data["timestamp"] == event.timestamp


# ---------------------------------------------------------------------------
# Innovative lens — JSONL corruption, concurrent writers, and
# round-trip invariants.
#
# Lens rationale: the ledger file is shared state. Every guarantee the
# analyzer relies on (one-record-per-line, no partial writes, stable sort
# by timestamp, idempotent append) is a property the CONSUMER must
# maintain. If the consumer ever emits two records on one line, or drops
# the trailing newline, the analyzer breaks silently and every cost
# report that follows is wrong.
# ---------------------------------------------------------------------------


class TestInnovativeLedgerEdge:
    async def test_each_record_on_its_own_line(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """JSONL contract: exactly one JSON object per line, always ending
        in '\\n'. Violation would corrupt analyzer parsing for every
        record that follows.
        """
        for i in range(5):
            await bus.emit(
                DispatchCompleted(
                    session_id="s",
                    sequence=i,
                    agent_name=f"a{i}",
                    cost_usd=0.01,
                    duration_seconds=1.0,
                )
            )
        raw = ledger_path.read_text()
        assert raw.endswith("\n"), "ledger MUST always end with a newline"
        lines = raw.split("\n")
        # 5 content lines + 1 trailing empty from final '\n' → 6 entries
        non_empty = [ln for ln in lines if ln.strip()]
        assert len(non_empty) == 5
        # Each non-empty line MUST parse as a single complete JSON object.
        for ln in non_empty:
            obj = json.loads(ln)
            assert obj["type"] == "dispatch"

    async def test_ledger_appends_to_preexisting_file(
        self, bus: EventBus, ledger_path: Path
    ) -> None:
        """If the user already has a ledger (from an earlier session), a
        new consumer MUST append to it, not clobber it.
        """
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        preamble = (
            '{"type":"dispatch","timestamp":1.0,"session_id":"old","agent_name":"a",'
            '"cost_usd":0.1,"duration_seconds":1.0}\n'
        )
        ledger_path.write_text(preamble, encoding="utf-8")

        consumer = CostLedgerConsumer(ledger_path=ledger_path)
        consumer.register(bus)
        await bus.emit(
            DispatchCompleted(
                session_id="new",
                sequence=0,
                agent_name="b",
                cost_usd=0.2,
                duration_seconds=1.0,
            )
        )

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["session_id"] == "old"
        assert json.loads(lines[1])["session_id"] == "new"

    async def test_concurrent_emits_serialized_by_bus(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """EventBus awaits handlers sequentially. Even under
        asyncio.gather, every emitted event must produce exactly one line —
        no interleaving, no lost records.
        """
        events = [
            DispatchCompleted(
                session_id="ses",
                sequence=i,
                agent_name=f"agent_{i:03d}",
                cost_usd=0.01,
                duration_seconds=1.0,
            )
            for i in range(50)
        ]
        await asyncio.gather(*[bus.emit(e) for e in events])

        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 50
        # Every line is valid JSON with the expected fields.
        names = {json.loads(ln)["agent_name"] for ln in lines}
        assert names == {f"agent_{i:03d}" for i in range(50)}

    async def test_burst_of_events_no_line_corruption(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Under heavy burst, every single line MUST remain a complete
        JSON object. We inspect line-by-line, rejecting any that fails to
        parse — the kind of check that catches a flushed-mid-write bug.
        """
        for i in range(200):
            await bus.emit(
                DispatchCompleted(
                    session_id="burst",
                    sequence=i,
                    agent_name="agent",
                    cost_usd=0.001,
                    duration_seconds=0.1,
                )
            )
        raw = ledger_path.read_text()
        lines = [ln for ln in raw.split("\n") if ln]
        assert len(lines) == 200
        for ln in lines:
            obj = json.loads(ln)  # raises on any corruption
            assert obj["session_id"] == "burst"

    async def test_roundtrip_preserves_event_timestamp(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Event timestamps are assigned at emit time. The ledger MUST
        store that exact timestamp — not the write time — so ``all_records``
        can sort by causal order.
        """
        # Two events with hand-set timestamps (via the emit-seq model_copy
        # the bus preserves event.timestamp untouched).
        e1 = DispatchCompleted(
            session_id="s",
            sequence=0,
            agent_name="a",
            cost_usd=0.1,
            duration_seconds=1.0,
        )
        e2 = PipelineCompleted(
            session_id="s",
            sequence=1,
            total_cost_usd=0.1,
            duration_seconds=1.0,
            stages_completed=1,
        )
        await bus.emit(e1)
        await bus.emit(e2)
        lines = ledger_path.read_text().strip().split("\n")
        assert json.loads(lines[0])["timestamp"] == e1.timestamp
        assert json.loads(lines[1])["timestamp"] == e2.timestamp

    async def test_emit_with_zero_cost_still_written(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """A dispatch that costs 0 (cached, skipped, no-op agent) MUST still
        be persisted — downstream analytics care about count as well as
        cost.
        """
        await bus.emit(
            DispatchCompleted(
                session_id="s",
                sequence=0,
                agent_name="cached",
                cost_usd=0.0,
                duration_seconds=0.0,
            )
        )
        data = json.loads(ledger_path.read_text().strip())
        assert data["cost_usd"] == 0.0
        assert data["agent_name"] == "cached"

    async def test_two_consumers_on_same_ledger_both_append(
        self, bus: EventBus, ledger_path: Path
    ) -> None:
        """If (for reconfiguration, hot-reload, or a bug) two consumers
        subscribe to the same bus pointing at the same ledger, every event
        should produce TWO lines — idempotent append semantics, no file
        handle collision.
        """
        c1 = CostLedgerConsumer(ledger_path=ledger_path)
        c2 = CostLedgerConsumer(ledger_path=ledger_path)
        c1.register(bus)
        c2.register(bus)
        await bus.emit(
            DispatchCompleted(
                session_id="s",
                sequence=0,
                agent_name="a",
                cost_usd=0.1,
                duration_seconds=1.0,
            )
        )
        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 2
        # Both entries identical in payload (different consumers, same event).
        payloads = [json.loads(ln) for ln in lines]
        assert payloads[0]["agent_name"] == payloads[1]["agent_name"] == "a"

    async def test_unrelated_events_are_ignored(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """The consumer subscribes to exactly DispatchCompleted and
        PipelineCompleted. Other event types on the bus MUST NOT be
        written to the ledger.
        """
        from bonfire.models.events import CostAccrued, SessionStarted

        await bus.emit(SessionStarted(session_id="s", sequence=0, task="build", workflow="dual"))
        await bus.emit(
            CostAccrued(
                session_id="s",
                sequence=1,
                amount_usd=0.5,
                source="scout",
                running_total_usd=0.5,
            )
        )
        # Ledger file does not exist yet (consumer never fired).
        assert not ledger_path.exists() or ledger_path.read_text() == ""

    async def test_dispatch_then_pipeline_produces_two_typed_records(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """A single session normally emits N DispatchCompleted + 1
        PipelineCompleted. The ledger MUST contain records of both types,
        each with the correct Literal discriminator.
        """
        await bus.emit(
            DispatchCompleted(
                session_id="s",
                sequence=0,
                agent_name="a",
                cost_usd=0.1,
                duration_seconds=1.0,
            )
        )
        await bus.emit(
            PipelineCompleted(
                session_id="s",
                sequence=1,
                total_cost_usd=0.1,
                duration_seconds=1.0,
                stages_completed=1,
            )
        )
        lines = ledger_path.read_text().strip().split("\n")
        types = [json.loads(ln)["type"] for ln in lines]
        assert types == ["dispatch", "pipeline"]

    async def test_session_id_with_unusual_chars_roundtrips(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Session ids can contain dashes, underscores, digits — and in a
        bad deployment, even quotes or unicode. Whatever they contain,
        the JSONL line MUST stay parseable.
        """
        weird = 'ses-"quote"_2026\u00e9'
        await bus.emit(
            DispatchCompleted(
                session_id=weird,
                sequence=0,
                agent_name="a",
                cost_usd=0.1,
                duration_seconds=1.0,
            )
        )
        data = json.loads(ledger_path.read_text().strip())
        assert data["session_id"] == weird
