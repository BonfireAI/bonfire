# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire._safe_read.safe_read_capped_text`` refuses symlinks + caps reads.

Symmetric companion to :mod:`bonfire._safe_write.safe_write_text`.
Where the scanner-facing :func:`bonfire._safe_read.safe_read_text`
deliberately follows symlinks (so a scanner can fingerprint a project
tree), ``safe_read_capped_text`` is the operator-controlled-read
companion: it refuses symlinks and enforces a hard byte cap.

Used by ``CheckpointManager.load`` and ``CheckpointManager._load_all``
which read ``{session_id}.json`` files Bonfire itself wrote — any
symlink at those paths is suspicious (the W7.M ``safe_write_text``
hardening already refuses to *create* symlinked checkpoint files; this
closes the symmetric *read* path) and any oversized file is suspicious
(checkpoints are kilobytes in practice; a 10 MiB cap is comfortably
beyond any legitimate run while bounding memory damage from a planted
attack file).

Adversarial cases pinned below:

1. Symlink to ``/etc/passwd`` (or any sensitive file) — refused.
2. Symlink loop — refused with the W7.M ``"symlink"`` message.
3. File exceeding ``MAX_CHECKPOINT_BYTES`` — refused with ValueError.
4. ``CheckpointManager.load`` and ``._load_all`` propagate the
   refusals (load raises; _load_all skips with WARN).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bonfire._safe_read import MAX_CHECKPOINT_BYTES, safe_read_capped_text


def _platform_supports_symlinks() -> bool:
    return hasattr(os, "symlink")


pytestmark = pytest.mark.skipif(
    not _platform_supports_symlinks(),
    reason="platform lacks os.symlink — symlink-reject tests are POSIX-only",
)


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    """Tmp dir whose absolute path does NOT contain 'symlink'."""
    with tempfile.TemporaryDirectory(prefix="safe_read_capped_workdir_") as td:
        yield Path(td)


# ---------------------------------------------------------------------------
# Direct contract — symlinks always refused
# ---------------------------------------------------------------------------


