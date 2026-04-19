"""Tests for CostLedgerConsumer."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — used at runtime in fixtures

import pytest

from bonfire.cost.consumer import CostLedgerConsumer
from bonfire.events.bus import EventBus
from bonfire.models.events import DispatchCompleted, PipelineCompleted


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


class TestCostLedgerConsumer:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
