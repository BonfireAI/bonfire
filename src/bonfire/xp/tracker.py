"""XP tracker with JSONL persistence, level ladder, and temperature."""

from __future__ import annotations

import json
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Level ladder: (threshold, level_number, tier_name) — descending order
# ---------------------------------------------------------------------------
_LEVELS = [
    (20000, 5, "WhiteHeat"),
    (8000, 4, "Inferno"),
    (3000, 3, "Blaze"),
    (1000, 2, "Flame"),
    (300, 1, "Ember"),
    (0, 0, "Spark"),
]

# Temperature decay: 100 → 10 over 7 days, floor at 10
_DECAY_DAYS = 7
_TEMP_MAX = 100
_TEMP_FLOOR = 10


def _level_for_xp(xp: int) -> tuple[int, str]:
    """Return (level_number, tier_name) for a given XP total."""
    for threshold, level_num, tier_name in _LEVELS:
        if xp >= threshold:
            return level_num, tier_name
    return 0, "Spark"


class XPTracker:
    """Persists XP events as JSONL and computes aggregates."""

    def __init__(self, xp_dir: Path) -> None:
        self._xp_dir = Path(xp_dir)
        self._xp_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self._xp_dir / "xp_events.jsonl"

    def record(
        self,
        xp_total: int,
        success: bool,
        respawn: bool = False,
    ) -> None:
        """Append an XP event to the JSONL file.

        Note: No file-level locking is used. Bonfire runs one pipeline
        at a time, so concurrent writes are not expected. If concurrent
        pipelines are introduced, this method must be wrapped in a
        file lock (e.g., ``fcntl.flock``) to prevent JSONL corruption.
        """
        event = {
            "xp_total": xp_total,
            "success": success,
            "respawn": respawn,
            "timestamp": time.time(),
        }
        with self._jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def events(self) -> list[dict]:
        """Read all events from the JSONL file."""
        if not self._jsonl_path.exists():
            return []
        results: list[dict] = []
        with self._jsonl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
        return results

    def total_xp(self) -> int:
        """Sum of xp_total across all events."""
        return sum(e["xp_total"] for e in self.events())

    def session_count(self) -> int:
        """Count of recorded events."""
        return len(self.events())

    def level(self) -> tuple[int, str]:
        """Return (level_number, tier_name) based on total XP."""
        return _level_for_xp(self.total_xp())

    def level_changed(self, old_xp: int) -> bool:
        """True if the level for old_xp differs from the current level."""
        old_level = _level_for_xp(old_xp)
        current_level = self.level()
        return old_level != current_level

    def temperature(self) -> int:
        """Activity temperature based on recency of last event.

        - No events: 0
        - Events exist: linear decay from 100 to floor of 10
          over _DECAY_DAYS (7 days). Floor is 10.
        """
        evts = self.events()
        if not evts:
            return 0

        latest_ts = max(e["timestamp"] for e in evts)
        days_idle = (time.time() - latest_ts) / 86400

        if days_idle >= _DECAY_DAYS:
            return _TEMP_FLOOR

        # Linear decay: 100 at 0 days, 10 at 7 days
        temp = _TEMP_MAX - ((_TEMP_MAX - _TEMP_FLOOR) * days_idle / _DECAY_DAYS)
        return max(_TEMP_FLOOR, int(temp))
