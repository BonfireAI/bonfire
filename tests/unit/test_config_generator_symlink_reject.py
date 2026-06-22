# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``write_config`` refuses to follow symlinks.

The prior overwrite-guard at ``write_config`` used ``Path.exists()``.
``Path.exists()`` **follows symlinks** — so a dangling symlink
``bonfire.toml -> /attacker/path`` satisfies ``exists() == False`` and the
function proceeds to ``target.write_text(...)``, which OPENS THE SYMLINK
TARGET in write+truncate mode. Arbitrary-write primitive.

The fix specified here by RED tests:

1. Check ``target.is_symlink()`` explicitly **before** ``exists()``. Refuse
   any symlink — dangling or live — with a clear ``FileExistsError``.
2. Switch the write itself to ``os.open(target, O_CREAT | O_EXCL | O_NOFOLLOW, ...)``
   wrapped in ``os.fdopen`` so a TOCTOU race between check and write
   cannot bypass the refusal.

This file pins the contract at the function-level entry point
(``write_config``). Its companion ``test_scan_symlink_reject.py`` pins the
same contract at the CLI surface.

Exception contract: ``write_config`` MUST raise ``FileExistsError`` whose
message contains the substring ``symlink``. Reusing ``FileExistsError``
keeps the existing caller catch valid; the "symlink" substring lets
callers distinguish symlink-refusal from regular collision for log-grep
purposes. Tests use ``pytest.raises(FileExistsError, match="symlink")``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from bonfire.onboard.config_generator import write_config

# Minimal valid TOML for write_config to attempt to write.
SAMPLE_CONFIG = '[bonfire]\nname = "demo"\n'


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    """Yield a tmp directory whose absolute path does NOT contain 'symlink'.

    pytest's built-in ``tmp_path`` fixture renders the test function name
    into the path. Every test in this file has "symlink" in its name, so
    ``tmp_path`` would smuggle "symlink" into the target path that the
    overwrite-guard's ``FileExistsError`` message embeds — producing
    false-GREEN ``pytest.raises(..., match="symlink")`` matches. This
    fixture uses ``tempfile.TemporaryDirectory`` with a fixed neutral
    prefix so the regex match reflects ONLY the error message author's
    intent.
    """
    with tempfile.TemporaryDirectory(prefix="symlink_reject_workdir_") as td:
        yield Path(td)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(path: Path) -> tuple[bytes, int]:
    """Return ``(content_bytes, inode)`` for a file we want to prove untouched."""
    return path.read_bytes(), path.stat().st_ino


def _assert_unchanged(path: Path, snapshot: tuple[bytes, int]) -> None:
    """Assert ``path`` content + inode match the captured snapshot."""
    content, inode = snapshot
    assert path.exists(), (
        f"attack-target file {path} must still exist after the refused write; "
        "missing means the symlink-write path destroyed it"
    )
    assert path.read_bytes() == content, (
        f"attack-target file {path} content was modified by the refused write_config; "
        "the symlink was followed and the target was truncated/rewritten"
    )
    assert path.stat().st_ino == inode, (
        f"attack-target file {path} inode changed after the refused write_config; "
        "the symlink target was unlinked-and-recreated"
    )


# ---------------------------------------------------------------------------
# Tests 6-10 — write_config refuses symlinks
# ---------------------------------------------------------------------------


