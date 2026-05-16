# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire scan`` refuses to follow symlinks at the overwrite-guard.

The prior overwrite-guard on ``bonfire scan`` used ``Path.exists()``.
``Path.exists()`` **follows symlinks** — which means a dangling symlink
at ``bonfire.toml -> some/attacker/target`` satisfies ``exists() == False``.
The guard then proceeds to the write path, which opens the symlink target
in write+truncate mode. This is an **arbitrary-write primitive** via
attacker-controlled dangling symlink.

The fix specified here by RED tests:

1. Check ``target.is_symlink()`` explicitly **before** ``exists()``.
   Refuse any symlink — dangling or live.
2. Open with ``os.open(..., O_CREAT | O_EXCL | O_NOFOLLOW)`` so even a
   TOCTOU race between the check and the write cannot bypass the guard.

This file pins the contract at the CLI layer (``bonfire.cli.commands.scan``).
Its companion ``test_config_generator_symlink_reject.py`` pins the same
contract at the lower-level ``write_config`` entry point.

Exception contract: the implementation MUST raise ``FileExistsError`` whose
message mentions the word "symlink". Reusing ``FileExistsError`` keeps the
existing caller (``_run_scan``) catch-clause valid; the "symlink"
substring lets callers distinguish symlink-refusal from regular collision
for log-grep purposes. Tests use ``pytest.raises(FileExistsError,
match="symlink")`` and assert the same substring in CLI stderr.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app

runner = CliRunner()


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    """Yield a tmp directory whose absolute path does NOT contain 'symlink'.

    pytest's built-in ``tmp_path`` fixture renders the test function name
    into the path. Every test in this file has "symlink" in its name, so
    ``tmp_path`` would smuggle "symlink" into every error-message-rendered
    path — producing false-GREEN assertions like ``"symlink" in stderr``.
    This fixture uses ``tempfile.TemporaryDirectory`` with a fixed neutral
    prefix so path-substring checks reflect ONLY the error message
    author's intent.
    """
    with tempfile.TemporaryDirectory(prefix="w7m_workdir_") as td:
        yield Path(td)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(path: Path) -> tuple[bytes, int]:
    """Return ``(content_bytes, inode)`` for a file we want to prove untouched.

    Inode pin lets us detect a delete-and-recreate as well as a truncate.
    """
    return path.read_bytes(), path.stat().st_ino


def _assert_unchanged(path: Path, snapshot: tuple[bytes, int]) -> None:
    """Assert ``path`` content + inode match the captured snapshot."""
    content, inode = snapshot
    assert path.exists(), (
        f"attack-target file {path} must still exist after the refused scan; "
        "missing means the symlink-write path destroyed it"
    )
    assert path.read_bytes() == content, (
        f"attack-target file {path} content was modified by the refused scan; "
        "the symlink was followed and the target was truncated/rewritten"
    )
    assert path.stat().st_ino == inode, (
        f"attack-target file {path} inode changed after the refused scan; "
        "the symlink target was unlinked-and-recreated"
    )


# ---------------------------------------------------------------------------
# Tests 1-5 — scan CLI overwrite-guard refuses symlinks
# ---------------------------------------------------------------------------


