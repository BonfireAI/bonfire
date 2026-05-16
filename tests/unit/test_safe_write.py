# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire._safe_write.safe_write_text`` refuses to follow symlinks.

Companion module to ``bonfire._safe_read``. Centralises the
arbitrary-write defense W7.M established for ``write_config`` so the
same primitive can be reused at every operator-controlled write site
(``init.py``, ``persona.py``, ``checkpoint.py``, plus the existing
``scan.py`` + ``config_generator.py`` sites that W7.M originally
hardened).

The function under test:

.. code-block:: python

    safe_write_text(
        path: Path,
        content: str,
        *,
        allow_existing: bool = False,
    ) -> None

Semantics pinned by the RED tests below:

1. **Always refuse symlinks** at ``path`` (dangling, live, or loop).
   ``Path.is_symlink()`` check + ``O_NOFOLLOW`` defense-in-depth.
2. **By default refuse existing files** (``allow_existing=False`` /
   ``O_EXCL``) — preserves the W7.M overwrite-guard semantics. Callers
   that need to overwrite (e.g. ``checkpoint`` atomic-rename, or
   ``persona`` mutate-in-place) pass ``allow_existing=True`` which
   drops the ``O_EXCL`` flag but **keeps** the ``O_NOFOLLOW`` refusal.
3. **Symlink-refusal error** contains the literal substring
   ``"symlink"`` — log-grep contract carried forward from W7.M.
4. **Failure does not leak partial files** — if the write step
   raises, the half-written file is unlinked.

POSIX-only: skipped on platforms without ``os.symlink``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from bonfire._safe_write import safe_write_text


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


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    """Yield a tmp directory whose absolute path does NOT contain 'symlink'.

    pytest's built-in ``tmp_path`` fixture renders the test function
    name into the path. Tests that match on the ``"symlink"`` substring
    of the error message would false-GREEN if the path itself contained
    "symlink".
    """
    with tempfile.TemporaryDirectory(prefix="safe_write_workdir_") as td:
        yield Path(td)


def _snapshot(path: Path) -> tuple[bytes, int]:
    """Capture ``(content_bytes, inode)`` to prove untouched."""
    return path.read_bytes(), path.stat().st_ino


def _assert_unchanged(path: Path, snapshot: tuple[bytes, int]) -> None:
    content, inode = snapshot
    assert path.exists(), f"attack-target {path} disappeared (deletion via write)"
    assert path.read_bytes() == content, (
        f"attack-target {path} content was modified by the refused write"
    )
    assert path.stat().st_ino == inode, (
        f"attack-target {path} inode changed (delete-and-recreate via symlink)"
    )


# ---------------------------------------------------------------------------
# Direct helper contract — symlinks always refused
# ---------------------------------------------------------------------------


class TestSafeWriteTextDirectContract:
    """``safe_write_text`` refuses symlinks regardless of ``allow_existing``."""

    def test_dangling_symlink_refused_default(self, safe_tmp: Path) -> None:
        """Dangling symlink at target path → FileExistsError, attack target untouched."""
        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        link = safe_tmp / "config.toml"
        link.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_write_text(link, "[bonfire]\n")

        # Arbitrary-write primitive must NOT have fired.
        assert not attack_target.exists(), (
            f"attack target {attack_target} was created through the dangling symlink"
        )

    def test_live_symlink_refused_target_preserved(self, safe_tmp: Path) -> None:
        """Live symlink at target → refused, symlink target byte-for-byte preserved."""
        attack_target = safe_tmp / "sensitive"
        sensitive = b"ssh-rsa MUST_SURVIVE attacker@example\n"
        attack_target.write_bytes(sensitive)
        snapshot = _snapshot(attack_target)

        link = safe_tmp / "config.toml"
        link.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_write_text(link, "[bonfire]\n")

        _assert_unchanged(attack_target, snapshot)

    def test_symlink_loop_refused_cleanly(self, safe_tmp: Path) -> None:
        """Symlink cycle → FileExistsError mentioning symlink (no raw OSError leak)."""
        link_a = safe_tmp / "link_a"
        link_b = safe_tmp / "link_b"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_write_text(link_a, "[bonfire]\n")

    def test_symlink_refused_even_with_allow_existing(self, safe_tmp: Path) -> None:
        """``allow_existing=True`` still refuses symlinks — symlink reject is unconditional."""
        attack_target = safe_tmp / "attack_target"
        attack_target.write_bytes(b"sensitive\n")
        snapshot = _snapshot(attack_target)

        link = safe_tmp / "config.toml"
        link.symlink_to(attack_target)

        with pytest.raises(FileExistsError, match="symlink"):
            safe_write_text(link, "new content\n", allow_existing=True)

        _assert_unchanged(attack_target, snapshot)