class TestWriteConfigSymlinkReject:
    """``write_config`` refuses to clobber a symlink at ``project_path/bonfire.toml``.

    Each test plants a ``bonfire.toml`` symlink in ``tmp_path``, calls
    ``write_config(SAMPLE_CONFIG, tmp_path)``, asserts ``FileExistsError``
    with a "symlink" message, and verifies the (fake) attack target is
    byte-for-byte intact.
    """

    def test_dangling_symlink_to_fake_authorized_keys_raises(
        self,
        safe_tmp: Path,
    ) -> None:
        """RED (Test 6) — dangling symlink to a non-existent attack target.

        Today's behavior: ``Path.exists()`` returns False (symlink target
        doesn't exist), guard does NOT trip, ``write_text`` opens the
        symlink, follows it, creates the target with our config content.

        Expected post-fix: ``FileExistsError`` raised, attack target never
        materializes.
        """
        attack_target = safe_tmp / "fake_authorized_keys"
        assert not attack_target.exists()

        toml_path = safe_tmp / "bonfire.toml"
        toml_path.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            write_config(SAMPLE_CONFIG, safe_tmp)

        # CRITICAL — the arbitrary-write primitive must NOT have fired.
        assert not attack_target.exists(), (
            f"attack target {attack_target} was created through the dangling "
            f"symlink — write_config followed the symlink and the "
            "overwrite-guard bypass is OPEN"
        )

    def test_live_symlink_to_existing_target_raises_and_preserves_target(
        self,
        safe_tmp: Path,
    ) -> None:
        """RED (Test 7) — live symlink to an existing target with content.

        Today's behavior: ``Path.exists()`` returns True (the SYMLINK
        TARGET exists), the existing-message ``FileExistsError`` fires —
        but the message says "already exists", not "symlink", so the user
        cannot distinguish a symlink attack from a normal collision. And
        a TOCTOU race between the check and ``write_text`` can still
        clobber the target.

        Expected post-fix: ``FileExistsError`` with a "symlink" message,
        target byte-for-byte preserved (the existing-file path raises
        before any write).
        """
        attack_target = safe_tmp / "fake_authorized_keys"
        sensitive = b"ssh-rsa AAAAATTACKER_KEY_MUST_SURVIVE attacker@example\n"
        attack_target.write_bytes(sensitive)
        snapshot = _snapshot(attack_target)

        toml_path = safe_tmp / "bonfire.toml"
        toml_path.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            write_config(SAMPLE_CONFIG, safe_tmp)

        # The attack-target content+inode must be byte-for-byte preserved.
        _assert_unchanged(attack_target, snapshot)

    def test_symlink_loop_raises_cleanly(
        self,
        safe_tmp: Path,
    ) -> None:
        """RED (Test 8) — symlink cycle does not hang or surface raw OSError.

        Pre-conditions:
          * ``bonfire.toml -> bonfire.toml.alt``
          * ``bonfire.toml.alt -> bonfire.toml``

        Today's behavior: ``Path.exists()`` on a symlink loop returns False
        on some platforms (ELOOP suppressed), True on others. Either way
        the subsequent ``write_text`` will OSError with ELOOP — a raw,
        non-actionable traceback. Worse: in TOCTOU contexts the loop may
        be unwound by a race and the write proceeds.

        Expected post-fix: clean ``FileExistsError`` with "symlink" mention.
        No ``OSError`` leaking out.
        """
        toml_path = safe_tmp / "bonfire.toml"
        alt_path = safe_tmp / "bonfire.toml.alt"
        toml_path.symlink_to(alt_path)
        alt_path.symlink_to(toml_path)

        # Sanity: cycle exists and is_symlink() works without resolution.
        assert toml_path.is_symlink()

        # NB: ``pytest.raises(FileExistsError)`` will fail if write_config
        # raises ``OSError`` (likely behavior on a loop without the fix).
        # That is the desired RED signal — the implementation must convert
        # the OSError path into the FileExistsError path.
        with pytest.raises(FileExistsError, match="symlink"):
            write_config(SAMPLE_CONFIG, safe_tmp)

    def test_regular_file_with_content_still_raises(
        self,
        safe_tmp: Path,
    ) -> None:
        """SMOKE (Test 9) — prior happy-path preserved: regular file refused.

        A real (non-symlink) ``bonfire.toml`` must still trigger the prior
        overwrite-guard. This pin guards against the symlink hardening
        accidentally narrowing the guard to "symlinks only".

        The "match" pin here is ``"bonfire.toml"`` not ``"symlink"`` —
        a regular-file collision message should still reference the path.
        """
        existing = safe_tmp / "bonfire.toml"
        original = b'# hand-tuned\n[bonfire]\nname = "original"\n'
        existing.write_bytes(original)
        snapshot = _snapshot(existing)

        with pytest.raises(FileExistsError, match="bonfire.toml"):
            write_config(SAMPLE_CONFIG, safe_tmp)

        # Existing-file path raises BEFORE any write, so content is unchanged.
        _assert_unchanged(existing, snapshot)

    def test_clean_directory_happy_path_writes_file(
        self,
        safe_tmp: Path,
    ) -> None:
        """SMOKE (Test 10) — clean directory, file written.

        Confirms the symlink-reject hardening does NOT regress the
        clean-directory write path.
        """
        # Sanity: no file, no symlink.
        toml_path = safe_tmp / "bonfire.toml"
        assert not toml_path.exists()
        assert not toml_path.is_symlink()

        result = write_config(SAMPLE_CONFIG, safe_tmp)

        assert result == toml_path
        assert result.read_text() == SAMPLE_CONFIG
        # And it's a regular file, NOT a symlink — the write created a
        # fresh file, did not somehow leave a symlink in place.
        assert not result.is_symlink(), "write_config must produce a regular file, never a symlink"


# ---------------------------------------------------------------------------
# Platform gate — symlink support required.
# ---------------------------------------------------------------------------


def _platform_supports_symlinks() -> bool:
    """Return True iff the current platform/user can create symlinks."""
    return hasattr(os, "symlink")


pytestmark = pytest.mark.skipif(
    not _platform_supports_symlinks(),
    reason="platform lacks os.symlink — symlink-reject tests are POSIX-only",
)
