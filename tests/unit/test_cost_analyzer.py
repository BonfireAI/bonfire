"""Tests for CostAnalyzer."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bonfire.cost.analyzer import CostAnalyzer
from bonfire.cost.models import DispatchRecord, PipelineRecord

if TYPE_CHECKING:
    from pathlib import Path


def _write_records(path: Path, records: list[DispatchRecord | PipelineRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "cost_ledger.jsonl"


@pytest.fixture
def sample_records() -> list[DispatchRecord | PipelineRecord]:
    return [
        DispatchRecord(
            timestamp=1000.0,
            session_id="ses_001",
            agent_name="scout",
            cost_usd=0.09,
            duration_seconds=20.0,
        ),
        DispatchRecord(
            timestamp=1001.0,
            session_id="ses_001",
            agent_name="warrior",
            cost_usd=0.04,
            duration_seconds=30.0,
        ),
        PipelineRecord(
            timestamp=1002.0,
            session_id="ses_001",
            total_cost_usd=0.13,
            duration_seconds=54.3,
            stages_completed=2,
        ),
        DispatchRecord(
            timestamp=2000.0,
            session_id="ses_002",
            agent_name="scout",
            cost_usd=0.15,
            duration_seconds=25.0,
        ),
        DispatchRecord(
            timestamp=2001.0,
            session_id="ses_002",
            agent_name="warrior",
            cost_usd=0.06,
            duration_seconds=35.0,
        ),
        DispatchRecord(
            timestamp=2002.0,
            session_id="ses_002",
            agent_name="wizard",
            cost_usd=0.20,
            duration_seconds=40.0,
        ),
        PipelineRecord(
            timestamp=2003.0,
            session_id="ses_002",
            total_cost_usd=0.41,
            duration_seconds=82.1,
            stages_completed=3,
        ),
    ]


class TestCumulativeCost:
    def test_cumulative_cost_sums_pipeline_records(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.54)

    def test_cumulative_cost_empty_ledger(self, ledger_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == 0.0

    def test_cumulative_cost_no_file(self, tmp_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=tmp_path / "nonexistent.jsonl")
        assert analyzer.cumulative_cost() == 0.0


class TestSessionCost:
    def test_session_cost_returns_dispatches_and_total(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        session = analyzer.session_cost("ses_001")
        assert session is not None
        assert session.total_cost_usd == pytest.approx(0.13)
        assert session.duration_seconds == pytest.approx(54.3)
        assert len(session.dispatches) == 2
        assert session.dispatches[0].agent_name == "scout"
        assert session.dispatches[1].agent_name == "warrior"

    def test_session_cost_unknown_session_returns_none(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.session_cost("ses_999") is None


class TestAgentCosts:
    def test_agent_costs_sorted_by_spend_descending(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        agents = analyzer.agent_costs()
        assert len(agents) == 3
        # scout: 0.09 + 0.15 = 0.24, warrior: 0.04 + 0.06 = 0.10, wizard: 0.20
        assert agents[0].agent_name == "scout"
        assert agents[0].total_cost_usd == pytest.approx(0.24)
        assert agents[0].dispatch_count == 2
        assert agents[0].avg_cost_usd == pytest.approx(0.12)
        assert agents[1].agent_name == "wizard"
        assert agents[1].total_cost_usd == pytest.approx(0.20)
        assert agents[2].agent_name == "warrior"

    def test_agent_costs_empty_ledger(self, ledger_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.agent_costs() == []


class TestAllSessions:
    def test_all_sessions_sorted_by_timestamp_descending(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 2
        assert sessions[0].session_id == "ses_002"
        assert sessions[1].session_id == "ses_001"

    def test_all_sessions_empty_ledger(self, ledger_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.all_sessions() == []

    def test_all_sessions_returns_correct_data_for_multiple_sessions(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()

        assert len(sessions) == 2

        # ses_002 first (higher timestamp)
        s2 = sessions[0]
        assert s2.session_id == "ses_002"
        assert s2.total_cost_usd == pytest.approx(0.41)
        assert s2.duration_seconds == pytest.approx(82.1)
        assert s2.stages_completed == 3
        assert len(s2.dispatches) == 3

        # ses_001 second
        s1 = sessions[1]
        assert s1.session_id == "ses_001"
        assert s1.total_cost_usd == pytest.approx(0.13)
        assert s1.duration_seconds == pytest.approx(54.3)
        assert s1.stages_completed == 2
        assert len(s1.dispatches) == 2


class TestMalformedLines:
    def test_skips_malformed_lines(self, ledger_path: Path) -> None:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            fh.write(
                '{"type":"dispatch","timestamp":1000.0,"session_id":"s1","agent_name":"a","cost_usd":0.1,"duration_seconds":5.0}\n'
            )
            fh.write("NOT VALID JSON\n")
            fh.write(
                '{"type":"pipeline","timestamp":1001.0,"session_id":"s1","total_cost_usd":0.1,"duration_seconds":5.0,"stages_completed":1}\n'
            )

        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.1)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 1
