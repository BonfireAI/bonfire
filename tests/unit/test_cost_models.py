"""RED tests for bonfire.cost.models — W5.7 transfer.

Cost ledger record types (DispatchRecord, PipelineRecord) and aggregation
result types (SessionCost, AgentCost). Pydantic models with strict type
literals, JSON round-trip fidelity, and the ``SessionCost.date`` derived
property (UTC ISO date from a float timestamp).

Knight-A innovative lens: edge cases on serialization, decimal/float
precision, timezone drift, and malformed construction.

All imports resolve to ``bonfire.cost.*`` (singular, renamed from private
``bonfire.costs.*``).
"""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from bonfire.cost.models import (
    AgentCost,
    DispatchRecord,
    PipelineRecord,
    SessionCost,
)

# ---------------------------------------------------------------------------
# DispatchRecord — baseline shape + round-trip
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# PipelineRecord — baseline shape + round-trip
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# SessionCost — aggregation result + derived ``date`` property
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# AgentCost — baseline shape
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Innovative lens — edges the conservative mirror does not cover.
#
# Lens rationale: the models are wire-format. Any drift in serialization,
# literal enforcement, or date derivation becomes a silent ledger corruption
# that compounds across every session. These tests pin the contract at the
# edges where float/string/UTC assumptions break.
# ---------------------------------------------------------------------------


class TestInnovativeModelsEdge:
    def test_dispatch_rejects_wrong_type_literal(self) -> None:
        """Attempting to forge a DispatchRecord with type='pipeline' must fail.

        The Literal discriminator is the ONLY thing keeping the two record
        families apart on the JSONL ledger. If it silently coerces, a
        cross-contaminated ledger is indistinguishable from a clean one.
        """
        with pytest.raises(ValidationError):
            DispatchRecord.model_validate(
                {
                    "type": "pipeline",
                    "timestamp": 1.0,
                    "session_id": "s",
                    "agent_name": "a",
                    "cost_usd": 0.1,
                    "duration_seconds": 1.0,
                }
            )

    def test_pipeline_rejects_wrong_type_literal(self) -> None:
        with pytest.raises(ValidationError):
            PipelineRecord.model_validate(
                {
                    "type": "dispatch",
                    "timestamp": 1.0,
                    "session_id": "s",
                    "total_cost_usd": 0.1,
                    "duration_seconds": 1.0,
                    "stages_completed": 1,
                }
            )

    def test_dispatch_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            DispatchRecord.model_validate(
                {
                    "type": "dispatch",
                    "timestamp": 1.0,
                    "session_id": "s",
                    # agent_name missing
                    "cost_usd": 0.1,
                    "duration_seconds": 1.0,
                }
            )

    def test_pipeline_stages_completed_must_be_int_not_float(self) -> None:
        """stages_completed is an int; ``2.7`` would silently truncate to 2
        under loose coercion. Pydantic v2 in strict-enough mode rejects it;
        if it does coerce, we at least want the value stored as an int
        (never 2.7 smuggled past the schema).
        """
        try:
            rec = PipelineRecord(
                timestamp=1.0,
                session_id="s",
                total_cost_usd=0.1,
                duration_seconds=1.0,
                stages_completed=2.7,  # type: ignore[arg-type]
            )
        except ValidationError:
            return
        # If coercion is allowed, it MUST produce a real int (no float leak).
        assert isinstance(rec.stages_completed, int)
        assert rec.stages_completed in (2, 3)

    def test_dispatch_json_roundtrip_preserves_microsecond_timestamp(self) -> None:
        """Timestamps carry millisecond/microsecond precision in practice.
        Round-tripping through JSON must preserve them byte-for-byte so the
        analyzer's sort-by-timestamp stays stable.
        """
        ts = 1712764321.123456
        record = DispatchRecord(
            timestamp=ts,
            session_id="s",
            agent_name="a",
            cost_usd=0.00001,
            duration_seconds=0.001,
        )
        restored = DispatchRecord.model_validate_json(record.model_dump_json())
        assert restored.timestamp == ts
        assert restored.cost_usd == 0.00001

    def test_dispatch_accepts_zero_cost_and_zero_duration(self) -> None:
        """Zero-cost dispatches happen (cached responses, no-op agents).
        They must be representable — not rejected as 'pointless'."""
        record = DispatchRecord(
            timestamp=1.0,
            session_id="s",
            agent_name="a",
            cost_usd=0.0,
            duration_seconds=0.0,
        )
        assert record.cost_usd == 0.0
        assert record.duration_seconds == 0.0

    def test_dispatch_json_is_valid_jsonl_single_line(self) -> None:
        """Ledger format is JSONL — each record MUST serialize to a single
        line. An embedded newline inside the JSON would corrupt every
        subsequent record's line number.
        """
        record = DispatchRecord(
            timestamp=1.0,
            session_id="ses\twith\ttabs",
            agent_name="agent\nwith\nnewlines",
            cost_usd=0.1,
            duration_seconds=1.0,
        )
        line = record.model_dump_json()
        assert "\n" not in line, "JSONL record leaked a raw newline"
        # And it must still parse as JSON with the escapes preserved.
        parsed = json.loads(line)
        assert parsed["agent_name"] == "agent\nwith\nnewlines"

    def test_session_cost_date_is_utc_not_local(self) -> None:
        """``SessionCost.date`` MUST be UTC. 1712750399.0 is
        2024-04-10 11:59:59 UTC — which in UTC+14 would roll to 2024-04-11
        and in UTC-12 would roll back to 2024-04-09. A local-tz bug here
        fans out into every daily cost report.
        """
        # 2024-04-10 11:59:59 UTC
        session = SessionCost(
            session_id="s",
            total_cost_usd=0.0,
            duration_seconds=0.0,
            dispatches=[],
            stages_completed=0,
            timestamp=1712750399.0,
        )
        assert session.date == "2024-04-10"

    def test_session_cost_date_at_utc_midnight_boundary(self) -> None:
        """Exactly-midnight UTC must land on the new day, not the previous."""
        # 2024-04-10 00:00:00 UTC = 1712707200.0
        session = SessionCost(
            session_id="s",
            total_cost_usd=0.0,
            duration_seconds=0.0,
            dispatches=[],
            stages_completed=0,
            timestamp=1712707200.0,
        )
        assert session.date == "2024-04-10"

    def test_agent_cost_avg_nonnegative_and_finite(self) -> None:
        """A NaN or infinite avg_cost_usd would poison every downstream sort
        and display. The model doesn't enforce it, but if someone builds a
        bad AgentCost by hand we want at least to round-trip faithfully so
        the bug is loud rather than silent.
        """
        agent = AgentCost(
            agent_name="a",
            total_cost_usd=0.0,
            dispatch_count=0,
            avg_cost_usd=0.0,
        )
        assert math.isfinite(agent.avg_cost_usd)
        assert agent.avg_cost_usd >= 0.0
        # Round-trip still clean.
        restored = AgentCost.model_validate_json(agent.model_dump_json())
        assert restored == agent
