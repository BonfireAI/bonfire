# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire._safe_write.safe_append_text`` refuses to follow symlinks.

Append-mode companion to :mod:`bonfire._safe_write.safe_write_text`.
The W7.M ``safe_write_text`` rollout closed truncate-mode write sites
(``write_text`` / ``open("w")``) but missed append-mode sites
(``open("a")``) at:

* ``src/bonfire/session/persistence.py`` — JSONL event append
* ``src/bonfire/xp/tracker.py`` — JSONL XP-event append

Both targets sit at operator-controlled paths (``{session_id}.jsonl``
under ``session_dir``; ``xp_events.jsonl`` under ``xp_dir``). A planted
symlink at either path would redirect every appended line to an
attacker-controlled file — the same arbitrary-write primitive W7.M
closed for truncate writes, just in append form.

Semantics pinned by the RED tests below:

1. **Always refuse symlinks** at *path* (dangling, live, or loop).
   ``Path.is_symlink()`` pre-check + ``O_NOFOLLOW`` defense-in-depth.
2. **Append-mode semantics preserved** — first call creates the file,
   subsequent calls append at end-of-file.
3. **Symlink-refusal error** contains the literal substring
   ``"symlink"`` — log-grep contract carried forward from W7.M.
4. **Pre-existing regular file is NOT refused** — append mode legitimately
   re-opens existing files (no ``O_EXCL``).

POSIX-only: skipped on platforms without ``os.symlink``.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from bonfire._safe_write import safe_append_text


def _platform_supports_symlinks() -> bool:
    return hasattr(os, "symlink")


pytestmark = pytest.mark.skipif(
    not _platform_supports_symlinks(),
    reason="platform lacks os.symlink — symlink-reject tests are POSIX-only",
)


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    """Yield a tmp dir whose absolute path does NOT contain 'symlink'."""
    with tempfile.TemporaryDirectory(prefix="safe_append_workdir_") as td:
        yield Path(td)


