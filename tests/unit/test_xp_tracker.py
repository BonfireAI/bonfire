"""RED tests for bonfire.xp.tracker — BON-344 W5.5 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md

Floor (21 tests, per Sage §D6 Row 2): port v1 `test_xp_tracker.py` verbatim.
Innovations (2 tests, INNOVATIVE lens additions over Sage floor):

  * `test_level_ladder_matrix` — parametrize-matrix drift-guard on the _LEVELS
    ladder. Sage §D4 locks the six-tier ladder exactly at thresholds
    0/300/1000/3000/8000/20000 with names Spark/Ember/Flame/Blaze/Inferno/WhiteHeat.
    Cites Sage §D4 tracker.py:12-19.

  * `test_jsonl_record_roundtrip_byte_stable` — byte-stability drift-guard on
    JSONL persistence. Sage Appendix note 3 flags `respawn` as a field that v1
    writes to JSONL verbatim. This test locks the write→read contract so future
    refactors (e.g. adding a field) can't silently drift the on-disk format.
    Cites Sage §D4 + Appendix note 3 + tracker.py:56-63.

Imports are RED — `bonfire.xp.tracker` does not exist until Warriors port v1
source per Sage §D9.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from bonfire.xp.tracker import XPTracker

# ---------------------------------------------------------------------------
# Empty tracker defaults
# ---------------------------------------------------------------------------


class TestEmptyTracker:
    def test_empty_tracker_total_xp(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.total_xp() == 0

    def test_empty_tracker_level(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.level() == (0, "Spark")

    def test_empty_tracker_temperature(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.temperature() == 0

    def test_empty_tracker_session_count(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.session_count() == 0


# ---------------------------------------------------------------------------
# Recording and reading events
# ---------------------------------------------------------------------------


class TestRecordAndRead:
    def test_record_and_read(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=100, success=True)
        events = tracker.events()
        assert len(events) == 1

    def test_total_xp_accumulates(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=100, success=True)
        tracker.record(xp_total=150, success=True)
        assert tracker.total_xp() == 250

    def test_session_count_increments(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=50, success=True)
        tracker.record(xp_total=75, success=True)
        tracker.record(xp_total=100, success=False)
        assert tracker.session_count() == 3


# ---------------------------------------------------------------------------
# Level ladder
# ---------------------------------------------------------------------------


class TestLevelLadder:
    def test_level_spark(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.level() == (0, "Spark")

    def test_level_ember(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=300, success=True)
        assert tracker.level() == (1, "Ember")

    def test_level_flame(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=1000, success=True)
        assert tracker.level() == (2, "Flame")

    def test_level_blaze(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=3000, success=True)
        assert tracker.level() == (3, "Blaze")

    def test_level_inferno(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=8000, success=True)
        assert tracker.level() == (4, "Inferno")

    def test_level_whiteheat(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=20000, success=True)
        assert tracker.level() == (5, "WhiteHeat")

    def test_level_between_thresholds(self, tmp_path: Path) -> None:
        """500 XP is above Ember (300) but below Flame (1000) — should be Ember."""
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=500, success=True)
        assert tracker.level() == (1, "Ember")


# ---------------------------------------------------------------------------
# Level transitions
# ---------------------------------------------------------------------------


class TestLevelChanged:
    def test_level_changed_crosses_threshold(self, tmp_path: Path) -> None:
        """old_xp=290 (Spark), record 20 → total 310 (Ember). Crossed threshold."""
        tracker = XPTracker(xp_dir=tmp_path)
        # Seed with 290 first
        tracker.record(xp_total=290, success=True)
        # Record 20 more to cross into Ember
        tracker.record(xp_total=20, success=True)
        assert tracker.level_changed(old_xp=290) is True

    def test_level_changed_same_level(self, tmp_path: Path) -> None:
        """old_xp=100 (Spark), record 50 → total 150 (still Spark). No change."""
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=100, success=True)
        tracker.record(xp_total=50, success=True)
        assert tracker.level_changed(old_xp=100) is False


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------


class TestTemperature:
    def test_temperature_active_today(self, tmp_path: Path) -> None:
        """An event recorded today should give temperature > 0."""
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=100, success=True)
        assert tracker.temperature() > 0

    def test_temperature_cold_after_week(self, tmp_path: Path) -> None:
        """Event 8 days ago → 7+ days idle → floor at 10."""
        tracker = XPTracker(xp_dir=tmp_path)
        # Write a JSONL event with timestamp 8 days ago
        eight_days_ago = time.time() - (8 * 86400)
        event = {
            "xp_total": 100,
            "success": True,
            "respawn": False,
            "timestamp": eight_days_ago,
        }
        xp_file = tmp_path / "xp_events.jsonl"
        xp_file.write_text(json.dumps(event) + "\n")
        # Re-load tracker to pick up the file
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.temperature() == 10

    def test_temperature_never_zero_with_history(self, tmp_path: Path) -> None:
        """Any past events → temperature >= 10, never zero."""
        tracker = XPTracker(xp_dir=tmp_path)
        # Write an event from 30 days ago — well beyond any decay window
        thirty_days_ago = time.time() - (30 * 86400)
        event = {
            "xp_total": 50,
            "success": True,
            "respawn": False,
            "timestamp": thirty_days_ago,
        }
        xp_file = tmp_path / "xp_events.jsonl"
        xp_file.write_text(json.dumps(event) + "\n")
        tracker = XPTracker(xp_dir=tmp_path)
        assert tracker.temperature() >= 10


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_persistence_survives_reload(self, tmp_path: Path) -> None:
        """Record events, create new XPTracker with same dir → data intact."""
        tracker1 = XPTracker(xp_dir=tmp_path)
        tracker1.record(xp_total=100, success=True)
        tracker1.record(xp_total=200, success=True)

        # Create a completely new tracker instance pointing at same directory
        tracker2 = XPTracker(xp_dir=tmp_path)
        assert tracker2.total_xp() == 300
        assert tracker2.session_count() == 2
        assert len(tracker2.events()) == 2

    def test_jsonl_format(self, tmp_path: Path) -> None:
        """Record event, read raw file → valid JSON per line."""
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=42, success=True, respawn=False)

        xp_file = tmp_path / "xp_events.jsonl"
        assert xp_file.exists(), "JSONL file must be created"

        lines = xp_file.read_text().strip().splitlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["xp_total"] == 42
        assert data["success"] is True
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# INNOVATIVE-lens additions (Knight B, Sage-cited)
# ---------------------------------------------------------------------------


class TestLevelLadderMatrix:
    """Drift-guard: parametrize-matrix pins the six-tier _LEVELS ladder.

    Sage §D4 locks the ladder at tracker.py:12-19:
        _LEVELS = [
            (20000, 5, "WhiteHeat"),
            (8000,  4, "Inferno"),
            (3000,  3, "Blaze"),
            (1000,  2, "Flame"),
            (300,   1, "Ember"),
            (0,     0, "Spark"),
        ]

    A single parametrize case per tier — if any threshold or name drifts,
    exactly the affected row fails. Compared to six separate "test_level_X"
    floor tests, this one matrix is the single place to grep for "what is
    the ladder" — cleaner than six scattered recorder tests. It is additive
    to the floor tests, which cover boundary-AT-threshold; this matrix
    covers the identity-on-the-shelf each tier sits on.
    """

    @pytest.mark.parametrize(
        ("xp", "expected_level"),
        [
            (0, (0, "Spark")),
            (300, (1, "Ember")),
            (1000, (2, "Flame")),
            (3000, (3, "Blaze")),
            (8000, (4, "Inferno")),
            (20000, (5, "WhiteHeat")),
        ],
    )
    def test_level_ladder_matrix(
        self, tmp_path: Path, xp: int, expected_level: tuple[int, str]
    ) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        if xp > 0:
            tracker.record(xp_total=xp, success=True)
        assert tracker.level() == expected_level, (
            f"Level ladder drift at xp={xp}: expected {expected_level}, "
            f"got {tracker.level()}. Sage §D4 locks the _LEVELS constant."
        )


class TestJsonlByteStability:
    """Drift-guard: JSONL record→read round-trip is byte-stable.

    Sage §D4 + Appendix note 3 flag that `XPTracker.record(xp_total, success,
    respawn=False)` writes a four-key event shape to JSONL:
        {"xp_total": ..., "success": ..., "respawn": ..., "timestamp": ...}

    Appendix note 3 specifically flags that `respawn` is written verbatim even
    when redundant. This test locks the write→read contract: what `record`
    appends must parse back to a dict with exactly the four Sage-specified keys,
    with values byte-stable for xp_total/success/respawn. timestamp is checked
    only for presence (it's a monotonic float, not byte-stable by nature).

    Future refactor guard: if a Warrior "cleans up" by dropping the `respawn`
    field on write, this test fires.
    """

    def test_jsonl_record_roundtrip_byte_stable(self, tmp_path: Path) -> None:
        tracker = XPTracker(xp_dir=tmp_path)
        tracker.record(xp_total=250, success=False, respawn=True)

        xp_file = tmp_path / "xp_events.jsonl"
        lines = xp_file.read_text().strip().splitlines()
        assert len(lines) == 1

        parsed = json.loads(lines[0])
        # Exact key-set lock per Sage §D4 + tracker.py:56-63.
        assert set(parsed.keys()) == {"xp_total", "success", "respawn", "timestamp"}, (
            f"JSONL schema drift from Sage-locked shape; got keys={sorted(parsed.keys())}"
        )
        # Byte-stable values for the three deterministic fields.
        assert parsed["xp_total"] == 250
        assert parsed["success"] is False
        assert parsed["respawn"] is True
        # timestamp is a non-deterministic float; only check presence + type.
        assert isinstance(parsed["timestamp"], (int, float))
