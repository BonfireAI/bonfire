"""CLI exception-handling for the onboarding flow's named errors.

When ``run_front_door`` raises ``BrowserDisconnectedError`` or
``ConversationTimeoutError`` mid-flow, the ``bonfire scan`` CLI must
catch them at the call site and surface a tailored remediation message
to the user — never a raw Python traceback. This file pins those
catches and the threading of the ``--conversation-timeout`` Typer option
through the lazy router (``bonfire.cli.app``) into
``bonfire.cli.commands.scan._run_scan`` and on to ``run_front_door``.

These tests are siblings of ``test_scan_cli.py`` (which is Knight-contract
locked) — kept separate so the contract floor stays untouched while the
follow-on exception + flag surface gets explicit coverage.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.onboard.flow import (
    BrowserDisconnectedError,
    ConversationTimeoutError,
)

runner = CliRunner()

# Strip ANSI style codes so substring assertions on Typer/Rich help
# output don't split on style boundaries when CI emits colored output.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _build_mock_server() -> MagicMock:
    """FrontDoorServer mock with the minimum surface _run_scan touches.

    ``shutdown_event`` is a real ``asyncio.Event`` pre-set so the post-flow
    ``await server.shutdown_event.wait()`` returns immediately instead of
    blocking the test.
    """
    server = MagicMock()
    server.start = AsyncMock(return_value=None)
    server.stop = AsyncMock(return_value=None)
    server.wait_for_client_connect = AsyncMock(return_value=None)
    server.url = "http://127.0.0.1:0"
    server.ws_url = "ws://127.0.0.1:0/ws"
    shutdown_event = asyncio.Event()
    shutdown_event.set()
    server.shutdown_event = shutdown_event
    return server


# ---------------------------------------------------------------------------
# BLOCKER B1 — CLI catches the new flow exceptions cleanly
# ---------------------------------------------------------------------------


class TestScanCatchesBrowserDisconnectedError:
    """``bonfire scan`` must convert ``BrowserDisconnectedError`` into a
    clean non-zero exit with an actionable stderr message — never a raw
    Python traceback. The flow's docstring promises the CLI offers a
    tailored remediation message; this test pins that promise.
    """

    def test_browser_disconnected_exits_one_with_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "bonfire.toml").exists()

        async def fake_run_front_door(*args, **kwargs):  # noqa: ARG001
            raise BrowserDisconnectedError(
                "Browser closed before the onboarding conversation completed."
            )

        with (
            patch(
                "bonfire.cli.commands.scan.FrontDoorServer",
                return_value=_build_mock_server(),
            ),
            patch(
                "bonfire.onboard.flow.run_front_door",
                new=fake_run_front_door,
            ),
        ):
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code == 1, (
            f"BrowserDisconnectedError must produce exit_code=1; "
            f"got {result.exit_code}, output={result.output!r}, "
            f"stderr={result.stderr!r}"
        )
        combined = (result.output or "") + (result.stderr or "")
        assert "Traceback" not in combined, (
            f"BrowserDisconnectedError must NOT propagate as a raw traceback; got: {combined!r}"
        )
        assert "BrowserDisconnectedError" not in combined, (
            f"Exception class name must not leak to the user; got: {combined!r}"
        )
        stderr_lower = (result.stderr or "").lower()
        assert "browser closed" in stderr_lower, (
            f"stderr must mention `Browser closed` so the user knows what "
            f"happened; got stderr={result.stderr!r}"
        )
        assert "bonfire scan" in stderr_lower or "re-run" in stderr_lower, (
            f"stderr must hint at retrying via `bonfire scan`; got stderr={result.stderr!r}"
        )


class TestScanCatchesConversationTimeoutError:
    """``bonfire scan`` must convert ``ConversationTimeoutError`` into a
    clean non-zero exit with a message that points at the
    ``--conversation-timeout`` knob — never a raw Python traceback.
    """

    def test_conversation_timeout_exits_one_with_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "bonfire.toml").exists()

        async def fake_run_front_door(*args, **kwargs):  # noqa: ARG001
            raise ConversationTimeoutError(
                "Onboarding conversation did not complete within 300.0 seconds."
            )

        with (
            patch(
                "bonfire.cli.commands.scan.FrontDoorServer",
                return_value=_build_mock_server(),
            ),
            patch(
                "bonfire.onboard.flow.run_front_door",
                new=fake_run_front_door,
            ),
        ):
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code == 1, (
            f"ConversationTimeoutError must produce exit_code=1; "
            f"got {result.exit_code}, output={result.output!r}, "
            f"stderr={result.stderr!r}"
        )
        combined = (result.output or "") + (result.stderr or "")
        assert "Traceback" not in combined, (
            f"ConversationTimeoutError must NOT propagate as a raw traceback; got: {combined!r}"
        )
        assert "ConversationTimeoutError" not in combined, (
            f"Exception class name must not leak to the user; got: {combined!r}"
        )
        stderr_lower = (result.stderr or "").lower()
        assert "timed out" in stderr_lower or "timeout" in stderr_lower, (
            f"stderr must mention the timeout so the user knows what "
            f"happened; got stderr={result.stderr!r}"
        )
        assert "--conversation-timeout" in (result.stderr or ""), (
            f"stderr must mention the --conversation-timeout flag so the "
            f"user can extend the window; got stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# MEDIUM M1 — --conversation-timeout exists and threads through
# ---------------------------------------------------------------------------


class TestConversationTimeoutOption:
    """``--conversation-timeout`` is exposed on ``bonfire scan`` and the
    value threads from the Typer router into ``run_front_door`` verbatim.
    """

    def test_help_lists_conversation_timeout_flag(self) -> None:
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        plain = _ANSI_RE.sub("", result.output)
        assert "--conversation-timeout" in plain, (
            f"`bonfire scan --help` must list --conversation-timeout; got: {plain!r}"
        )

    def test_explicit_timeout_threads_to_run_front_door(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--conversation-timeout 60`` reaches ``run_front_door`` as 60.0."""
        monkeypatch.chdir(tmp_path)

        captured_kwargs: dict[str, object] = {}

        async def fake_run_front_door(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return tmp_path / "bonfire.toml"

        with (
            patch(
                "bonfire.cli.commands.scan.FrontDoorServer",
                return_value=_build_mock_server(),
            ),
            patch(
                "bonfire.onboard.flow.run_front_door",
                new=fake_run_front_door,
            ),
        ):
            # Stub shutdown_event.wait() so the CLI returns after the
            # mocked run_front_door rather than blocking forever.
            result = runner.invoke(
                app,
                ["scan", "--conversation-timeout", "60", "--no-browser"],
            )

        assert result.exit_code == 0, (
            f"explicit --conversation-timeout must run cleanly; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        assert "conversation_timeout" in captured_kwargs, (
            f"run_front_door must receive conversation_timeout kwarg; "
            f"got captured kwargs={captured_kwargs!r}"
        )
        assert captured_kwargs["conversation_timeout"] == 60.0, (
            f"--conversation-timeout 60 must surface as 60.0 at run_front_door; "
            f"got conversation_timeout={captured_kwargs['conversation_timeout']!r}"
        )

    def test_zero_timeout_disables_the_wait(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--conversation-timeout 0`` reaches ``run_front_door`` as None."""
        monkeypatch.chdir(tmp_path)

        captured_kwargs: dict[str, object] = {}

        async def fake_run_front_door(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return tmp_path / "bonfire.toml"

        with (
            patch(
                "bonfire.cli.commands.scan.FrontDoorServer",
                return_value=_build_mock_server(),
            ),
            patch(
                "bonfire.onboard.flow.run_front_door",
                new=fake_run_front_door,
            ),
        ):
            result = runner.invoke(
                app,
                ["scan", "--conversation-timeout", "0", "--no-browser"],
            )

        assert result.exit_code == 0, (
            f"--conversation-timeout 0 must run cleanly; got "
            f"exit_code={result.exit_code}, output={result.output!r}"
        )
        assert captured_kwargs.get("conversation_timeout") is None, (
            f"--conversation-timeout 0 must surface as None at run_front_door "
            f"(wait indefinitely); got "
            f"conversation_timeout={captured_kwargs.get('conversation_timeout')!r}"
        )