def _snapshot(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_ino


# ---------------------------------------------------------------------------
# Direct contract — symlinks always refused
# ---------------------------------------------------------------------------


class TestSafeAppendTextSymlinkRefusal:
    """``safe_append_text`` refuses any symlink at the target path."""

    def test_dangling_symlink_refused(self, safe_tmp: Path) -> None:
        """Dangling symlink → FileExistsError, attack target untouched."""
        attack_target = safe_tmp / "attack_target.jsonl"
        assert not attack_target.exists()

        link = safe_tmp / "session_x.jsonl"
        link.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_append_text(link, "{}\n")

        # Arbitrary-append primitive must NOT have fired.
        assert not attack_target.exists(), (
            f"attack target {attack_target} was created through the dangling symlink"
        )

    def test_live_symlink_refused_target_preserved(self, safe_tmp: Path) -> None:
        """Live symlink → refused, symlink target byte-for-byte preserved."""
        attack_target = safe_tmp / "sensitive.log"
        sensitive = b"do-not-touch\n"
        attack_target.write_bytes(sensitive)
        snapshot = _snapshot(attack_target)

        link = safe_tmp / "session_x.jsonl"
        link.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_append_text(link, "appended-line\n")

        assert attack_target.read_bytes() == snapshot[0]
        assert attack_target.stat().st_ino == snapshot[1]

    def test_symlink_loop_refused_cleanly(self, safe_tmp: Path) -> None:
        """Symlink cycle → FileExistsError mentioning symlink (no raw OSError leak)."""
        link_a = safe_tmp / "link_a.jsonl"
        link_b = safe_tmp / "link_b.jsonl"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_append_text(link_a, "x\n")


# ---------------------------------------------------------------------------
# Append-mode semantics — first-write + subsequent-append
# ---------------------------------------------------------------------------


class TestSafeAppendTextAppendSemantics:
    """``safe_append_text`` creates on first call, appends on subsequent calls."""

    def test_first_call_creates_file(self, safe_tmp: Path) -> None:
        """First call against non-existent path creates the file."""
        target = safe_tmp / "events.jsonl"
        assert not target.exists()

        safe_append_text(target, "line-1\n")

        assert target.exists()
        assert not target.is_symlink()
        assert target.read_text() == "line-1\n"

    def test_subsequent_calls_append(self, safe_tmp: Path) -> None:
        """Subsequent calls append at EOF — prior content preserved."""
        target = safe_tmp / "events.jsonl"
        safe_append_text(target, "line-1\n")
        safe_append_text(target, "line-2\n")
        safe_append_text(target, "line-3\n")

        assert target.read_text() == "line-1\nline-2\nline-3\n"

    def test_existing_regular_file_not_refused(self, safe_tmp: Path) -> None:
        """Pre-existing regular file is opened in append mode (no O_EXCL)."""
        target = safe_tmp / "events.jsonl"
        target.write_text("prior-line\n")

        safe_append_text(target, "appended\n")

        assert target.read_text() == "prior-line\nappended\n"

    def test_mode_applied_on_create(self, safe_tmp: Path) -> None:
        """``mode`` parameter applied when file is newly created."""
        target = safe_tmp / "events.jsonl"
        old_umask = os.umask(0)
        try:
            safe_append_text(target, "x\n", mode=0o600)
        finally:
            os.umask(old_umask)

        actual_mode = target.stat().st_mode & 0o777
        assert actual_mode == 0o600


# ---------------------------------------------------------------------------
# Per-site integration: SessionPersistence.append_event
# ---------------------------------------------------------------------------


class TestSessionPersistenceSymlinkReject:
    """``SessionPersistence.append_event`` must not append through a symlink."""

    def test_append_event_refuses_dangling_symlink(self, safe_tmp: Path) -> None:
        """Dangling symlink at ``{session_id}.jsonl`` → append refused."""
        from bonfire.models.events import PipelineStarted
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        session_id = "sess_under_attack"
        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        # Plant the dangling symlink at the JSONL target path.
        jsonl = session_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(attack_target)

        persistence = SessionPersistence(session_dir)
        event = PipelineStarted(
            session_id=session_id,
            sequence=0,
            plan_name="test-plan",
            budget_usd=1.0,
        )

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.append_event(session_id, event)

        # The arbitrary-append primitive must NOT have fired.
        assert not attack_target.exists(), (
            f"append_event followed the symlink and created {attack_target}"
        )

    def test_append_event_refuses_live_symlink_target_preserved(self, safe_tmp: Path) -> None:
        """Live symlink to a sensitive file → refused, target preserved."""
        from bonfire.models.events import PipelineStarted
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        session_id = "sess_live_attack"
        attack_target = safe_tmp / "sensitive.log"
        sensitive = b"audit-log-must-survive\n"
        attack_target.write_bytes(sensitive)

        jsonl = session_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(attack_target)

        persistence = SessionPersistence(session_dir)
        event = PipelineStarted(
            session_id=session_id,
            sequence=0,
            plan_name="test-plan",
            budget_usd=1.0,
        )

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.append_event(session_id, event)

        # The sensitive file must still hold its original bytes — the
        # append primitive must not have leaked through the symlink.
        assert attack_target.read_bytes() == sensitive

    def test_append_event_happy_path_still_works(self, safe_tmp: Path) -> None:
        """No symlink planted → append still produces a regular JSONL line."""
        from bonfire.models.events import PipelineStarted
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        persistence = SessionPersistence(session_dir)
        event = PipelineStarted(
            session_id="happy_session",
            sequence=0,
            plan_name="happy-plan",
            budget_usd=1.0,
        )

        persistence.append_event("happy_session", event)

        jsonl = session_dir / "happy_session.jsonl"
        assert jsonl.exists()
        line = jsonl.read_text().strip()
        parsed = json.loads(line)
        assert parsed["plan_name"] == "happy-plan"


# ---------------------------------------------------------------------------
# Per-site integration: XPTracker.record
# ---------------------------------------------------------------------------


class TestXPTrackerSymlinkReject:
    """``XPTracker.record`` must not append through a symlink."""

    def test_record_refuses_dangling_symlink(self, safe_tmp: Path) -> None:
        """Dangling symlink at ``xp_events.jsonl`` → record refused.

        ``XPTracker.__init__`` mkdir-only creates the directory; the
        attack vector is the JSONL file itself. We pre-plant the symlink
        at ``xp_dir/xp_events.jsonl`` BEFORE constructing the tracker so
        ``record()`` hits the symlink on first append.
        """
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        # Plant the dangling symlink at the xp_events.jsonl target.
        jsonl = xp_dir / "xp_events.jsonl"
        jsonl.symlink_to(attack_target)

        tracker = XPTracker(xp_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.record(xp_total=100, success=True)

        assert not attack_target.exists(), (
            f"XPTracker.record followed the symlink and created {attack_target}"
        )

    def test_record_refuses_live_symlink_target_preserved(self, safe_tmp: Path) -> None:
        """Live symlink → refused, sensitive target preserved."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        attack_target = safe_tmp / "sensitive.log"
        sensitive = b"audit-log-must-survive\n"
        attack_target.write_bytes(sensitive)

        jsonl = xp_dir / "xp_events.jsonl"
        jsonl.symlink_to(attack_target)

        tracker = XPTracker(xp_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.record(xp_total=50, success=False)

        assert attack_target.read_bytes() == sensitive

    def test_record_happy_path_still_works(self, safe_tmp: Path) -> None:
        """No symlink planted → record produces a JSONL line."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        tracker = XPTracker(xp_dir)
        tracker.record(xp_total=10, success=True)
        tracker.record(xp_total=20, success=True)

        events = tracker.events()
        assert len(events) == 2
        assert events[0]["xp_total"] == 10
        assert events[1]["xp_total"] == 20
