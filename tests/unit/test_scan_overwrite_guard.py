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


# ---------------------------------------------------------------------------
# Layer 3 — TOCTOU between pre-flow check and post-flow write_config
# ---------------------------------------------------------------------------


class TestScanRunHandlesPostFlowFileExistsError:
    """``_run_scan`` must catch FileExistsError from the post-flow write.

    The CLI's pre-flow ``Path.exists()`` check (line 97 of scan.py) catches
    the happy path. But the conversation flow inside ``run_front_door`` is
    where ``write_config`` is actually called. If a concurrent process
    creates ``bonfire.toml`` AFTER the pre-flow check and BEFORE
    ``write_config`` writes, the function-level ``FileExistsError`` raised
    by ``write_config`` would propagate as a raw traceback through
    ``_run_scan``. Users see Python noise instead of a clean exit.

    This test simulates the TOCTOU: ``run_front_door`` is mocked to raise
    ``FileExistsError`` (matching the post-flow write that found the file
    already in place). ``_run_scan`` must catch it, exit cleanly via
    ``typer.Exit(code=1)`` with a stderr message, and not propagate the
    traceback.
    """

    def test_toctou_post_flow_fileexists_clean_exit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_front_door raising FileExistsError post-flow -> clean Exit(1).

        Pre-flow check sees a clean directory; the conversation engine
        races a concurrent process; ``write_config`` raises mid-flow.
        ``_run_scan`` must surface a clean stderr message and exit 1.
        """
        monkeypatch.chdir(tmp_path)
        # Sanity: directory clean at the start (pre-flow check passes).
        assert not (tmp_path / "bonfire.toml").exists()

        target = tmp_path / "bonfire.toml"
        post_flow_msg = (
            f"bonfire.toml already exists at {target}. Refusing to "
            "overwrite. Remove or move the existing file and re-run."
        )

        # Mock the Front Door server constructor (used inside _run_scan)
        # so we don't bind a real socket. The server object only needs
        # the methods _run_scan touches before the run_front_door call.
        mock_server = AsyncMock()
        mock_server.start = AsyncMock(return_value=None)
        mock_server.stop = AsyncMock(return_value=None)
        mock_server.wait_for_client_connect = AsyncMock(return_value=None)
        mock_server.url = "http://localhost:0"
        mock_server.ws_url = "ws://localhost:0/ws"

        # Have run_front_door raise FileExistsError as if a concurrent
        # process created bonfire.toml between pre-flow check and write.
        # Simulate the TOCTOU side effect (file appears mid-flow) so the
        # filesystem state at exit matches reality.
        async def fake_run_front_door(*args, **kwargs):  # noqa: ARG001
            target.write_text('[bonfire]\nname = "raced"\n')
            raise FileExistsError(post_flow_msg)

        with (
            patch(
                "bonfire.cli.commands.scan.FrontDoorServer",
                return_value=mock_server,
            ),
            patch(
                "bonfire.onboard.flow.run_front_door",
                new=fake_run_front_door,
            ),
        ):
            result = runner.invoke(app, ["scan", "--no-browser"])

        # Clean non-zero exit — NOT a raw traceback.
        assert result.exit_code != 0, (
            f"_run_scan must exit non-zero on post-flow FileExistsError; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        # No Python traceback in the user-visible output.
        combined = (result.output or "") + (result.stderr or "")
        assert "Traceback" not in combined, (
            f"FileExistsError must NOT propagate as a raw traceback; got output: {combined!r}"
        )
        assert "FileExistsError" not in combined, (
            f"FileExistsError exception class must not leak to the user; got output: {combined!r}"
        )
        # The stderr message must mention the blocked file and a recovery hint.
        assert "bonfire.toml" in combined, (
            f"post-flow error must mention bonfire.toml; got: {combined!r}"
        )
        recovery_markers = ("remove", "move", "rename", "delete", "rerun", "re-run")
        combined_lower = combined.lower()
        assert any(m in combined_lower for m in recovery_markers), (
            f"post-flow error must hint at recovery; got: {combined!r}"
        )

    def test_toctou_other_exceptions_not_swallowed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only FileExistsError is caught; other exceptions still propagate.

        We must not turn ``_run_scan`` into a blanket except-Exception
        sink. A RuntimeError from the conversation engine should still
        surface (so bug reports retain their traceback signal).
        """
        monkeypatch.chdir(tmp_path)

        mock_server = AsyncMock()
        mock_server.start = AsyncMock(return_value=None)
        mock_server.stop = AsyncMock(return_value=None)
        mock_server.wait_for_client_connect = AsyncMock(return_value=None)
        mock_server.url = "http://localhost:0"
        mock_server.ws_url = "ws://localhost:0/ws"

        async def fake_run_front_door(*args, **kwargs):  # noqa: ARG001
            raise RuntimeError("conversation engine exploded")

        with (
            patch(
                "bonfire.cli.commands.scan.FrontDoorServer",
                return_value=mock_server,
            ),
            patch(
                "bonfire.onboard.flow.run_front_door",
                new=fake_run_front_door,
            ),
        ):
            result = runner.invoke(app, ["scan", "--no-browser"])

        # A non-FileExistsError must still surface as an error (non-zero
        # exit). The CliRunner captures the exception in result.exception
        # when it isn't a SystemExit / typer.Exit.
        assert result.exit_code != 0, (
            f"non-FileExistsError must still exit non-zero; got exit_code={result.exit_code}"
        )
        # The exception kind must NOT be quietly converted into a clean
        # FileExistsError-style exit. Either typer surfaces the
        # RuntimeError (CliRunner stores it on result.exception) OR the
        # output contains a traceback that names RuntimeError.
        runtime_visible = (
            isinstance(result.exception, RuntimeError)
            or "RuntimeError" in (result.output or "")
            or "conversation engine exploded" in (result.output or "")
        )
        assert runtime_visible, (
            f"RuntimeError must not be silently swallowed by the "
            f"FileExistsError handler; got exception={result.exception!r}, "
            f"output={result.output!r}"
        )
