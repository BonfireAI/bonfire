"""Canonical RED — ``bonfire.engine.checkpoint`` (BON-334).

Synthesized from Knight-A orchestration + Knight-B contract fidelity.

A sloppy orchestrator fumbles crash recovery: half-written files, lost session
IDs, failures to mkdir. This suite pins the atomic-write contract and the
resume-after-crash contract.

Contract locked:
    1. CheckpointData is a frozen Pydantic model with exact V1 field list.
    2. CheckpointSummary is a frozen Pydantic model with exact V1 field list.
    3. save() uses atomic tmp+os.replace; no lingering .tmp; no corrupt files.
    4. save() auto-creates missing parent directories.
    5. save() writes to {session_id}.json and returns Path.
    6. save() persists session_id, plan_name, cost, timestamp, version.
    7. load() returns CheckpointData; raises FileNotFoundError for missing.
    8. latest() returns newest by timestamp; None on empty/missing dir.
    9. list_checkpoints() returns summaries sorted desc by timestamp.
   10. Round-trip preserves envelopes byte-perfect (status + cost_usd + result).
   11. Corrupt JSON raises on explicit load (does not crash manager).
"""

from __future__ import annotations

import inspect
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType

# ---------------------------------------------------------------------------
# Helpers — mirror V1 test_checkpoint.py style
# ---------------------------------------------------------------------------


def _make_plan(name: str = "ck-plan") -> WorkflowPlan:
    return WorkflowPlan(
        name=name,
        workflow_type=WorkflowType.STANDARD,
        stages=[
            StageSpec(name="scout", agent_name="scout-agent"),
            StageSpec(name="knight", agent_name="knight-agent", depends_on=["scout"]),
        ],
        task_description="rebuild the engine",
        budget_usd=5.0,
    )


def _make_completed() -> dict[str, Envelope]:
    return {
        "scout": Envelope(
            task="research",
            agent_name="scout-agent",
            status=TaskStatus.COMPLETED,
            result="scout findings",
            cost_usd=0.25,
        ),
        "knight": Envelope(
            task="write tests",
            agent_name="knight-agent",
            status=TaskStatus.COMPLETED,
            result="RED suite",
            cost_usd=0.50,
        ),
    }


def _make_result(session_id: str = "sess-abc"):  # noqa: ANN202 — built lazily, depends on impl
    from bonfire.engine.pipeline import PipelineResult

    return PipelineResult(
        success=True,
        session_id=session_id,
        stages=_make_completed(),
        total_cost_usd=0.75,
        duration_seconds=3.14,
    )


# ===========================================================================
# 1. Imports
# ===========================================================================


class TestImports:
    """All three checkpoint types importable from both paths."""

    def test_import_from_module(self) -> None:
        from bonfire.engine.checkpoint import (
            CheckpointData,
            CheckpointManager,
            CheckpointSummary,
        )

        assert CheckpointData is not None
        assert CheckpointManager is not None
        assert CheckpointSummary is not None

    def test_import_from_engine_package(self) -> None:
        from bonfire.engine import CheckpointData, CheckpointManager, CheckpointSummary

        assert CheckpointData is not None
        assert CheckpointManager is not None
        assert CheckpointSummary is not None


# ===========================================================================
# 2. CheckpointData — frozen, versioned, serializable
# ===========================================================================


