"""RED tests — BON-344 W5.5 — `bonfire.xp.tracker` (conservative lens).

Sage D6 Row 2 locks: 21 tests across six TestXPTracker* / TestEmptyTracker /
TestPersistence classes pinning empty defaults, JSONL persistence, the
six-tier level ladder (Spark/Ember/Flame/Blaze/Inferno/WhiteHeat), level
transitions, and linear temperature decay (100 → 10 over 7 days with floor 10).
Sage D4 locks `_LEVELS`, `_DECAY_DAYS=7`, `_TEMP_MAX=100`, `_TEMP_FLOOR=10`;
Sage D8 locks `XPTracker.__init__(xp_dir: Path)` and `record(xp_total, success,
respawn=False)` signatures.

Adjudication: ``docs/audit/sage-decisions/bon-344-sage-20260424T022424Z.md``.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

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
