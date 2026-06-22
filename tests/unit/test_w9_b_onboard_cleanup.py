# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""W9 Lane B — close 3 onboard-axis findings blocking release-gate-5.

Release-gate-5 ("every README example executable + every documented surface
accurate") fails on three onboard cleanup findings from Probe N+5:

H1 — ``bonfire init`` silently appends to ``.gitignore`` and creates an
     undocumented ``agents/`` directory. The success message and the
     README Quick Start both under-enumerate what init actually does.

H2 — ``bonfire --persona <X>`` is parsed but never read by any subcommand.
     The README documents it as a working per-command override; in reality
     the value is written to ``ctx.obj["persona"]`` and never consulted.

H3 — A WebSocket frame ≥ 8 KiB is hard-closed by the W8.L ``max_size``
     defense (close-code 1009, message-too-big). The CLI surfaces that
     close as ``BrowserDisconnectedError`` ("Browser closed before
     onboarding completed"), misdiagnosing a long-paste as a connection
     drop and sending the user down the wrong recovery path.

These tests pin the post-fix behavior of all three findings.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.cli.commands.init import _GITIGNORE_LINE
from bonfire.onboard.flow import (
    BrowserDisconnectedError,
    MessageTooLargeError,
    run_front_door,
)

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------
# H1 — init success message + README enumerate every created artefact
# ---------------------------------------------------------------------------


class TestInitEnumeratesCreatedArtefacts:
    """``bonfire init`` lists every artefact it creates / touches.

    Hidden mutations (``agents/`` directory; ``.gitignore`` line append)
    break the audit trail: an operator who reads only the success
    message has no way to know what changed on disk. The success stdout
    must enumerate everything; the README reconciliation test below pins
    the docs against the same list so the two cannot drift.
    """

    def test_success_stdout_enumerates_every_created_artefact(
        self,
        tmp_path: Path,
    ) -> None:
        """Every artefact init actually creates / touches is named in stdout.

        Pin the four artefacts:
          - ``bonfire.toml``
          - ``.bonfire/`` directory
          - ``agents/`` directory
          - ``.gitignore`` line append (``.bonfire/tools.local.toml``)
        """
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0, (
            f"init must succeed; got exit_code={result.exit_code}, output={result.output!r}"
        )

        # Every artefact that lands on disk must be named in stdout.
        out = result.output
        assert "bonfire.toml" in out, f"stdout must name bonfire.toml; got {out!r}"
        assert ".bonfire" in out, f"stdout must name .bonfire/ directory; got {out!r}"
        assert "agents" in out, (
            f"stdout must name the agents/ directory the prompt compiler "
            f"reads from (src/bonfire/prompt/compiler.py); got {out!r}"
        )
        assert _GITIGNORE_LINE in out, (
            f"stdout must name the .gitignore line the init appends "
            f"({_GITIGNORE_LINE!r}); got {out!r}"
        )

        # Disk truth — sanity-check every named artefact actually exists.
        assert (tmp_path / "bonfire.toml").is_file()
        assert (tmp_path / ".bonfire").is_dir()
        assert (tmp_path / "agents").is_dir()
        gitignore = tmp_path / ".gitignore"
        assert gitignore.is_file()
        assert _GITIGNORE_LINE in gitignore.read_text()

    def test_readme_quick_start_enumerates_every_created_artefact(self) -> None:
        """The README Quick Start mentions every artefact init creates.

        Parse the Quick Start ``bonfire init`` block in README.md and assert
        each of the four artefacts is referenced. Drift catcher: if a future
        change adds a new file/dir to init, the README must be updated in the
        same PR.
        """
        readme = Path(__file__).resolve().parents[2] / "README.md"
        assert readme.exists(), f"README.md not found at {readme}"

        text = readme.read_text(encoding="utf-8")

        # Find the Quick Start ``bonfire init .`` block. Bound the search
        # to the lines immediately around the init invocation so we don't
        # accidentally satisfy a match from an unrelated later section.
        marker = "bonfire init ."
        idx = text.find(marker)
        assert idx >= 0, f"README must contain the Quick Start `{marker}` example"

        # Examine 600 chars of context BEFORE the marker (where the
        # comment-block enumeration of artefacts lives).
        window = text[max(0, idx - 600) : idx + 200]

        assert "bonfire.toml" in window, (
            f"README Quick Start window must mention bonfire.toml; got: {window!r}"
        )
        assert ".bonfire" in window, (
            f"README Quick Start window must mention .bonfire/ dir; got: {window!r}"
        )
        assert "agents" in window, (
            f"README Quick Start window must mention agents/ dir (drift "
            f"catcher for the bonfire.cli.commands.init creation); got: {window!r}"
        )
        assert ".gitignore" in window, (
            f"README Quick Start window must mention .gitignore (drift "
            f"catcher for the operator-local-state append); got: {window!r}"
        )


# ---------------------------------------------------------------------------
# H2 — `bonfire --persona X` flag is gone (no per-command override surface)
# ---------------------------------------------------------------------------


class TestGlobalPersonaFlagRemoved:
    """``bonfire --persona <X>`` was dead code; the flag was removed.

    The flag wrote ``ctx.obj["persona"]`` and no subcommand ever read it.
    Documenting it as a working override was misleading. The flag is
    removed and the README is updated to direct users to ``bonfire
    persona set <name>`` (the only working configuration path).
    """

    def test_global_persona_flag_is_not_accepted(self) -> None:
        """``bonfire --persona minimal scan`` must NOT be a valid invocation."""
        result = runner.invoke(app, ["--persona", "minimal", "scan", "--no-browser"])
        # Typer/Click exits with code 2 on unknown option.
        assert result.exit_code != 0, (
            f"--persona must be rejected after removal; got "
            f"exit_code={result.exit_code}, output={result.output!r}"
        )
        # Surface either "No such option" (Click) or "unexpected extra
        # argument" depending on parse position.
        combined = (result.output or "") + (result.stderr or "")
        plain = _ANSI_RE.sub("", combined).lower()
        assert "persona" in plain and (
            "no such option" in plain or "unexpected" in plain or "error" in plain
        ), f"error output must surface the --persona rejection; got: {combined!r}"

    def test_root_help_does_not_advertise_persona_flag(self) -> None:
        """``bonfire --help`` must not advertise a global --persona flag."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        plain = _ANSI_RE.sub("", result.output)
        assert "--persona" not in plain, (
            f"`bonfire --help` must not list a global --persona flag after removal; got: {plain!r}"
        )

    def test_readme_does_not_document_global_persona_override(self) -> None:
        """The README must not show a ``bonfire --persona <X> <cmd>`` example.

        Drift catcher: the dead flag's documentation was the load-bearing
        bug; removing the flag without removing the example would leave
        users in the same broken state.
        """
        readme = Path(__file__).resolve().parents[2] / "README.md"
        assert readme.exists()

        text = readme.read_text(encoding="utf-8")
        # The bad pattern is ``bonfire --persona <something> <subcommand>``.
        # Use a regex with the global-flag word boundary so we don't
        # accidentally match ``bonfire persona set`` (legitimate, kept).
        bad_pattern = re.compile(r"bonfire\s+--persona\b")
        match = bad_pattern.search(text)
        assert match is None, (
            f"README must NOT document `bonfire --persona <X> <cmd>` after the "
            f"flag was removed; matched at offset {match.start() if match else -1}: "
            f"{match.group() if match else ''!r}"
        )


# ---------------------------------------------------------------------------
# H3 — oversize WS frame surfaces as MessageTooLargeError, not browser-drop
# ---------------------------------------------------------------------------


def _build_mock_server_with_oversize_flag(
    *,
    oversize: bool,
) -> MagicMock:
    """Mock FrontDoorServer where ``shutdown_event`` is immediately set.

    The mock mirrors the shape ``_run_scan`` reaches into:
    ``shutdown_event`` (already-set asyncio.Event), ``start``/``stop``
    awaitables, ``wait_for_client_connect`` awaitable. The
    ``oversize_disconnect`` property reflects the requested test scenario.
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
    server.oversize_disconnect = oversize
    return server


class TestRunFrontDoorRaisesMessageTooLargeOnOversizeDisconnect:
    """``run_front_door`` discriminates oversize close from generic disconnect.

    When the WS server flips ``oversize_disconnect`` (a client sent a frame
    larger than the 8 KiB ``max_size`` cap, close code 1009), the flow must
    raise ``MessageTooLargeError`` — not the generic
    ``BrowserDisconnectedError`` — so the CLI can offer the right
    remediation ("shorten your answer", not "your browser dropped").
    """

    async def test_oversize_disconnect_raises_message_too_large(
        self,
        tmp_path: Path,
    ) -> None:
        """Server.oversize_disconnect=True → MessageTooLargeError, not parent."""
        server = MagicMock()
        # The flow's Act I emits scan events through ``server.broadcast``;
        # make it a no-op.
        server.broadcast = AsyncMock(return_value=None)
        # The flow uses ``server.shutdown_event`` as the disconnect race
        # signal — set it so the shutdown branch wins the asyncio.wait race.
        shutdown_event = asyncio.Event()
        shutdown_event.set()
        server.shutdown_event = shutdown_event
        # Tag the disconnect as oversize. This is what ``_ws_handler``
        # would have flipped in real life on close-code 1009.
        server.oversize_disconnect = True
        # Conversation never sets its own done flag; the on_message
        # property exists for the run_front_door installer.
        server.on_message = None

        with (
            patch(
                "bonfire.onboard.flow.run_scan",
                new=AsyncMock(return_value=None),
            ),
            patch("bonfire.onboard.flow.ConversationEngine") as mock_engine_cls,
        ):
            engine = MagicMock()
            engine.start = AsyncMock(return_value=None)
            engine.is_complete = False
            mock_engine_cls.return_value = engine

            with pytest.raises(MessageTooLargeError) as excinfo:
                await run_front_door(server, tmp_path)

        msg = str(excinfo.value).lower()
        # The user-visible message must name the cap and the recovery path.
        assert "too long" in msg or "max" in msg, (
            f"MessageTooLargeError must surface an actionable 'too long'/'max' "
            f"message, not the generic 'browser closed' text; got: {excinfo.value!r}"
        )
        assert "8" in str(excinfo.value), (
            f"MessageTooLargeError must name the 8 KiB cap so the user knows "
            f"what they exceeded; got: {excinfo.value!r}"
        )

    def test_message_too_large_subclasses_browser_disconnected(self) -> None:
        """``MessageTooLargeError`` is a ``BrowserDisconnectedError`` subclass.

        Existing CLI/test handlers that catch the parent must keep working;
        the discriminating handler relies on Python MRO catching the
        subclass first.
        """
        assert issubclass(MessageTooLargeError, BrowserDisconnectedError)


class TestScanCliMapsOversizeToActionableMessage:
    """``bonfire scan`` surfaces the oversize remediation, not "browser closed".

    This is the user-visible bug-fix: the misleading
    ``BrowserDisconnectedError`` message ("Browser closed before
    onboarding completed") sent users back through ``bonfire scan`` only
    to hit the same wall on the same too-long answer. Post-fix the
    stderr must explicitly say "too long" / "max" so the user knows the
    recovery path is "shorten the answer", not "re-launch the browser".
    """

    def test_message_too_large_emits_too_long_in_stderr(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)

        async def fake_run_front_door(*_args: Any, **_kwargs: Any) -> Path:
            raise MessageTooLargeError(
                "Your answer is too long (max 8 KiB per message). "
                "Re-run `bonfire scan` and try a shorter response."
            )

        mock_server = _build_mock_server_with_oversize_flag(oversize=True)
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

        assert result.exit_code == 1, (
            f"MessageTooLargeError must exit 1; got "
            f"exit_code={result.exit_code}, output={result.output!r}, "
            f"stderr={result.stderr!r}"
        )
        combined = (result.output or "") + (result.stderr or "")
        # No raw traceback.
        assert "Traceback" not in combined, (
            f"MessageTooLargeError must NOT propagate as a raw traceback; got: {combined!r}"
        )
        # Crucially: the surface must NOT use the generic browser-closed
        # text — that's the misleading-diagnosis bug.
        assert "browser closed" not in combined.lower(), (
            f"oversize must NOT surface as 'Browser closed' (the H3 "
            f"misclassification we're fixing); got stderr={result.stderr!r}"
        )
        # The actionable phrasing must be present.
        stderr_lower = (result.stderr or "").lower()
        assert "too long" in stderr_lower or "max" in stderr_lower, (
            f"stderr must surface an actionable 'too long'/'max' message; "
            f"got stderr={result.stderr!r}"
        )

    def test_generic_browser_disconnect_still_handled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A non-oversize disconnect still surfaces the legacy "Browser closed".

        Regression guard: the new ``MessageTooLargeError`` branch must not
        swallow plain ``BrowserDisconnectedError`` cases (the user really
        did close the browser tab).
        """
        monkeypatch.chdir(tmp_path)

        async def fake_run_front_door(*_args: Any, **_kwargs: Any) -> Path:
            raise BrowserDisconnectedError(
                "Browser closed before the onboarding conversation completed."
            )

        mock_server = _build_mock_server_with_oversize_flag(oversize=False)
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

        assert result.exit_code == 1
        stderr_lower = (result.stderr or "").lower()
        assert "browser closed" in stderr_lower, (
            f"plain BrowserDisconnectedError must still surface as "
            f"'Browser closed'; got stderr={result.stderr!r}"
        )


class TestWsServerFlipsOversizeFlagOn1009:
    """End-to-end on the server side: an >8 KiB frame flips ``oversize_disconnect``.

    Sanity test against the live WS server. Send an oversize frame, wait for
    the close, then assert ``server.oversize_disconnect`` is True. Pairs
    with ``test_onboard_server_ws_limits.py`` (which pins the close-code
    behaviour) — this test pins the new server-side flag flip.
    """

    async def test_oversize_frame_flips_oversize_disconnect_flag(self) -> None:
        import websockets

        from bonfire.onboard.server import _WS_MAX_FRAME_BYTES, FrontDoorServer

        server = FrontDoorServer()
        await server.start()
        try:
            assert server.oversize_disconnect is False, (
                "freshly-started server must not report oversize_disconnect"
            )

            oversized = json.dumps({"type": "user_message", "text": "x" * (16 * 1024)})
            assert len(oversized.encode("utf-8")) > _WS_MAX_FRAME_BYTES

            with pytest.raises(Exception):  # noqa: BLE001
                async with websockets.connect(server.ws_url) as ws:
                    await ws.send(oversized)
                    # If send didn't raise, recv definitely will once the
                    # server's close frame arrives.
                    await ws.recv()

            # Give the server-side handler a brief moment to observe the
            # ConnectionClosed exception, flip the flag, and exit the
            # ``finally`` block.
            for _ in range(50):
                if server.oversize_disconnect:
                    break
                await asyncio.sleep(0.02)

            assert server.oversize_disconnect is True, (
                "server.oversize_disconnect must flip True after an "
                "oversize close (WS code 1009); without this the flow "
                "layer cannot discriminate the oversize case from a "
                "generic browser disconnect."
            )
        finally:
            await server.stop()
