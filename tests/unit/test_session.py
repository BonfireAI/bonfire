"""RED tests for bonfire.session — SessionState + SessionPersistence.

Two tightly-scoped seams:

- ``SessionState`` — mutable, in-memory. Tracks ``is_active``, cumulative
  ``total_cost_usd``, ``stages_completed``, and monotonic ``duration_seconds``.
  Lifecycle: ``start()`` → ``record_stage(name, cost)`` × N → ``end(status)``.
  Serialize via ``to_dict()``.
- ``SessionPersistence`` — append-only JSONL storage for BonfireEvent
  objects, one file per session id (``<session_id>.jsonl``). Supports
  ``append_event``, ``read_events``, ``list_sessions``, ``session_exists``.

Knight-A innovative lens: persistence round-trip with weird characters,
stable sort across many sessions, duration monotonicity, status
transitions, and tolerance to nested session_dir creation under races.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from bonfire.models.events import (
    DispatchCompleted,
    PipelineStarted,
    SessionEnded,
    SessionStarted,
    StageCompleted,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Imports (must resolve after Warrior GREEN)
# ---------------------------------------------------------------------------


class TestSessionImports:
    def test_import_session_state(self) -> None:
        from bonfire.session import SessionState

        assert SessionState is not None

    def test_import_session_persistence(self) -> None:
        from bonfire.session import SessionPersistence

        assert SessionPersistence is not None


# ---------------------------------------------------------------------------
# SessionState — init + lifecycle
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_init_stores_session_id_and_plan_name(self) -> None:
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="my-plan", workflow_type="dual")
        assert state.session_id == "s1"
        assert state.plan_name == "my-plan"
        assert state.workflow_type == "dual"

    def test_init_starts_inactive_with_zero_cost(self) -> None:
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        assert state.is_active is False
        assert state.total_cost_usd == 0.0
        assert state.stages_completed == 0

    def test_start_makes_active(self) -> None:
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        assert state.is_active is True

    def test_record_stage_tracks_cost_and_count(self) -> None:
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        state.record_stage("scout", 0.25)
        state.record_stage("knight", 0.50)
        assert state.total_cost_usd == pytest.approx(0.75)
        assert state.stages_completed == 2

    def test_end_makes_inactive(self) -> None:
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        state.end(status="completed")
        assert state.is_active is False

    def test_duration_tracked_after_end(self) -> None:
        from bonfire.session import SessionState

        state = SessionState(session_id="s1", plan_name="p", workflow_type="dual")
        state.start()
        time.sleep(0.05)
        state.end()
        assert state.duration_seconds >= 0.04

    def test_to_dict_contains_all_fields(self) -> None:
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
# SessionPersistence — append, read, list, exists
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    def test_append_creates_session_file(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        assert (tmp_path / "s1.jsonl").exists()

    def test_append_writes_valid_jsonl(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        lines = (tmp_path / "s1.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "session.started"

    def test_append_creates_directory_if_missing(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        nested = tmp_path / "deep" / "sessions"
        p = SessionPersistence(session_dir=nested)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        assert (nested / "s1.jsonl").exists()

    def test_read_returns_list_of_dicts(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = SessionStarted(session_id="s1", sequence=0, task="build", workflow="dual")
        p.append_event("s1", event)
        events = p.read_events("s1")
        assert isinstance(events, list)
        assert len(events) == 1
        assert isinstance(events[0], dict)

    def test_read_raises_for_missing_session(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            p.read_events("nonexistent")

    def test_read_preserves_multiple_events(self, tmp_path: Path) -> None:
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

    def test_list_returns_session_ids_sorted(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        for sid in ("beta", "alpha", "gamma"):
            event = SessionStarted(session_id=sid, sequence=0, task="t", workflow="w")
            p.append_event(sid, event)
        sessions = p.list_sessions()
        assert sessions == ["alpha", "beta", "gamma"]

    def test_list_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        assert p.list_sessions() == []

    def test_exists_true_after_append_false_before(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        assert p.session_exists("s1") is False
        event = SessionStarted(session_id="s1", sequence=0, task="t", workflow="w")
        p.append_event("s1", event)
        assert p.session_exists("s1") is True

    def test_roundtrip_preserves_all_fields(self, tmp_path: Path) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = PipelineStarted(session_id="s1", sequence=0, plan_name="my-plan", budget_usd=10.0)
        p.append_event("s1", event)
        events = p.read_events("s1")
        assert events[0]["plan_name"] == "my-plan"
        assert events[0]["budget_usd"] == 10.0
        assert events[0]["event_id"] == event.event_id

    def test_roundtrip_multiple_event_types(self, tmp_path: Path) -> None:
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


# ---------------------------------------------------------------------------
# Innovative lens — adversarial state transitions and persistence edges.
#
# Lens rationale: SessionState is mutable and will be called from multiple
# layers of the pipeline. Any hidden ordering assumption (end before start,
# record_stage after end, duration without start) is a latent crash. For
# persistence: the session file is the ONLY record of what happened in a
# run. Round-trip fidelity must survive arbitrary event payloads and the
# directory must be re-creatable if something deletes it between writes.
# ---------------------------------------------------------------------------


class TestInnovativeSessionEdge:
    def test_duration_is_none_before_start(self) -> None:
        """Asking ``duration_seconds`` before the session starts MUST return
        None — not 0.0, not raise. This is the invariant the CLI's status
        command depends on when printing 'pending' sessions.
        """
        from bonfire.session import SessionState

        state = SessionState(session_id="s", plan_name="p", workflow_type="dual")
        assert state.duration_seconds is None

    def test_duration_grows_monotonically_during_run(self) -> None:
        """While the session is active, ``duration_seconds`` must read the
        current elapsed time — increasing on every call, never negative.
        """
        from bonfire.session import SessionState

        state = SessionState(session_id="s", plan_name="p", workflow_type="dual")
        state.start()
        d1 = state.duration_seconds
        time.sleep(0.02)
        d2 = state.duration_seconds
        assert d1 is not None and d2 is not None
        assert d2 >= d1 >= 0.0

    def test_status_is_pending_before_end(self) -> None:
        """A session that has started but not ended has a defined status —
        'pending' per private v1. Matters for ``bonfire status`` display.
        """
        from bonfire.session import SessionState

        state = SessionState(session_id="s", plan_name="p", workflow_type="dual")
        state.start()
        assert state.status == "pending"

    def test_end_sets_custom_status(self) -> None:
        """end() accepts a status string ('failed', 'aborted', 'completed').
        Status MUST reflect what was passed.
        """
        from bonfire.session import SessionState

        state = SessionState(session_id="s", plan_name="p", workflow_type="dual")
        state.start()
        state.end(status="failed")
        assert state.status == "failed"
        assert state.is_active is False

    def test_record_stage_accumulates_floating_point_cost(self) -> None:
        """Ten stages at $0.1 must round to $1.00 within pytest.approx —
        catches naive sum bugs that drift under FP accumulation.
        """
        from bonfire.session import SessionState

        state = SessionState(session_id="s", plan_name="p", workflow_type="dual")
        state.start()
        for i in range(10):
            state.record_stage(f"stage_{i}", 0.1)
        assert state.total_cost_usd == pytest.approx(1.0)
        assert state.stages_completed == 10

    def test_to_dict_includes_completed_stages_list(self) -> None:
        """CLI 'resume' reads the completed stages list to know where to
        pick up. Must be present AND a list AND ordered by record_stage.
        """
        from bonfire.session import SessionState

        state = SessionState(session_id="s", plan_name="p", workflow_type="dual")
        state.start()
        state.record_stage("scout", 0.1)
        state.record_stage("knight", 0.2)
        d = state.to_dict()
        assert d["completed_stages"] == ["scout", "knight"]

    def test_persistence_append_after_dir_deleted_recreates(self, tmp_path: Path) -> None:
        """If the session directory is removed between two appends (disk
        cleanup, test sandbox, or a stray rm), the next append MUST
        recreate it — never crash with FileNotFoundError.
        """
        from bonfire.session import SessionPersistence

        session_dir = tmp_path / "sessions"
        p = SessionPersistence(session_dir=session_dir)
        p.append_event("s", SessionStarted(session_id="s", sequence=0, task="t", workflow="w"))
        # Nuke the whole directory — simulate external cleanup.
        import shutil

        shutil.rmtree(session_dir)
        # Next append must recreate.
        p.append_event(
            "s",
            StageCompleted(
                session_id="s",
                sequence=1,
                stage_name="scout",
                agent_name="a",
                duration_seconds=1.0,
                cost_usd=0.1,
            ),
        )
        events = p.read_events("s")
        # Only the second event survives — but no crash.
        assert len(events) == 1
        assert events[0]["event_type"] == "stage.completed"

    def test_persistence_isolates_sessions_by_id(self, tmp_path: Path) -> None:
        """Two sessions writing to the same directory MUST NOT bleed into
        each other's files.
        """
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        p.append_event("s_a", SessionStarted(session_id="s_a", sequence=0, task="t", workflow="w"))
        p.append_event("s_b", SessionStarted(session_id="s_b", sequence=0, task="t", workflow="w"))
        events_a = p.read_events("s_a")
        events_b = p.read_events("s_b")
        assert len(events_a) == 1
        assert len(events_b) == 1
        assert events_a[0]["session_id"] == "s_a"
        assert events_b[0]["session_id"] == "s_b"

    def test_persistence_list_ignores_non_jsonl_files(self, tmp_path: Path) -> None:
        """Foreign files in the session dir (notes.md, .DS_Store, a user's
        editor swap file) MUST NOT leak into ``list_sessions``.
        """
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        p.append_event(
            "real", SessionStarted(session_id="real", sequence=0, task="t", workflow="w")
        )
        # Sprinkle non-jsonl detritus.
        (tmp_path / "notes.md").write_text("not a session")
        (tmp_path / ".DS_Store").write_text("mac junk")
        (tmp_path / "README.txt").write_text("junk")
        assert p.list_sessions() == ["real"]

    def test_persistence_roundtrip_with_rich_dispatch_payload(self, tmp_path: Path) -> None:
        """DispatchCompleted carries cost + duration + agent_name. Every
        field MUST round-trip through JSON intact.
        """
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        event = DispatchCompleted(
            session_id="s",
            sequence=0,
            agent_name="scout_innovative_v2",
            cost_usd=0.123456,
            duration_seconds=42.42,
        )
        p.append_event("s", event)
        restored = p.read_events("s")[0]
        assert restored["agent_name"] == "scout_innovative_v2"
        assert restored["cost_usd"] == pytest.approx(0.123456)
        assert restored["duration_seconds"] == pytest.approx(42.42)
        assert restored["event_id"] == event.event_id

    def test_persistence_session_id_with_dashes_and_unicode(self, tmp_path: Path) -> None:
        """Session ids with dashes, underscores, and non-ASCII chars must
        survive as filenames on every major filesystem.
        """
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        sid = "ses-2026-04-19_alpha"
        p.append_event(sid, SessionStarted(session_id=sid, sequence=0, task="t", workflow="w"))
        assert p.session_exists(sid)
        assert sid in p.list_sessions()

    def test_appending_preserves_sequence_on_disk(self, tmp_path: Path) -> None:
        """Events carry a ``sequence`` field. After persistence round-trip,
        the original sequence number MUST be present — the CLI uses it for
        replay order.
        """
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=tmp_path)
        for i in range(5):
            p.append_event(
                "s",
                StageCompleted(
                    session_id="s",
                    sequence=i,
                    stage_name=f"st_{i}",
                    agent_name="a",
                    duration_seconds=1.0,
                    cost_usd=0.1,
                ),
            )
        events = p.read_events("s")
        assert [e["sequence"] for e in events] == [0, 1, 2, 3, 4]