class TestScanSymlinkReject:
    """``bonfire scan`` refuses to proceed when ``bonfire.toml`` is a symlink.

    Each test sets up a fake "attack target" (a stand-in for the real-world
    ``~/.ssh/authorized_keys`` an attacker would aim at) INSIDE ``tmp_path``,
    pointed at by a ``bonfire.toml`` symlink in CWD. After the scan command
    refuses, we verify the attack target's content and inode are intact.
    """

    def test_dangling_symlink_to_fake_authorized_keys_refused(
        self,
        safe_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RED — dangling symlink to a (currently non-existent) attack target.

        Pre-conditions:
          * ``safe_tmp/fake_authorized_keys`` does NOT exist yet.
          * ``safe_tmp/bonfire.toml -> safe_tmp/fake_authorized_keys`` (dangling).

        Expected:
          * ``bonfire scan`` exits non-zero with a "symlink" mention in stderr.
          * Internal ``_run_scan`` is NOT invoked (fast-fail).
          * ``fake_authorized_keys`` is STILL non-existent — the write path
            did NOT create-and-truncate it through the symlink.
        """
        attack_target = safe_tmp / "fake_authorized_keys"
        # Deliberately do NOT create attack_target; the symlink dangles.
        assert not attack_target.exists()

        toml_path = safe_tmp / "bonfire.toml"
        toml_path.symlink_to(attack_target)

        monkeypatch.chdir(safe_tmp)

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must refuse a dangling-symlink bonfire.toml; got exit_code="
            f"{result.exit_code}, output={result.output!r}"
        )
        assert not mock_run.called, (
            "scan must fail BEFORE starting the Front Door server when bonfire.toml is a symlink"
        )
        combined = (result.output or "") + (result.stderr or "")
        assert "symlink" in combined.lower(), (
            f"scan stderr must explain the refusal mentions a symlink; got: {combined!r}"
        )

        # CRITICAL — the arbitrary-write primitive must NOT have fired.
        assert not attack_target.exists(), (
            f"attack target {attack_target} was created through the symlink — "
            "the dangling-symlink overwrite-guard bypass is OPEN"
        )

    def test_live_symlink_to_existing_file_refused(
        self,
        safe_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RED — live symlink to an existing file with content.

        Pre-conditions:
          * ``safe_tmp/fake_authorized_keys`` exists with attacker-readable
            content (proxy for the real ``~/.ssh/authorized_keys`` value
            we never want to clobber).
          * ``safe_tmp/bonfire.toml -> safe_tmp/fake_authorized_keys`` (live).

        Expected:
          * ``bonfire scan`` exits non-zero.
          * ``fake_authorized_keys`` content and inode UNCHANGED post-scan.

        Note: ``Path.exists()`` returns True here, so the prior guard
        already trips — but it trips with a generic "already exists" message
        and (in a TOCTOU race window) still lets ``write_text`` follow the
        symlink. The pin: the message must mention ``symlink`` so the user
        understands what was actually refused; behavior must be the same
        once the implementation switches to ``is_symlink()`` + ``O_NOFOLLOW``.
        """
        attack_target = safe_tmp / "fake_authorized_keys"
        sensitive = b"ssh-rsa AAAAATTACKER_KEY_MUST_SURVIVE attacker@example\n"
        attack_target.write_bytes(sensitive)
        snapshot = _snapshot(attack_target)

        toml_path = safe_tmp / "bonfire.toml"
        toml_path.symlink_to(attack_target)

        monkeypatch.chdir(safe_tmp)

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must refuse a live-symlink bonfire.toml; got exit_code="
            f"{result.exit_code}, output={result.output!r}"
        )
        assert not mock_run.called, (
            "scan must fail-fast on a symlinked bonfire.toml, before server start"
        )
        combined = (result.output or "") + (result.stderr or "")
        assert "symlink" in combined.lower(), (
            f"scan stderr must mention 'symlink' for a symlinked bonfire.toml; got: {combined!r}"
        )

        # The attack-target content+inode must be byte-for-byte preserved.
        _assert_unchanged(attack_target, snapshot)

    def test_symlink_loop_refused_without_hang_or_oserror(
        self,
        safe_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RED — symlink cycle: bonfire.toml -> bonfire.toml.alt -> bonfire.toml.

        Pre-conditions:
          * ``bonfire.toml -> bonfire.toml.alt``
          * ``bonfire.toml.alt -> bonfire.toml``

        Expected:
          * Scan exits non-zero cleanly with a "symlink" message.
          * No ``OSError(ELOOP)`` traceback in user output.
          * Test wall time is bounded (no infinite loop / no recursive
            resolution).
        """
        toml_path = safe_tmp / "bonfire.toml"
        alt_path = safe_tmp / "bonfire.toml.alt"
        toml_path.symlink_to(alt_path)
        alt_path.symlink_to(toml_path)

        # Sanity: cycle exists and is_symlink() returns True without
        # resolving the target (otherwise ELOOP would surface here).
        assert toml_path.is_symlink()

        monkeypatch.chdir(safe_tmp)

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must refuse a symlink-loop bonfire.toml; got exit_code="
            f"{result.exit_code}, output={result.output!r}"
        )
        assert not mock_run.called

        combined = (result.output or "") + (result.stderr or "")
        # No raw traceback leaking the OSError.
        assert "Traceback" not in combined, (
            f"symlink loop must not raise a raw traceback; got: {combined!r}"
        )
        # Symlink-explanation must surface (loop is still a symlink case).
        assert "symlink" in combined.lower(), (
            f"scan stderr must mention 'symlink' for a symlink loop; got: {combined!r}"
        )

    def test_regular_file_with_content_still_refused(
        self,
        safe_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SMOKE — prior happy-path preserved: regular file collision refuses.

        A user with a hand-tuned ``bonfire.toml`` (real file, not a symlink)
        must still see the prior overwrite-guard fire. This pin guards
        against the symlink hardening accidentally narrowing the guard to
        "symlinks only" and breaking the original contract.
        """
        existing = safe_tmp / "bonfire.toml"
        original = b'# hand-tuned\n[bonfire]\nname = "keep-me"\n'
        existing.write_bytes(original)
        snapshot = _snapshot(existing)

        monkeypatch.chdir(safe_tmp)

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must refuse to overwrite a regular bonfire.toml; got "
            f"exit_code={result.exit_code}"
        )
        assert not mock_run.called
        _assert_unchanged(existing, snapshot)

    def test_clean_directory_happy_path_still_proceeds(
        self,
        safe_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SMOKE — happy-path: no file present -> _run_scan invoked.

        Confirms the symlink-reject hardening does NOT break the case where
        no ``bonfire.toml`` (real or symlinked) exists in CWD.
        """
        monkeypatch.chdir(safe_tmp)
        assert not (safe_tmp / "bonfire.toml").exists()
        assert not (safe_tmp / "bonfire.toml").is_symlink()

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code == 0, (
            f"scan in a clean directory must succeed; got exit_code="
            f"{result.exit_code}, output={result.output!r}"
        )
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Pin: the platform must support symlinks (POSIX). All assertions above
# assume ``Path.symlink_to`` works. On Windows in CI without developer-mode,
# ``symlink_to`` raises ``OSError``; skip the file entirely in that case
# rather than reporting a false RED.
# ---------------------------------------------------------------------------


def _platform_supports_symlinks() -> bool:
    """Return True iff the current platform/user can create symlinks."""
    return hasattr(os, "symlink")


pytestmark = pytest.mark.skipif(
    not _platform_supports_symlinks(),
    reason="platform lacks os.symlink — symlink-reject tests are POSIX-only",
)
