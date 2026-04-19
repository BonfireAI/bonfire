"""Tests for bonfire.session — SessionState and SessionPersistence.

RED phase: all tests fail with ImportError (bonfire.session does not exist yet).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from bonfire.models.events import (
    PipelineStarted,
    SessionEnded,
    SessionStarted,
    StageCompleted,
)

# ---------------------------------------------------------------------------
# 1. Imports (2)
# ---------------------------------------------------------------------------


class TestSessionImports:
    """bonfire.session exposes SessionState and SessionPersistence."""

    def test_import_session_state(self):
        from bonfire.session import SessionState

        assert SessionState is not None

    def test_import_session_persistence(self):
        from bonfire.session import SessionPersistence

        assert SessionPersistence is not None


# ---------------------------------------------------------------------------
# 2. SessionState init (2)
# ---------------------------------------------------------------------------


class TestSessionStateInit:
    """SessionState constructor and initial property values."""

    def test_init_stores_session_id_and_plan_name(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="my-plan", workflow_type="dual")
        assert state.session_id == "s1"
        assert state.plan_name == "my-plan"

    def test_init_starts_inactive_with_zero_cost(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        assert state.is_active is False
        assert state.total_cost_usd == 0.0
        assert state.stages_completed == 0


# ---------------------------------------------------------------------------
# 3. SessionState lifecycle (4)
# ---------------------------------------------------------------------------


class TestSessionStateLifecycle:
    """start(), record_stage(), end(), duration tracking."""

    def test_start_makes_active(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        assert state.is_active is True

    def test_record_stage_tracks_cost_and_count(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        state.record_stage("scout", 0.25)
        state.record_stage("knight", 0.50)
        assert state.total_cost_usd == pytest.approx(0.75)
        assert state.stages_completed == 2

    def test_end_makes_inactive(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        state.end(status="completed")
        assert state.is_active is False

    def test_duration_tracked_after_end(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        time.sleep(0.05)
        state.end()
        assert state.duration_seconds >= 0.04


# ---------------------------------------------------------------------------
# 4. SessionState to_dict (1)
# ---------------------------------------------------------------------------


class TestSessionStateToDict:
    """to_dict() serializes all fields."""

    def test_to_dict_contains_all_fields(self):
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        state.record_stage("scout", 0.10)
        state.end(status="completed")
        d = state.to_dict()
        assert d["session_id"] == "s1"
        assert d["plan_name"] == "p"
        assert d["workflow_type"] == "dual"
        assert d["is_active"] is False
        assert d["total_cost_usd"] == pytest.approx(0.10)
        assert d["stages_completed"] == 1
        assert "duration_seconds" in d


# ---------------------------------------------------------------------------
# 5. SessionPersistence append (3)
# ---------------------------------------------------------------------------


class TestSessionPersistenceAppend:
    """append_event() creates files and writes JSONL."""

    def test_append_creates_session_file(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        assert (tmp_path / "s1.jsonl").exists()

    def test_append_writes_valid_jsonl(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        lines = (tmp_path / "s1.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "session.started"

    def test_append_creates_directory_if_missing(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        nested = tmp_path / "deep" / "sessions"
        p = SessionPersistence(session_dir=nested)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        assert (nested / "s1.jsonl").exists()


# ---------------------------------------------------------------------------
# 6. SessionPersistence read (3)
# ---------------------------------------------------------------------------


class TestSessionPersistenceRead:
    """read_events() returns list of dicts from JSONL."""

    def test_read_returns_list_of_dicts(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        events = p.read_events("s1")
        assert isinstance(events, list)
        assert len(events) == 1
        assert isinstance(events[0], dict)

    def test_read_raises_for_missing_session(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            p.read_events("nonexistent")

    def test_read_preserves_multiple_events(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        e1 = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        e2 = StageCompleted(
            session_id="s1",
            sequence=1,
            stage_name="scout",
            agent_name="scout-1",
            duration_seconds=5.0,
            cost_usd=0.25,
        )
        p.append_event("s1", e1)
        p.append_event("s1", e2)
        events = p.read_events("s1")
        assert len(events) == 2
        assert events[0]["event_type"] == "session.started"
        assert events[1]["event_type"] == "stage.completed"


# ---------------------------------------------------------------------------
# 7. SessionPersistence list (2)
# ---------------------------------------------------------------------------


class TestSessionPersistenceList:
    """list_sessions() returns session IDs from .jsonl filenames."""

    def test_list_returns_session_ids_sorted(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        for sid in ("beta", "alpha", "gamma"):
            event = SessionStarted(session_id=sid, sequence=0, task="t", workflow="w")
            p.append_event(sid, event)
        sessions = p.list_sessions()
        assert sessions == ["alpha", "beta", "gamma"]

    def test_list_empty_dir_returns_empty(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        assert p.list_sessions() == []


# ---------------------------------------------------------------------------
# 8. SessionPersistence session_exists (1)
# ---------------------------------------------------------------------------


class TestSessionPersistenceExists:
    """session_exists() checks for .jsonl file."""

    def test_exists_true_after_append_false_before(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        assert p.session_exists("s1") is False
        event = SessionStarted(session_id="s1", sequence=0, task="t", workflow="w")
        p.append_event("s1", event)
        assert p.session_exists("s1") is True


# ---------------------------------------------------------------------------
# 9. Round-trip (2)
# ---------------------------------------------------------------------------


class TestSessionRoundTrip:
    """Append then read preserves event data faithfully."""

    def test_roundtrip_preserves_all_fields(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = PipelineStarted(session_id="s1", sequence=0, plan_name="my-plan", budget_usd=10.0)
        p.append_event("s1", event)
        events = p.read_events("s1")
        assert events[0]["plan_name"] == "my-plan"
        assert events[0]["budget_usd"] == 10.0
        assert events[0]["event_id"] == event.event_id

    def test_roundtrip_multiple_event_types(self, tmp_path: Path):
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        e1 = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        e2 = SessionEnded(session_id="s1", sequence=1, status="completed", total_cost_usd=1.50)
        p.append_event("s1", e1)
        p.append_event("s1", e2)
        events = p.read_events("s1")
        assert len(events) == 2
        types = [e["event_type"] for e in events]
        assert types == ["session.started", "session.ended"]
        assert events[1]["total_cost_usd"] == 1.50