class TestCheckpointData:
    """CheckpointData is a frozen, versioned, serializable Pydantic model."""

    def test_field_list_matches_v1(self) -> None:
        """Locked field set (Sage D8 parallel lock for CheckpointData)."""
        from bonfire.engine.checkpoint import CheckpointData

        expected = {
            "session_id",
            "plan_name",
            "task_description",
            "completed",
            "total_cost_usd",
            "timestamp",
            "checkpoint_version",
        }
        assert set(CheckpointData.model_fields.keys()) == expected

    def test_fields_populated(self) -> None:
        from bonfire.engine.checkpoint import CheckpointData

        data = CheckpointData(
            session_id="s1",
            plan_name="p1",
            task_description="do thing",
            completed=_make_completed(),
            total_cost_usd=0.75,
            timestamp=time.time(),
        )
        assert data.session_id == "s1"
        assert data.plan_name == "p1"
        assert data.task_description == "do thing"
        assert data.total_cost_usd == 0.75
        assert len(data.completed) == 2

    def test_default_task_description_is_empty(self) -> None:
        from bonfire.engine.checkpoint import CheckpointData

        data = CheckpointData(
            session_id="s",
            plan_name="p",
            completed={},
            total_cost_usd=0.0,
            timestamp=1.0,
        )
        assert data.task_description == ""

    def test_default_checkpoint_version_is_1(self) -> None:
        from bonfire.engine.checkpoint import CheckpointData

        data = CheckpointData(
            session_id="s",
            plan_name="p",
            completed={},
            total_cost_usd=0.0,
            timestamp=1.0,
        )
        assert data.checkpoint_version == 1

    def test_is_frozen(self) -> None:
        """Attempting to mutate a CheckpointData raises ValidationError."""
        from bonfire.engine.checkpoint import CheckpointData

        data = CheckpointData(
            session_id="s",
            plan_name="p",
            completed={},
            total_cost_usd=0.0,
            timestamp=1.0,
        )
        with pytest.raises(ValidationError):
            data.session_id = "changed"  # type: ignore[misc]

    def test_round_trip_through_json(self) -> None:
        from bonfire.engine.checkpoint import CheckpointData

        data = CheckpointData(
            session_id="s",
            plan_name="p",
            completed=_make_completed(),
            total_cost_usd=0.75,
            timestamp=1000.0,
        )
        dumped = data.model_dump(mode="json")
        blob = json.dumps(dumped)
        restored = CheckpointData.model_validate(json.loads(blob))
        assert restored == data


# ===========================================================================
# 3. CheckpointSummary — frozen, compact
# ===========================================================================


class TestCheckpointSummary:
    """CheckpointSummary is frozen and holds lightweight metrics."""

    def test_field_list_matches_v1(self) -> None:
        from bonfire.engine.checkpoint import CheckpointSummary

        expected = {
            "session_id",
            "plan_name",
            "timestamp",
            "stages_completed",
            "total_cost_usd",
        }
        assert set(CheckpointSummary.model_fields.keys()) == expected

    def test_fields_populated(self) -> None:
        from bonfire.engine.checkpoint import CheckpointSummary

        summary = CheckpointSummary(
            session_id="s",
            plan_name="p",
            timestamp=1000.0,
            stages_completed=3,
            total_cost_usd=1.25,
        )
        assert summary.stages_completed == 3
        assert summary.total_cost_usd == 1.25

    def test_is_frozen(self) -> None:
        from bonfire.engine.checkpoint import CheckpointSummary

        summary = CheckpointSummary(
            session_id="s",
            plan_name="p",
            timestamp=1.0,
            stages_completed=1,
            total_cost_usd=0.0,
        )
        with pytest.raises(ValidationError):
            summary.session_id = "changed"  # type: ignore[misc]


# ===========================================================================
# 4. CheckpointManager constructor
# ===========================================================================