# ---------------------------------------------------------------------------
# Direct helper contract — happy + existing-file paths
# ---------------------------------------------------------------------------


class TestSafeWriteTextExistingFile:
    """Non-symlink existing-file semantics gate on ``allow_existing``."""

    def test_nonexistent_path_writes(self, safe_tmp: Path) -> None:
        """Default invocation against a fresh path writes the content."""
        target = safe_tmp / "config.toml"
        assert not target.exists()

        safe_write_text(target, "[bonfire]\n")

        assert target.read_text() == "[bonfire]\n"
        assert not target.is_symlink(), "must produce a regular file"

    def test_existing_file_default_raises(self, safe_tmp: Path) -> None:
        """Default ``allow_existing=False`` against an existing regular file raises."""
        target = safe_tmp / "config.toml"
        original = b"# hand-tuned\n"
        target.write_bytes(original)
        snapshot = _snapshot(target)

        with pytest.raises(FileExistsError):
            safe_write_text(target, "new content\n")

        # Existing-file path raises BEFORE any write.
        _assert_unchanged(target, snapshot)

    def test_existing_file_with_allow_existing_overwrites(self, safe_tmp: Path) -> None:
        """``allow_existing=True`` permits overwriting a non-symlink regular file."""
        target = safe_tmp / "config.toml"
        target.write_bytes(b"old content\n")

        safe_write_text(target, "new content\n", allow_existing=True)

        assert target.read_text() == "new content\n"
        assert not target.is_symlink()

    def test_partial_write_failure_unlinks(self, safe_tmp: Path, monkeypatch) -> None:
        """If the write step crashes, no half-written file remains."""
        target = safe_tmp / "config.toml"

        # Force write() to raise after the fd is opened.
        real_fdopen = os.fdopen

        class _ExplodingFile:
            def __init__(self, real):
                self._real = real

            def write(self, *_args, **_kwargs):
                raise OSError("disk full")

            def close(self):
                self._real.close()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self._real.close()
                return False

        def fake_fdopen(fd, *a, **kw):
            return _ExplodingFile(real_fdopen(fd, *a, **kw))

        monkeypatch.setattr("bonfire._safe_write.os.fdopen", fake_fdopen)

        with pytest.raises(OSError, match="disk full"):
            safe_write_text(target, "[bonfire]\n")

        # Partial / empty file MUST be cleaned up.
        assert not target.exists(), (
            f"safe_write_text left a half-written file at {target} after a "
            "write-step failure"
        )


# ---------------------------------------------------------------------------
# Per-site integration: init.py
# ---------------------------------------------------------------------------