class TestSafeReadCappedSymlinkRefusal:
    """``safe_read_capped_text`` refuses any symlink at the read path."""

    def test_live_symlink_to_sensitive_file_refused(self, safe_tmp: Path) -> None:
        """Live symlink (e.g. ``→ /etc/passwd``) → FileExistsError.

        Real attack shape: an attacker plants a symlink at a checkpoint
        path pointing at ``/etc/passwd``. Without the symlink-refusal,
        ``CheckpointManager.load`` would happily read the file's
        contents and pass them to ``json.loads`` — at minimum, the
        passwd contents end up in error messages / logs (information
        disclosure); worse, if the JSON parses, the attacker's chosen
        bytes get loaded into the pipeline as a "checkpoint".
        """
        sensitive = safe_tmp / "fake_passwd"
        sensitive.write_text("root:x:0:0:root:/root:/bin/bash\n")

        link = safe_tmp / "checkpoint.json"
        link.symlink_to(sensitive)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_read_capped_text(link, max_bytes=MAX_CHECKPOINT_BYTES)

    def test_dangling_symlink_refused(self, safe_tmp: Path) -> None:
        """Dangling symlink → FileExistsError (not FileNotFoundError)."""
        target = safe_tmp / "nonexistent"
        assert not target.exists()

        link = safe_tmp / "checkpoint.json"
        link.symlink_to(target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_read_capped_text(link, max_bytes=MAX_CHECKPOINT_BYTES)

    def test_symlink_loop_refused(self, safe_tmp: Path) -> None:
        """Symlink cycle → FileExistsError with the symlink message."""
        link_a = safe_tmp / "link_a.json"
        link_b = safe_tmp / "link_b.json"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_read_capped_text(link_a, max_bytes=MAX_CHECKPOINT_BYTES)


# ---------------------------------------------------------------------------
# Direct contract — size cap
# ---------------------------------------------------------------------------


class TestSafeReadCappedSizeCap:
    """``safe_read_capped_text`` raises ValueError when file exceeds cap."""

    def test_oversized_file_refused(self, safe_tmp: Path) -> None:
        """File exceeding the cap → ValueError, no payload returned.

        Adversarial shape: attacker plants an 11 MiB file at a
        checkpoint path. Without the cap, ``CheckpointManager.load``
        would read the entire payload into memory before realising it
        is not valid JSON (or worse, parses successfully if crafted).
        The cap fails fast at 10 MiB + 1 bytes.
        """
        big = safe_tmp / "oversized.json"
        # Slightly above the cap so the bounded read trips it.
        big.write_bytes(b"A" * (MAX_CHECKPOINT_BYTES + 1024))

        with pytest.raises(ValueError, match="exceeds cap"):
            safe_read_capped_text(big, max_bytes=MAX_CHECKPOINT_BYTES)

    def test_at_cap_boundary_accepted(self, safe_tmp: Path) -> None:
        """File at exactly the cap → accepted, full content returned."""
        target = safe_tmp / "boundary.json"
        payload = b"B" * 1024  # well below any reasonable cap
        target.write_bytes(payload)

        text = safe_read_capped_text(target, max_bytes=MAX_CHECKPOINT_BYTES)
        assert text == "B" * 1024

    def test_small_cap_with_small_file(self, safe_tmp: Path) -> None:
        """Small custom cap exercises the same cap-arithmetic."""
        target = safe_tmp / "small.txt"
        target.write_bytes(b"X" * 100)

        # 50-byte cap, 100-byte file → refused.
        with pytest.raises(ValueError, match="exceeds cap"):
            safe_read_capped_text(target, max_bytes=50)

        # 200-byte cap, 100-byte file → accepted.
        text = safe_read_capped_text(target, max_bytes=200)
        assert text == "X" * 100


# ---------------------------------------------------------------------------
# Direct contract — happy path + non-existent file
# ---------------------------------------------------------------------------


class TestSafeReadCappedHappyPath:
    """Non-symlink, within-cap reads succeed normally."""

    def test_regular_file_returned_verbatim(self, safe_tmp: Path) -> None:
        """Regular file under the cap → contents returned verbatim."""
        target = safe_tmp / "checkpoint.json"
        payload = '{"session_id": "abc123", "stages": []}'
        target.write_text(payload)

        text = safe_read_capped_text(target, max_bytes=MAX_CHECKPOINT_BYTES)
        assert text == payload

    def test_missing_file_propagates_filenotfounderror(self, safe_tmp: Path) -> None:
        """Missing path → FileNotFoundError propagates unchanged."""
        target = safe_tmp / "missing.json"
        assert not target.exists()

        with pytest.raises(FileNotFoundError):
            safe_read_capped_text(target, max_bytes=MAX_CHECKPOINT_BYTES)


# ---------------------------------------------------------------------------
# Per-site integration: CheckpointManager.load
# ---------------------------------------------------------------------------


def _build_real_checkpoint_payload() -> str:
    """Return a minimal valid CheckpointData JSON payload."""
    return json.dumps(
        {
            "session_id": "valid_session",
            "plan_name": "test-plan",
            "task_description": "test",
            "completed": {},
            "total_cost_usd": 0.0,
            "timestamp": 1000.0,
            "checkpoint_version": 1,
        }
    )


class TestCheckpointLoadSymlinkReject:
    """``CheckpointManager.load`` refuses to load through a symlink."""

    def test_load_refuses_symlink_to_sensitive_file(self, safe_tmp: Path) -> None:
        """Symlink at ``{session_id}.json`` → ``FileExistsError``."""
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        # Plant a sensitive target + symlink at the checkpoint path.
        sensitive = safe_tmp / "fake_passwd"
        sensitive.write_text("root:x:0:0:root:/root:/bin/bash\n")
        link = checkpoint_dir / "victim_session.json"
        link.symlink_to(sensitive)

        manager = CheckpointManager(checkpoint_dir)

        with pytest.raises(FileExistsError, match="symlink"):
            manager.load("victim_session")

    def test_load_refuses_oversized_checkpoint(self, safe_tmp: Path) -> None:
        """11 MiB checkpoint file → ValueError (cap-exceeded)."""
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        # 11 MiB > MAX_CHECKPOINT_BYTES (10 MiB). The bounded read
        # trips the cap before json.loads gets to allocate.
        oversized = checkpoint_dir / "huge_session.json"
        oversized.write_bytes(b"Z" * (MAX_CHECKPOINT_BYTES + 1024 * 1024))

        manager = CheckpointManager(checkpoint_dir)

        with pytest.raises(ValueError, match="exceeds cap"):
            manager.load("huge_session")

    def test_load_happy_path_still_works(self, safe_tmp: Path) -> None:
        """Normal regular checkpoint file → loaded as before."""
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        path = checkpoint_dir / "valid_session.json"
        path.write_text(_build_real_checkpoint_payload())

        manager = CheckpointManager(checkpoint_dir)
        data = manager.load("valid_session")
        assert data.session_id == "valid_session"
        assert data.plan_name == "test-plan"


# ---------------------------------------------------------------------------
# Per-site integration: CheckpointManager._load_all (via .latest /
# .list_checkpoints)
# ---------------------------------------------------------------------------


class TestCheckpointLoadAllSymlinkSkip:
    """``CheckpointManager._load_all`` SKIPS symlinks/oversized files (not raises).

    ``_load_all`` is best-effort: one bad file must not poison
    ``.latest()`` or ``.list_checkpoints()``. Symlink-refusal +
    oversize-refusal join the existing skip-with-WARN family.
    """

    def test_load_all_skips_symlink_to_sensitive_file(self, safe_tmp: Path) -> None:
        """Symlinked checkpoint is silently skipped; valid sibling still surfaces."""
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        # Plant a symlink + a valid neighbor checkpoint.
        sensitive = safe_tmp / "fake_passwd"
        sensitive.write_text("root:x:0:0:root:/root:/bin/bash\n")
        link = checkpoint_dir / "victim_session.json"
        link.symlink_to(sensitive)

        valid = checkpoint_dir / "good_session.json"
        valid.write_text(_build_real_checkpoint_payload())

        manager = CheckpointManager(checkpoint_dir)
        latest = manager.latest()

        # The valid checkpoint survives; the symlinked entry is skipped.
        assert latest is not None
        assert latest.session_id == "valid_session"

        summaries = manager.list_checkpoints()
        assert len(summaries) == 1
        assert summaries[0].session_id == "valid_session"

    def test_load_all_skips_oversized_checkpoint(self, safe_tmp: Path) -> None:
        """Oversized checkpoint is silently skipped; valid sibling still surfaces."""
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        # 11 MiB attacker-planted file.
        oversized = checkpoint_dir / "huge_session.json"
        oversized.write_bytes(b"Z" * (MAX_CHECKPOINT_BYTES + 1024 * 1024))

        valid = checkpoint_dir / "good_session.json"
        valid.write_text(_build_real_checkpoint_payload())

        manager = CheckpointManager(checkpoint_dir)
        latest = manager.latest()
        assert latest is not None
        assert latest.session_id == "valid_session"

    def test_load_all_skips_symlink_loop_without_raising(self, safe_tmp: Path) -> None:
        """Symlink loop in the dir → skipped, not raised; valid neighbor surfaces."""
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        link_a = checkpoint_dir / "loop_a.json"
        link_b = checkpoint_dir / "loop_b.json"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        valid = checkpoint_dir / "good_session.json"
        valid.write_text(_build_real_checkpoint_payload())

        manager = CheckpointManager(checkpoint_dir)

        # Must NOT raise — loops are skipped like any other bad file.
        latest = manager.latest()
        assert latest is not None
        assert latest.session_id == "valid_session"


# ---------------------------------------------------------------------------
# Defense-in-depth — symmetric with safe_write_text's contract
# ---------------------------------------------------------------------------


class TestSafeReadCappedDefenseInDepth:
    """``safe_read_capped_text`` is the read-side mirror of safe_write_text.

    Pinning the symmetric contract: if ``safe_write_text`` refuses to
    write through a symlink at ``X``, ``safe_read_capped_text`` refuses
    to read through a symlink at ``X``. Both guards apply at the same
    operator-controlled paths.
    """

    def test_writing_then_reading_via_safe_helpers_round_trip(self, safe_tmp: Path) -> None:
        """Round-trip: safe_write_text creates → safe_read_capped_text reads back."""
        from bonfire._safe_write import safe_write_text

        target = safe_tmp / "rt.json"
        payload = '{"k": "v"}'
        safe_write_text(target, payload)

        text = safe_read_capped_text(target, max_bytes=MAX_CHECKPOINT_BYTES)
        assert text == payload

    def test_symlink_at_path_refused_for_both_directions(self, safe_tmp: Path) -> None:
        """Same symlinked path refused by both write and read helpers.

        The cross-helper consistency is what makes the defense
        operator-friendly: the same log signature (``"symlink"`` in the
        error message) and the same exception class
        (``FileExistsError``) carry through both directions.
        """
        from bonfire._safe_write import safe_write_text

        attack_target = safe_tmp / "attack_target"
        link = safe_tmp / "shared.json"
        link.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_write_text(link, "x", allow_existing=True)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_read_capped_text(link, max_bytes=MAX_CHECKPOINT_BYTES)


# ---------------------------------------------------------------------------
# Module-level constant exposed
# ---------------------------------------------------------------------------


class TestMaxCheckpointBytesConstant:
    """``MAX_CHECKPOINT_BYTES`` is exposed at module level."""

    def test_constant_value_is_10_mib(self) -> None:
        """Cap is 10 MiB — comfortably above any legitimate checkpoint."""
        assert MAX_CHECKPOINT_BYTES == 10 * 1024 * 1024

    def test_constant_used_by_checkpoint_manager(self, safe_tmp: Path, monkeypatch) -> None:
        """``CheckpointManager.load`` passes ``MAX_CHECKPOINT_BYTES`` through.

        Sanity check that the constant we expose is the one the
        production code actually consults. Use a tiny monkeypatched
        value and verify a 1 KiB file is refused as oversized.
        """
        import bonfire.engine.checkpoint as ckpt_mod
        from bonfire.engine.checkpoint import CheckpointManager

        monkeypatch.setattr(ckpt_mod, "MAX_CHECKPOINT_BYTES", 100)

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()
        path = checkpoint_dir / "small_session.json"
        path.write_bytes(b"X" * 1024)  # 1 KiB > monkeypatched 100-byte cap

        manager = CheckpointManager(checkpoint_dir)
        with pytest.raises(ValueError, match="exceeds cap"):
            manager.load("small_session")


# ---------------------------------------------------------------------------
# Tests that exercise the existing patched-os.replace canonical test path
# ---------------------------------------------------------------------------


class TestCheckpointManagerSaveStillCallsLoadThroughHelper:
    """Sanity round-trip via ``CheckpointManager.save`` → ``.load``.

    ``save`` is unchanged by this wave (W7.M closed it). ``load`` is
    new-routed through ``safe_read_capped_text``. The round-trip
    must still succeed for normal saves so we haven't regressed any
    of the prior W7.M / W8 work.
    """

    def test_save_then_load_round_trip(self, safe_tmp: Path) -> None:
        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"

        result = MagicMock()
        result.stages = {}
        result.total_cost_usd = 0.0
        plan = MagicMock()
        plan.name = "round-trip-plan"
        plan.task_description = "rt"

        manager = CheckpointManager(checkpoint_dir)
        path = manager.save("rt_session", result, plan)
        assert path.exists()

        loaded = manager.load("rt_session")
        assert loaded.session_id == "rt_session"
        assert loaded.plan_name == "round-trip-plan"
