"""RED tests for bonfire.cost.consumer::CostLedgerConsumer — W5.7 transfer.

CostLedgerConsumer subscribes to DispatchCompleted and PipelineCompleted
events and appends JSONL records to a ledger file on disk. It is a
DIFFERENT seam from ``bonfire.events.consumers.cost::CostTracker`` (the
in-memory budget watcher). This ledger consumer is the persistence layer
that feeds the CostAnalyzer.

Target location after Warrior GREEN: ``src/bonfire/cost/consumer.py``.
The canonical ``DEFAULT_LEDGER_PATH`` is ``~/.bonfire/cost/cost_ledger.jsonl``
(singular package name after the `costs` -> `cost` rename).

Canonical dedupe of two Knight lenses. Baseline mirrors private v1 plus
file-system adversarial edges the happy-path mirror does not cover:
concurrent emits, idempotent append to preexisting ledger, timestamp
preservation, and unrelated events filtered out.

``pyproject.toml`` sets ``asyncio_mode = "auto"``, so ``async def`` tests
are discovered automatically — no explicit ``@pytest.mark.asyncio`` mark.
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
    # Singular ``cost/`` subdir matches the DEFAULT_LEDGER_PATH convention.
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
# Adversarial ledger-write edges.
#
# The ledger file is shared state. Every guarantee the analyzer relies on
# (one-record-per-line, trailing newline, stable ordering, idempotent
# append) is a property the CONSUMER must maintain. A missed '\n' corrupts
# every record that follows; a clobber on register wipes history.
# ---------------------------------------------------------------------------


class TestConsumerEdge:
    async def test_each_record_on_its_own_line(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """JSONL contract: exactly one JSON object per line, every line
        ending in '\\n'. Violation corrupts analyzer parsing for every
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
        non_empty = [ln for ln in raw.split("\n") if ln.strip()]
        assert len(non_empty) == 5
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
        ``asyncio.gather``, every emitted event must produce exactly one
        line — no interleaving, no lost records.
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
        names = {json.loads(ln)["agent_name"] for ln in lines}
        assert names == {f"agent_{i:03d}" for i in range(50)}

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
        """Session ids span the full allow-list (alphanumerics + dash + underscore).

        Wave 9 Lane C tightened ``BonfireEvent.session_id`` to refuse
        path-traversal smuggling: only ``[a-zA-Z0-9_-]{1,64}`` plus the
        empty-string sentinel are accepted at the model layer. Quotes,
        unicode, slashes, and other shell-meaningful characters are
        rejected before the consumer ever sees the event. The remaining
        roundtrip contract: whatever the allow-list permits MUST stay
        parseable through the JSONL encoder.
        """
        weird = "ses-dashed_2026-XYZ_99"
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


# ---------------------------------------------------------------------------
# BON-351 — CostLedgerConsumer passes model field through (D7)
#
# DispatchCompleted carries a new ``model`` field (D4). The consumer reads
# it and persists it onto the DispatchRecord ledger row. Default is the
# empty string so old emitters / fixtures that don't set ``model=`` keep
# producing valid records (record.model == "").
# ---------------------------------------------------------------------------


class TestModelFieldPassthrough:
    """RED tests for BON-351 D7 — consumer threads ``DispatchCompleted.model``
    onto the persisted ``DispatchRecord.model`` field.
    """

    async def test_dispatch_completed_with_model_persisted(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Sage memo D7 — when the producer sets ``model`` on
        DispatchCompleted, the consumer MUST persist that exact string onto
        the ledger row. This is the producer-to-record round trip.
        """
        from bonfire.cost.models import DispatchRecord

        event = DispatchCompleted(
            session_id="ses_001",
            sequence=0,
            agent_name="warrior",
            cost_usd=0.05,
            duration_seconds=2.0,
            model="claude-haiku-4-5",
        )
        await bus.emit(event)

        line = ledger_path.read_text().strip().splitlines()[0]
        record = DispatchRecord.model_validate_json(line)
        assert record.model == "claude-haiku-4-5"

    async def test_dispatch_completed_without_model_persists_empty(
        self, consumer: CostLedgerConsumer, bus: EventBus, ledger_path: Path
    ) -> None:
        """Sage memo D7 — when the producer omits ``model`` (default = "")
        the persisted record carries an empty model string. This keeps the
        consumer's append-mode JSONL ledger gracefully accepting the wider
        shape without breaking legacy emitters.
        """
        from bonfire.cost.models import DispatchRecord

        event = DispatchCompleted(
            session_id="ses_002",
            sequence=0,
            agent_name="scout",
            cost_usd=0.01,
            duration_seconds=1.0,
            # model intentionally omitted -> defaults to ""
        )
        await bus.emit(event)

        line = ledger_path.read_text().strip().splitlines()[0]
        record = DispatchRecord.model_validate_json(line)
        assert record.model == ""
