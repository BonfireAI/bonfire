# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: read-symmetric defenses mirror Wave 9's safe-write hardening.

Probe N+6 surfaced that Wave 9 hardened the WRITE side of the JSONL
append paths (``SessionPersistence.append_event`` + ``XPTracker.record``)
via ``safe_append_text`` but left the SYMMETRIC READ side
(``SessionPersistence.read_events`` + ``XPTracker.events``) using raw
``path.read_text()`` / ``path.open("r")``. The same symlink-redirect
defense-family that protects the write path must protect the read path:

* A planted symlink at ``{session_id}.jsonl -> /etc/passwd`` lets a
  malicious operator leak sensitive bytes back into a Bonfire pipeline
  (``read_events`` would happily parse the symlink target).
* A planted 5 GiB file at ``xp_events.jsonl`` lets the same actor
  exhaust RAM when ``XPTracker.events`` slurps the file in.

This wave (BON-1075) routes both reads through
``safe_read_capped_text`` (W7.M's read-side helper) at
``MAX_CHECKPOINT_BYTES`` (10 MiB cap).

The third site closed by this wave is the ``.gitignore`` append in
``cli/commands/init.py:84``. The W9 init code uses
``path.is_symlink()`` + raw ``path.write_text(existing + ...)``; this
leaves a TOCTOU window between the symlink pre-check and the write
that a race-planted symlink can slip through. The fix routes the
append through ``safe_append_text`` (W7.M append helper with
``O_NOFOLLOW`` defense-in-depth), closing the race.

Adversarial coverage per the defense-in-depth-needs-adversarial-tests
discipline: ``..`` / ``//`` / case-fold / encoded path shapes are
exercised against each site so a future regression on input
canonicalization cannot bypass the symlink guard.

POSIX-only: symlink tests skip on platforms without ``os.symlink``.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from bonfire._safe_read import MAX_CHECKPOINT_BYTES


def _platform_supports_symlinks() -> bool:
    return hasattr(os, "symlink")


pytestmark = pytest.mark.skipif(
    not _platform_supports_symlinks(),
    reason="platform lacks os.symlink — read-symmetric tests are POSIX-only",
)


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    """Yield a tmp dir whose absolute path does NOT contain 'symlink'."""
    with tempfile.TemporaryDirectory(prefix="bon_1075_workdir_") as td:
        yield Path(td)


# ---------------------------------------------------------------------------
# Site 1 — SessionPersistence.read_events
# ---------------------------------------------------------------------------


class TestSessionPersistenceReadEventsSymlinkReject:
    """``SessionPersistence.read_events`` must not read through a symlink."""

    def test_read_events_refuses_live_symlink_to_sensitive_file(self, safe_tmp: Path) -> None:
        """Live symlink at ``{session_id}.jsonl`` → FileExistsError (symlink)."""
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        sensitive = safe_tmp / "fake_passwd"
        sensitive.write_text("root:x:0:0:root:/root:/bin/bash\n")

        session_id = "sess_under_attack"
        jsonl = session_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(sensitive)

        persistence = SessionPersistence(session_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events(session_id)

    def test_read_events_refuses_dangling_symlink(self, safe_tmp: Path) -> None:
        """Dangling symlink → FileExistsError, not FileNotFoundError.

        ``Path.exists()`` returns False for a dangling symlink, which
        previously let ``read_events`` raise the ambiguous
        ``FileNotFoundError("No session file")`` — masking the
        symlink-attack signal. The hardened path raises
        FileExistsError(symlink) so the operator sees the actual
        threat.
        """
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        session_id = "sess_dangling"
        jsonl = session_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(safe_tmp / "nonexistent_target")

        persistence = SessionPersistence(session_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events(session_id)

    def test_read_events_refuses_symlink_loop(self, safe_tmp: Path) -> None:
        """Symlink cycle → FileExistsError, no hang or raw ELOOP leak."""
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        link_a = session_dir / "loop_a.jsonl"
        link_b = session_dir / "loop_b.jsonl"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        persistence = SessionPersistence(session_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events("loop_a")

    def test_read_events_refuses_oversized_jsonl(self, safe_tmp: Path) -> None:
        """JSONL > MAX_CHECKPOINT_BYTES (10 MiB) → ValueError(exceeds cap).

        A planted oversized session file would otherwise let an attacker
        force unbounded memory allocation when an operator inspects
        session history.
        """
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        session_id = "sess_oversized"
        jsonl = session_dir / f"{session_id}.jsonl"
        jsonl.write_bytes(b"A" * (MAX_CHECKPOINT_BYTES + 1024))

        persistence = SessionPersistence(session_dir)

        with pytest.raises(ValueError, match="exceeds cap"):
            persistence.read_events(session_id)

    def test_read_events_happy_path_preserved(self, safe_tmp: Path) -> None:
        """No symlink, within cap → events parsed normally."""
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

        events = persistence.read_events("happy_session")
        assert len(events) == 1
        assert events[0]["plan_name"] == "happy-plan"

    def test_read_events_missing_file_still_raises_filenotfounderror(self, safe_tmp: Path) -> None:
        """Missing session file → FileNotFoundError preserved.

        Pin the existing public contract: ``read_events`` raises
        ``FileNotFoundError`` when the file is genuinely absent (not a
        dangling symlink). This separates "operator typoed the session
        id" from "attacker planted a symlink".
        """
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()
        persistence = SessionPersistence(session_dir)

        with pytest.raises(FileNotFoundError):
            persistence.read_events("never_existed")


class TestSessionPersistenceReadEventsAdversarialPaths:
    """Adversarial path shapes (``..``, ``//``, case-fold, encoded) refused.

    Per feedback_defense_in_depth_needs_adversarial_tests_2026_05_15 —
    write-floors/deny-lists MUST be exercised against canonicalization
    edge cases. The symlink guard sits at the resolved path, so each
    shape resolves to the same planted symlink and must still be refused.
    """

    def test_double_slash_in_session_dir_still_refused(self, safe_tmp: Path) -> None:
        """``session_dir`` with ``//`` segments — symlink still detected."""
        from bonfire.session.persistence import SessionPersistence

        real_dir = safe_tmp / "sessions"
        real_dir.mkdir()

        # Plant a symlink at the actual jsonl path.
        session_id = "sess_doubled"
        sensitive = safe_tmp / "fake_passwd"
        sensitive.write_text("root:x:0:0:root:/root:/bin/bash\n")
        jsonl = real_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(sensitive)

        # Construct a session_dir Path with a doubled separator. pathlib
        # collapses leading ``//`` but interior duplicates are preserved
        # textually; the resolved fd-open still hits the symlink.
        doubled = Path(str(safe_tmp) + "//sessions")
        persistence = SessionPersistence(doubled)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events(session_id)

    def test_dot_dot_in_session_dir_still_refused(self, safe_tmp: Path) -> None:
        """``session_dir`` containing ``..`` — symlink still refused."""
        from bonfire.session.persistence import SessionPersistence

        real_dir = safe_tmp / "sessions"
        real_dir.mkdir()

        session_id = "sess_dotdot"
        sensitive = safe_tmp / "fake_passwd"
        sensitive.write_text("data\n")
        jsonl = real_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(sensitive)

        # safe_tmp/sessions/../sessions resolves back to safe_tmp/sessions.
        traversed = safe_tmp / "sessions" / ".." / "sessions"
        persistence = SessionPersistence(traversed)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events(session_id)

    def test_case_fold_session_id_does_not_evade(self, safe_tmp: Path) -> None:
        """Case-folded session id — does not bypass symlink guard.

        On case-sensitive filesystems (Linux ext4/xfs/btrfs) the upper
        + lower variants are distinct files: the upper symlink stays
        refused; the lower variant is genuinely absent. The contract
        the test pins is that the upper-case symlink-refusal does NOT
        regress to a content-read just because a sibling name exists.
        """
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("payload\n")

        upper = session_dir / "SESS_CASE.jsonl"
        upper.symlink_to(sensitive)

        persistence = SessionPersistence(session_dir)

        # Upper-case id resolves to the symlinked path → refused.
        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events("SESS_CASE")

    def test_url_encoded_session_id_does_not_evade(self, safe_tmp: Path) -> None:
        """URL-encoded session id resolving to symlinked file refused.

        If a caller percent-encodes the session id and the resolved
        on-disk name still points at the planted symlink, the refusal
        must fire — the encoding shape is not a TOCTOU escape.
        """
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        # Plant a literal ``%20`` in the filename (no URL decoding).
        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("payload\n")
        jsonl = session_dir / "sess%20encoded.jsonl"
        jsonl.symlink_to(sensitive)

        persistence = SessionPersistence(session_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events("sess%20encoded")


# ---------------------------------------------------------------------------
# Site 2 — XPTracker.events
# ---------------------------------------------------------------------------


class TestXPTrackerEventsSymlinkReject:
    """``XPTracker.events`` must not read through a symlink."""

    def test_events_refuses_live_symlink_to_sensitive_file(self, safe_tmp: Path) -> None:
        """Live symlink at ``xp_events.jsonl`` → FileExistsError(symlink)."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        sensitive = safe_tmp / "sensitive.log"
        sensitive.write_text("audit-log\n")

        jsonl = xp_dir / "xp_events.jsonl"
        jsonl.symlink_to(sensitive)

        tracker = XPTracker(xp_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.events()

    def test_events_refuses_dangling_symlink(self, safe_tmp: Path) -> None:
        """Dangling symlink → FileExistsError (not the silent empty-list path).

        The current behavior gates on ``self._jsonl_path.exists()`` —
        which returns False for a dangling symlink, silently swallowing
        the attack signal as "no events yet". The hardened version
        detects the symlink before deciding empty-list-vs-read.
        """
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        jsonl = xp_dir / "xp_events.jsonl"
        jsonl.symlink_to(safe_tmp / "nonexistent_target")

        tracker = XPTracker(xp_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.events()

    def test_events_refuses_symlink_loop(self, safe_tmp: Path) -> None:
        """Symlink cycle at ``xp_events.jsonl`` → FileExistsError."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        decoy = xp_dir / "xp_events.jsonl"
        partner = xp_dir / "xp_events_loop_partner"
        decoy.symlink_to(partner)
        partner.symlink_to(decoy)

        tracker = XPTracker(xp_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.events()

    def test_events_refuses_oversized_jsonl(self, safe_tmp: Path) -> None:
        """XP ledger > MAX_CHECKPOINT_BYTES → ValueError(exceeds cap)."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        jsonl = xp_dir / "xp_events.jsonl"
        jsonl.write_bytes(b"A" * (MAX_CHECKPOINT_BYTES + 1024))

        tracker = XPTracker(xp_dir)

        with pytest.raises(ValueError, match="exceeds cap"):
            tracker.events()

    def test_events_happy_path_preserved(self, safe_tmp: Path) -> None:
        """No symlink → events parsed normally; empty-on-missing still works."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        tracker = XPTracker(xp_dir)

        # Missing file → empty list (preserved contract).
        assert tracker.events() == []

        tracker.record(xp_total=10, success=True)
        tracker.record(xp_total=20, success=True)

        events = tracker.events()
        assert len(events) == 2
        assert events[0]["xp_total"] == 10
        assert events[1]["xp_total"] == 20


class TestXPTrackerEventsAdversarialPaths:
    """Adversarial path shapes against the XP ledger read site."""

    def test_double_slash_in_xp_dir_still_refused(self, safe_tmp: Path) -> None:
        """``xp_dir`` with doubled separator — symlink still detected."""
        from bonfire.xp.tracker import XPTracker

        real_dir = safe_tmp / "xp"
        real_dir.mkdir()

        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("payload\n")
        jsonl = real_dir / "xp_events.jsonl"
        jsonl.symlink_to(sensitive)

        doubled = Path(str(safe_tmp) + "//xp")
        tracker = XPTracker(doubled)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.events()

    def test_dot_dot_in_xp_dir_still_refused(self, safe_tmp: Path) -> None:
        """``xp_dir`` traversal with ``..`` — symlink still refused."""
        from bonfire.xp.tracker import XPTracker

        real_dir = safe_tmp / "xp"
        real_dir.mkdir()

        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("payload\n")
        jsonl = real_dir / "xp_events.jsonl"
        jsonl.symlink_to(sensitive)

        traversed = safe_tmp / "xp" / ".." / "xp"
        tracker = XPTracker(traversed)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.events()


# ---------------------------------------------------------------------------
# Site 3 — cli/commands/init.py:84 gitignore append
# ---------------------------------------------------------------------------


class TestInitGitignoreAppendUsesSafeAppend:
    """``_ensure_gitignore_entry`` routes its append through safe_append_text.

    The pre-fix path is::

        if gitignore_path.is_symlink(): error
        ...
        gitignore_path.write_text(existing + suffix + line)

    The ``is_symlink`` pre-check leaves a TOCTOU window: an attacker
    racing between the check and the write can plant a symlink that
    redirects the appended content. The fix routes the append through
    ``safe_append_text`` whose ``O_NOFOLLOW`` flag closes the race.
    """

    def test_existing_gitignore_with_symlink_planted_after_pre_check_refused(
        self, safe_tmp: Path
    ) -> None:
        """A symlink at ``.gitignore`` is refused even when not pre-existing.

        Plant the symlink directly at ``.gitignore``; the hardened
        path's ``safe_append_text`` raises ``FileExistsError(symlink)``.
        """
        import typer

        from bonfire.cli.commands.init import (
            _GITIGNORE_LINE,
            _ensure_gitignore_entry,
        )

        # Pre-existing .gitignore with content that does NOT yet
        # contain the bonfire line — forces the append branch.
        gitignore = safe_tmp / ".gitignore"
        gitignore.write_text("# user content\nnode_modules/\n")

        # Replace the regular file with a symlink to a sensitive target.
        # In a race shape, an attacker swaps these two between the
        # pre-check and the write; here we just plant the symlink and
        # confirm the append helper refuses it.
        sensitive = safe_tmp / "sensitive.txt"
        sensitive.write_text("original-content\n")
        gitignore.unlink()
        gitignore.symlink_to(sensitive)

        # Pre-check raises typer.Exit; the symlink branch is also
        # exercised by the existing W7.M / W8.G work. The new lock:
        # the underlying append helper invocation refuses the symlink
        # with the W7.M error shape (FileExistsError mentioning
        # "symlink"). Drive the append directly to bypass the
        # pre-check branch and confirm safe_append_text is the floor.
        from bonfire._safe_write import safe_append_text

        with pytest.raises(FileExistsError, match="symlink"):
            safe_append_text(gitignore, f"{_GITIGNORE_LINE}\n")

        # Sensitive target byte-for-byte unchanged.
        assert sensitive.read_text() == "original-content\n"

        # Sanity: the pre-check ALSO refuses through typer.Exit so the
        # operator-facing exit code is preserved on the non-race path.
        with pytest.raises(typer.Exit):
            _ensure_gitignore_entry(safe_tmp, _GITIGNORE_LINE)

    def test_init_appends_via_safe_append_text(self, safe_tmp: Path) -> None:
        """The append branch in ``_ensure_gitignore_entry`` calls safe_append_text.

        Mock-and-assert: ``safe_append_text`` is the only function that
        writes new bytes into the existing ``.gitignore``. Wave 9's
        pre-existing fresh-file path still uses ``safe_write_text``;
        BON-1075 swaps the append branch from
        ``gitignore_path.write_text(...)`` to ``safe_append_text(...)``.
        """
        from unittest.mock import patch

        from bonfire.cli.commands.init import (
            _GITIGNORE_LINE,
            _ensure_gitignore_entry,
        )

        gitignore = safe_tmp / ".gitignore"
        gitignore.write_text("# user content\nnode_modules/\n")

        # Patch where it's used (bonfire.cli.commands.init imports
        # safe_append_text at module load), not where it's defined.
        with patch("bonfire.cli.commands.init.safe_append_text") as mock_append:
            _ensure_gitignore_entry(safe_tmp, _GITIGNORE_LINE)

        # Exactly one call against the .gitignore path with a trailing
        # newline payload that carries the bonfire line.
        assert mock_append.call_count == 1
        args, kwargs = mock_append.call_args
        called_path = args[0]
        called_content = args[1]
        assert called_path == gitignore
        assert _GITIGNORE_LINE in called_content
        assert called_content.endswith("\n")

    def test_init_fresh_gitignore_still_uses_safe_write_text(self, safe_tmp: Path) -> None:
        """Wave 9 ``safe_write_text`` for fresh file unchanged (no regression).

        BON-1075 only swaps the APPEND branch. The fresh-file create
        path still routes through ``safe_write_text`` so the W7.M
        ``O_EXCL`` guarantee survives.
        """
        from unittest.mock import patch

        from bonfire.cli.commands.init import (
            _GITIGNORE_LINE,
            _ensure_gitignore_entry,
        )

        # No pre-existing .gitignore — forces the fresh-file branch.
        with (
            patch("bonfire.cli.commands.init.safe_write_text") as mock_write,
            patch("bonfire.cli.commands.init.safe_append_text") as mock_append,
        ):
            _ensure_gitignore_entry(safe_tmp, _GITIGNORE_LINE)

        # Fresh-file path uses safe_write_text exactly once; the append
        # helper is not invoked.
        assert mock_write.call_count == 1
        assert mock_append.call_count == 0

    def test_init_idempotent_no_call_when_line_present(self, safe_tmp: Path) -> None:
        """Line already present → no write, no append (idempotent skip)."""
        from unittest.mock import patch

        from bonfire.cli.commands.init import (
            _GITIGNORE_LINE,
            _ensure_gitignore_entry,
        )

        gitignore = safe_tmp / ".gitignore"
        gitignore.write_text(f"# header\n{_GITIGNORE_LINE}\n")

        with (
            patch("bonfire.cli.commands.init.safe_write_text") as mock_write,
            patch("bonfire.cli.commands.init.safe_append_text") as mock_append,
        ):
            _ensure_gitignore_entry(safe_tmp, _GITIGNORE_LINE)

        assert mock_write.call_count == 0
        assert mock_append.call_count == 0


class TestInitGitignoreAppendAdversarialPaths:
    """Adversarial path shapes against the init gitignore append site."""

    def test_double_slash_target_dir_still_refused(self, safe_tmp: Path) -> None:
        """``project_dir`` with doubled separator — symlink still detected."""
        import typer

        from bonfire.cli.commands.init import (
            _GITIGNORE_LINE,
            _ensure_gitignore_entry,
        )

        # Plant a symlink at the real .gitignore path.
        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("payload\n")
        gitignore = safe_tmp / ".gitignore"
        gitignore.symlink_to(sensitive)

        doubled = Path(str(safe_tmp) + "//")

        with pytest.raises(typer.Exit):
            _ensure_gitignore_entry(doubled, _GITIGNORE_LINE)

        # Sensitive target survives unmodified.
        assert sensitive.read_text() == "payload\n"

    def test_dot_dot_target_dir_still_refused(self, safe_tmp: Path) -> None:
        """``project_dir`` traversal with ``..`` — symlink still refused."""
        import typer

        from bonfire.cli.commands.init import (
            _GITIGNORE_LINE,
            _ensure_gitignore_entry,
        )

        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("payload\n")
        gitignore = safe_tmp / ".gitignore"
        gitignore.symlink_to(sensitive)

        sub = safe_tmp / "child"
        sub.mkdir()
        traversed = sub / ".."

        with pytest.raises(typer.Exit):
            _ensure_gitignore_entry(traversed, _GITIGNORE_LINE)

        assert sensitive.read_text() == "payload\n"


# ---------------------------------------------------------------------------
# Cross-site lock — the wave-9-write-side is mirrored on the read side
# ---------------------------------------------------------------------------


class TestReadWriteSymmetricSurface:
    """The read-side guard is the read-side mirror of the W9 write guard.

    For each operator-controlled JSONL path, the same symlink shape is
    refused by both the append helper (Wave 9) and the read site
    (BON-1075). The symmetric refusal is the canon-grade defense.
    """

    def test_session_jsonl_symmetric_refusal(self, safe_tmp: Path) -> None:
        """Symlink at ``{session_id}.jsonl`` refused for both append + read."""
        from bonfire.models.events import PipelineStarted
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()

        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("must-not-touch\n")

        session_id = "sess_symmetric"
        jsonl = session_dir / f"{session_id}.jsonl"
        jsonl.symlink_to(sensitive)

        persistence = SessionPersistence(session_dir)
        event = PipelineStarted(
            session_id=session_id,
            sequence=0,
            plan_name="p",
            budget_usd=1.0,
        )

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.append_event(session_id, event)

        with pytest.raises(FileExistsError, match="symlink"):
            persistence.read_events(session_id)

        # Sensitive target survives both halves of the symmetric attack.
        assert sensitive.read_text() == "must-not-touch\n"

    def test_xp_jsonl_symmetric_refusal(self, safe_tmp: Path) -> None:
        """Symlink at ``xp_events.jsonl`` refused for both record + events."""
        from bonfire.xp.tracker import XPTracker

        xp_dir = safe_tmp / "xp"
        xp_dir.mkdir()

        sensitive = safe_tmp / "sensitive"
        sensitive.write_text("must-not-touch\n")

        jsonl = xp_dir / "xp_events.jsonl"
        jsonl.symlink_to(sensitive)

        tracker = XPTracker(xp_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.record(xp_total=10, success=True)

        with pytest.raises(FileExistsError, match="symlink"):
            tracker.events()

        assert sensitive.read_text() == "must-not-touch\n"


# ---------------------------------------------------------------------------
# JSON-parse contract preserved
# ---------------------------------------------------------------------------


class TestReadEventsJsonParsingPreserved:
    """``read_events`` still parses JSON-per-line semantics after the swap."""

    def test_read_events_preserves_per_line_parse(self, safe_tmp: Path) -> None:
        """Multiple events round-trip through append → read."""
        from bonfire.models.events import PipelineStarted
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        persistence = SessionPersistence(session_dir)

        for seq in range(3):
            persistence.append_event(
                "multi_session",
                PipelineStarted(
                    session_id="multi_session",
                    sequence=seq,
                    plan_name=f"plan-{seq}",
                    budget_usd=1.0,
                ),
            )

        events = persistence.read_events("multi_session")
        assert len(events) == 3
        plan_names = [e["plan_name"] for e in events]
        assert plan_names == ["plan-0", "plan-1", "plan-2"]

    def test_read_events_returns_list_of_dicts(self, safe_tmp: Path) -> None:
        """Return type stays ``list[dict]`` (public contract)."""
        from bonfire.session.persistence import SessionPersistence

        session_dir = safe_tmp / "sessions"
        session_dir.mkdir()
        jsonl = session_dir / "shape_session.jsonl"
        jsonl.write_text(json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2}) + "\n")

        persistence = SessionPersistence(session_dir)
        events = persistence.read_events("shape_session")
        assert events == [{"a": 1}, {"b": 2}]