class TestInitSiteSymlinkReject:
    """``bonfire init`` must not write through a dangling symlink at bonfire.toml."""

    def test_init_refuses_dangling_symlink(self, safe_tmp: Path, monkeypatch) -> None:
        """``bonfire init`` against a dir with a dangling symlinked bonfire.toml refuses."""
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        toml = safe_tmp / "bonfire.toml"
        toml.symlink_to(attack_target)

        runner = CliRunner()
        result = runner.invoke(app, ["init", str(safe_tmp)])

        # Non-zero exit + arbitrary-write primitive never fired.
        assert result.exit_code != 0, (
            f"bonfire init followed a symlink and exited 0; output:\n{result.output}"
        )
        assert not attack_target.exists(), (
            f"attack target {attack_target} was created through the symlink "
            f"by bonfire init; output:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# Per-site integration: persona.py
# ---------------------------------------------------------------------------


class TestPersonaSiteSymlinkReject:
    """``bonfire persona set`` must not write through a dangling symlink."""

    def test_persona_set_refuses_dangling_symlink(self, safe_tmp: Path, monkeypatch) -> None:
        """``bonfire persona set`` against a dangling symlinked bonfire.toml refuses."""
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        toml = safe_tmp / "bonfire.toml"
        toml.symlink_to(attack_target)

        # persona set runs against Path.cwd() — temporarily chdir into safe_tmp.
        monkeypatch.chdir(safe_tmp)

        runner = CliRunner()
        # falcor is the default built-in persona; if persona list discovery
        # fails on the symlink the command exits non-zero anyway.
        result = runner.invoke(app, ["persona", "set", "falcor"])

        assert result.exit_code != 0, (
            f"bonfire persona set followed a symlink and exited 0; "
            f"output:\n{result.output}"
        )
        assert not attack_target.exists(), (
            f"attack target {attack_target} was created through the symlink "
            f"by bonfire persona set; output:\n{result.output}"
        )

    def test_persona_set_refuses_dangling_symlink_when_no_prior_toml(
        self, safe_tmp: Path, monkeypatch
    ) -> None:
        """No prior bonfire.toml but symlink planted → still refused.

        Covers the persona.py branch that writes a fresh stub when the
        TOML does not pre-exist as a regular file. ``Path.exists()`` on
        a dangling symlink returns False, so without symlink-hardening
        this branch was the dominant arbitrary-write primitive.
        """
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        toml = safe_tmp / "bonfire.toml"
        toml.symlink_to(attack_target)

        # Sanity: Path.exists() returns False on the dangling symlink so
        # the persona.py "else" branch (write fresh stub) would be taken
        # without the symlink-reject hardening.
        assert toml.is_symlink()
        assert not toml.exists()

        monkeypatch.chdir(safe_tmp)
        runner = CliRunner()
        result = runner.invoke(app, ["persona", "set", "falcor"])

        assert result.exit_code != 0
        assert not attack_target.exists()


# ---------------------------------------------------------------------------
# Per-site integration: checkpoint.py
# ---------------------------------------------------------------------------


class TestCheckpointSiteSymlinkReject:
    """``CheckpointManager.save`` must not write through a dangling symlink."""

    def test_checkpoint_save_refuses_dangling_symlink_at_tmp_path(
        self, safe_tmp: Path
    ) -> None:
        """Dangling symlink planted at ``{session_id}.json.tmp`` is refused.

        ``CheckpointManager.save`` writes to ``{session_id}.json.tmp``
        with ``write_text`` (follows symlinks) then ``os.replace`` to
        ``{session_id}.json``. The ``.tmp`` write is the
        arbitrary-write primitive: a malicious symlink at the tmp path
        redirects the JSON payload to an attacker-controlled target.
        """
        from unittest.mock import MagicMock

        from bonfire.engine.checkpoint import CheckpointManager

        checkpoint_dir = safe_tmp / "checkpoints"
        checkpoint_dir.mkdir()

        session_id = "session_under_attack"
        attack_target = safe_tmp / "attack_target"
        assert not attack_target.exists()

        # Plant the dangling symlink at the tmp-write target.
        tmp_path = checkpoint_dir / f"{session_id}.json.tmp"
        tmp_path.symlink_to(attack_target)

        manager = CheckpointManager(checkpoint_dir)

        # Mock result + plan with the minimal surface CheckpointManager.save uses.
        result = MagicMock()
        result.stages = {}
        result.total_cost_usd = 0.0
        plan = MagicMock()
        plan.name = "test-plan"
        plan.task_description = "test"

        with pytest.raises((FileExistsError, OSError)):
            manager.save(session_id, result, plan)

        # The arbitrary-write primitive must NOT have fired.
        assert not attack_target.exists(), (
            f"checkpoint.save followed the symlink and created "
            f"{attack_target}"
        )
