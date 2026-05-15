# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire scan`` refuses to overwrite an existing ``bonfire.toml``.

Mirrors the existing guard pattern in ``bonfire.cli.commands.init`` (line 21:
``if not toml_path.exists(): toml_path.write_text(...)``). Scan previously
went straight to ``target.write_text(config_toml)`` with no exists-check,
destroying any hand-tuned ``bonfire.toml`` in the directory.

Two layers pinned here:

1. ``config_generator.write_config`` is the canonical writer; it raises
   ``FileExistsError`` with a clear, recovery-pointing message when the
   target already exists. This defends every future programmatic caller.

2. ``bonfire scan`` (CLI surface) fails fast — before starting the
   WebSocket server / browser dance — with a clean stderr message and a
   non-zero exit code when ``bonfire.toml`` already exists in CWD. This
   is the user-visible day-1 contract.

No ``--force`` flag in v0.1 — recovery is ``mv bonfire.toml bonfire.toml.bak``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.onboard.config_generator import write_config

runner = CliRunner()


# ---------------------------------------------------------------------------
# Layer 1 — ``write_config`` raises FileExistsError on collision
# ---------------------------------------------------------------------------


class TestWriteConfigOverwriteGuard:
    """``write_config`` refuses to clobber an existing ``bonfire.toml``."""

    def test_write_config_clean_directory_writes_file(self, tmp_path: Path) -> None:
        """Happy path: no existing bonfire.toml; write succeeds and returns path."""
        config_toml = '[bonfire]\nname = "demo"\n'
        result = write_config(config_toml, tmp_path)

        assert result == tmp_path / "bonfire.toml"
        assert result.read_text() == config_toml

    def test_write_config_existing_bonfire_toml_raises(self, tmp_path: Path) -> None:
        """When bonfire.toml exists, write_config raises FileExistsError.

        The existing file must be preserved byte-for-byte after the failed
        call.
        """
        existing = tmp_path / "bonfire.toml"
        original = '# hand-tuned\n[bonfire]\nname = "original"\n'
        existing.write_text(original)

        new_content = '[bonfire]\nname = "overwritten"\n'

        with pytest.raises(FileExistsError):
            write_config(new_content, tmp_path)

        # CRITICAL: existing content untouched.
        assert existing.read_text() == original, (
            "write_config must not modify the existing bonfire.toml when refusing to overwrite"
        )

    def test_write_config_error_message_is_actionable(self, tmp_path: Path) -> None:
        """Error message names the path and points the user toward recovery.

        The user has to know (a) which file blocked the write and (b) how
        to recover. The message must contain the path and a recovery hint
        ("Remove", "move", or similar) — verbatim phrasing is not pinned,
        but the actionable shape is.
        """
        existing = tmp_path / "bonfire.toml"
        existing.write_text("[bonfire]\n")

        with pytest.raises(FileExistsError) as exc_info:
            write_config('[bonfire]\nname = "x"\n', tmp_path)

        msg = str(exc_info.value)
        assert str(existing) in msg or "bonfire.toml" in msg, (
            f"error message must reference the blocked path; got: {msg!r}"
        )
        # Recovery-hint markers — at least one must appear.
        recovery_markers = ("remove", "move", "rename", "delete", "rerun", "re-run")
        msg_lower = msg.lower()
        assert any(m in msg_lower for m in recovery_markers), (
            f"error message must hint at recovery (one of {recovery_markers!r}); got: {msg!r}"
        )


# ---------------------------------------------------------------------------
# Layer 2 — ``bonfire scan`` CLI fails fast with a clean exit
# ---------------------------------------------------------------------------


class TestScanCommandRefusesOverwrite:
    """``bonfire scan`` exits non-zero before starting the server when
    ``bonfire.toml`` already exists in CWD.

    Failing FAST (before browser/server) matters: the user has not yet
    invested any time in the conversation flow when the guard trips.
    """

    def test_scan_with_existing_bonfire_toml_exits_nonzero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`bonfire scan` in a directory with existing bonfire.toml exits non-zero."""
        existing = tmp_path / "bonfire.toml"
        original = '# hand-tuned config\n[bonfire]\nname = "keep-me"\n'
        existing.write_text(original)

        monkeypatch.chdir(tmp_path)

        # If the guard fails to fire, _run_scan would start the server.
        # Mock it so a green test still proves the early-exit path (and
        # so a regression that bypasses the guard surfaces as the mock
        # being called).
        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must exit non-zero when bonfire.toml already exists; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        # The guard MUST fire before _run_scan is called — no server work
        # should happen.
        assert not mock_run.called, (
            "scan must fail before starting the Front Door server when bonfire.toml already exists"
        )
        # Existing file untouched.
        assert existing.read_text() == original

    def test_scan_with_existing_bonfire_toml_prints_actionable_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The error message names the file and tells the user how to recover."""
        existing = tmp_path / "bonfire.toml"
        existing.write_text("[bonfire]\n")
        monkeypatch.chdir(tmp_path)

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        combined = (result.output or "") + (result.stderr or "")
        assert "bonfire.toml" in combined, (
            f"error message must mention bonfire.toml; got: {combined!r}"
        )
        recovery_markers = ("remove", "move", "rename", "delete", "rerun", "re-run")
        combined_lower = combined.lower()
        assert any(m in combined_lower for m in recovery_markers), (
            f"scan error must hint at recovery (one of {recovery_markers!r}); got: {combined!r}"
        )

    def test_scan_in_clean_directory_still_proceeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Happy path preserved: no existing bonfire.toml -> _run_scan invoked."""
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "bonfire.toml").exists()

        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code == 0, (
            f"scan in a clean directory must succeed; got exit_code="
            f"{result.exit_code}, output={result.output!r}"
        )
        mock_run.assert_called_once()


# Layer 3 (defense in depth — write_config raising mid-flow) is implicitly
# covered by Layer 1: ``write_config`` raises ``FileExistsError`` on every
# call path, including the one inside ``run_front_door``. Pinning the flow
# layer would require constructing a fully-mocked Front Door server +
# conversation engine and is fragile — the function-level pin is enough.