class TestCheckpointManagerConstructor:
    """CheckpointManager(checkpoint_dir: Path) (V1 line 76)."""

    def test_accepts_path_argument(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(tmp_path)
        assert mgr is not None

    def test_constructor_has_checkpoint_dir_param(self) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        sig = inspect.signature(CheckpointManager.__init__)
        assert "checkpoint_dir" in sig.parameters


# ===========================================================================
# 5. save() — atomic write, file placement, metadata persistence
# ===========================================================================


class TestSave:
    """save() persists a pipeline result to ``{session_id}.json`` atomically."""

    def test_save_creates_json_file(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        path = mgr.save("s1", _make_result("s1"), _make_plan())
        assert path.exists()
        assert path.suffix == ".json"
        assert "s1" in path.name

    def test_save_writes_session_id_json_file(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(tmp_path)
        out = mgr.save("abc123", _make_result("abc123"), _make_plan())
        assert out == tmp_path / "abc123.json"
        assert out.exists()

    def test_save_returns_path_instance(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        path = mgr.save("s2", _make_result("s2"), _make_plan())
        assert isinstance(path, Path)

    def test_save_persists_session_id_and_plan_name(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        path = mgr.save("s-meta", _make_result("s-meta"), _make_plan(name="my-plan"))
        raw = json.loads(path.read_text())
        assert raw["session_id"] == "s-meta"
        assert raw["plan_name"] == "my-plan"

    def test_save_persists_cost(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        path = mgr.save("s-cost", _make_result("s-cost"), _make_plan())
        raw = json.loads(path.read_text())
        assert raw["total_cost_usd"] == 0.75

    def test_save_persists_all_stage_envelopes(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        path = mgr.save("s-stages", _make_result("s-stages"), _make_plan())
        raw = json.loads(path.read_text())
        assert "scout" in raw["completed"]
        assert "knight" in raw["completed"]

    def test_save_is_atomic_via_tmp_and_replace(self, tmp_path: Path) -> None:
        """save() must use tmp+os.replace to guarantee atomicity on crash (V1 102-106)."""
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        import os as _os

        real_replace = _os.replace
        with patch(
            "bonfire.engine.checkpoint.os.replace",
            wraps=real_replace,
        ) as spy:
            mgr.save("s-atomic", _make_result("s-atomic"), _make_plan())
            spy.assert_called_once()
            call_args = spy.call_args.args
            tmp_file = str(call_args[0])
            assert "tmp" in tmp_file.lower()

    def test_save_leaves_no_tmp_file(self, tmp_path: Path) -> None:
        """Atomic write: tmp -> replace -> no lingering .tmp (V1 102-106)."""
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(tmp_path)
        mgr.save("x", _make_result("x"), _make_plan())
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_auto_creates_missing_directory(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        nested = tmp_path / "deep" / "path" / "ckpt"
        assert not nested.exists()
        mgr = CheckpointManager(checkpoint_dir=nested)
        mgr.save("s-mk", _make_result("s-mk"), _make_plan())
        assert nested.exists()

    def test_save_stores_checkpoint_version(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        path = mgr.save("s-ver", _make_result("s-ver"), _make_plan())
        raw = json.loads(path.read_text())
        assert raw["checkpoint_version"] == 1

    def test_save_stores_timestamp(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        before = time.time()
        path = mgr.save("s-ts", _make_result("s-ts"), _make_plan())
        after = time.time()
        raw = json.loads(path.read_text())
        assert isinstance(raw["timestamp"], (int, float))
        assert before - 1 <= raw["timestamp"] <= after + 1

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("dup", _make_result("dup"), _make_plan())
        path2 = mgr.save("dup", _make_result("dup"), _make_plan(name="altered"))
        raw = json.loads(path2.read_text())
        assert raw["plan_name"] == "altered"


# ===========================================================================
# 6. load() — round-trip + FileNotFoundError
# ===========================================================================


class TestLoad:
    """load() returns CheckpointData; FileNotFoundError on missing session."""

    def test_load_returns_checkpoint_data(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointData, CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("L1", _make_result("L1"), _make_plan())
        loaded = mgr.load("L1")
        assert isinstance(loaded, CheckpointData)
        assert loaded.session_id == "L1"

    def test_load_preserves_plan_name(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("L2", _make_result("L2"), _make_plan(name="special"))
        loaded = mgr.load("L2")
        assert loaded.plan_name == "special"

    def test_load_missing_session_raises_file_not_found(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.load("nope")

    def test_load_preserves_completed_envelopes(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(tmp_path)
        mgr.save("r2", _make_result("r2"), _make_plan())
        loaded = mgr.load("r2")
        assert "scout" in loaded.completed
        assert isinstance(loaded.completed["scout"], Envelope)


# ===========================================================================
# 7. latest()
# ===========================================================================


class TestLatest:
    """latest(): most recent by timestamp; None when empty/missing."""

    def test_empty_returns_none(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        assert mgr.latest() is None

    def test_missing_directory_returns_none(self, tmp_path: Path) -> None:
        """Non-existent checkpoint dir returns None, does not raise."""
        from bonfire.engine.checkpoint import CheckpointManager

        missing = tmp_path / "never-created"
        mgr = CheckpointManager(checkpoint_dir=missing)
        assert mgr.latest() is None

    def test_returns_newest(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("old", _make_result("old"), _make_plan())
        time.sleep(0.01)  # ensure distinct timestamps
        mgr.save("new", _make_result("new"), _make_plan())

        latest = mgr.latest()
        assert latest is not None
        assert latest.session_id == "new"

    def test_single_entry_returns_that_entry(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointData, CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("only", _make_result("only"), _make_plan())

        latest = mgr.latest()
        assert isinstance(latest, CheckpointData)
        assert latest.session_id == "only"


# ===========================================================================
# 8. list_checkpoints()
# ===========================================================================


class TestList:
    """list_checkpoints() returns summaries in descending timestamp order."""

    def test_empty_list(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        assert mgr.list_checkpoints() == []

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(tmp_path / "missing")
        assert mgr.list_checkpoints() == []

    def test_returns_summary_type(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager, CheckpointSummary

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("a", _make_result("a"), _make_plan())
        summaries = mgr.list_checkpoints()
        assert len(summaries) == 1
        assert isinstance(summaries[0], CheckpointSummary)

    def test_sorted_descending_by_timestamp(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        for sid in ("a", "b", "c"):
            mgr.save(sid, _make_result(sid), _make_plan())
            time.sleep(0.005)

        summaries = mgr.list_checkpoints()
        timestamps = [s.timestamp for s in summaries]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_summary_counts_stages(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("S", _make_result("S"), _make_plan())

        summaries = mgr.list_checkpoints()
        assert summaries[0].stages_completed == 2

    def test_summary_exposes_session_id_and_plan_name(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("s1", _make_result("s1"), _make_plan(name="ck-plan"))
        summary = mgr.list_checkpoints()[0]
        assert summary.session_id == "s1"
        assert summary.plan_name == "ck-plan"


# ===========================================================================
# 9. Round-trip — saved state is byte-perfect after load
# ===========================================================================


class TestRoundTrip:
    """Saved state is byte-perfect after load."""

    def test_round_trip_preserves_cost(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("r1", _make_result("r1"), _make_plan())
        loaded = mgr.load("r1")
        assert loaded.total_cost_usd == 0.75

    def test_round_trip_preserves_envelopes(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("r2", _make_result("r2"), _make_plan())
        loaded = mgr.load("r2")

        scout = loaded.completed["scout"]
        assert isinstance(scout, Envelope)
        assert scout.result == "scout findings"
        assert scout.status == TaskStatus.COMPLETED
        assert scout.cost_usd == 0.25

    def test_round_trip_preserves_task_description(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        mgr.save("r3", _make_result("r3"), _make_plan())
        loaded = mgr.load("r3")
        assert loaded.task_description == "rebuild the engine"


# ===========================================================================
# 10. Corrupt-file tolerance
# ===========================================================================


class TestCorruptFileHandling:
    """Corrupt files raise on the specific load, not on manager construction."""

    def test_corrupt_file_raises_on_direct_load(self, tmp_path: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        (tmp_path / "bad.json").write_text("{not json")

        mgr = CheckpointManager(checkpoint_dir=tmp_path)
        with pytest.raises(Exception):  # noqa: B017 — JSONDecodeError or ValidationError
            mgr.load("bad")
