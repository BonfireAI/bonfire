"""Tests for cost ledger models."""

from __future__ import annotations

from bonfire.cost.models import (
    AgentCost,
    DispatchRecord,
    PipelineRecord,
    SessionCost,
)


class TestDispatchRecord:
    def test_create_dispatch_record(self) -> None:
        record = DispatchRecord(
            timestamp=1712764321.0,
            session_id="ses_abc",
            agent_name="scout_innovative",
            cost_usd=0.09,
            duration_seconds=23.4,
        )
        assert record.type == "dispatch"
        assert record.agent_name == "scout_innovative"
        assert record.cost_usd == 0.09

    def test_dispatch_record_serialization_roundtrip(self) -> None:
        record = DispatchRecord(
            timestamp=1712764321.0,
            session_id="ses_abc",
            agent_name="warrior",
            cost_usd=0.04,
            duration_seconds=30.9,
        )
        json_str = record.model_dump_json()
        restored = DispatchRecord.model_validate_json(json_str)
        assert restored == record

    def test_dispatch_record_type_is_literal(self) -> None:
        record = DispatchRecord(
            timestamp=1712764321.0,
            session_id="ses_abc",
            agent_name="scout",
            cost_usd=0.01,
            duration_seconds=5.0,
        )
        data = record.model_dump()
        assert data["type"] == "dispatch"


class TestPipelineRecord:
    def test_create_pipeline_record(self) -> None:
        record = PipelineRecord(
            timestamp=1712764395.0,
            session_id="ses_abc",
            total_cost_usd=0.13,
            duration_seconds=54.3,
            stages_completed=2,
        )
        assert record.type == "pipeline"
        assert record.total_cost_usd == 0.13
        assert record.stages_completed == 2

    def test_pipeline_record_serialization_roundtrip(self) -> None:
        record = PipelineRecord(
            timestamp=1712764395.0,
            session_id="ses_abc",
            total_cost_usd=0.13,
            duration_seconds=54.3,
            stages_completed=2,
        )
        json_str = record.model_dump_json()
        restored = PipelineRecord.model_validate_json(json_str)
        assert restored == record


class TestSessionCost:
    def test_create_session_cost(self) -> None:
        dispatch = DispatchRecord(
            timestamp=1712764321.0,
            session_id="ses_abc",
            agent_name="scout",
            cost_usd=0.09,
            duration_seconds=23.4,
        )
        session = SessionCost(
            session_id="ses_abc",
            total_cost_usd=0.13,
            duration_seconds=54.3,
            dispatches=[dispatch],
            stages_completed=2,
            timestamp=1712764395.0,
        )
        assert session.session_id == "ses_abc"
        assert len(session.dispatches) == 1

    def test_date_property_returns_iso_format(self) -> None:
        # 2024-04-10 12:00:00 UTC = 1712750400.0
        session = SessionCost(
            session_id="ses_date",
            total_cost_usd=0.50,
            duration_seconds=100.0,
            dispatches=[],
            stages_completed=1,
            timestamp=1712750400.0,
        )
        assert session.date == "2024-04-10"

    def test_date_property_different_timestamp(self) -> None:
        # 2025-01-01 00:00:00 UTC = 1735689600.0
        session = SessionCost(
            session_id="ses_newyear",
            total_cost_usd=0.10,
            duration_seconds=10.0,
            dispatches=[],
            stages_completed=0,
            timestamp=1735689600.0,
        )
        assert session.date == "2025-01-01"


class TestAgentCost:
    def test_create_agent_cost(self) -> None:
        agent = AgentCost(
            agent_name="scout_innovative",
            total_cost_usd=1.82,
            dispatch_count=18,
            avg_cost_usd=0.10,
        )
        assert agent.agent_name == "scout_innovative"
        assert agent.dispatch_count == 18
