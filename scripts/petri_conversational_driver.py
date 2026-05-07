# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Petri-box headless driver for ``bonfire scan --no-browser``.

A minimal Python WebSocket client that lets us drive the Front Door
onboarding scan end-to-end inside the dogfood petri-box VM without a
browser. Spawns ``python -m bonfire scan --no-browser``, parses the
listening URL the CLI prints to stdout, opens the WebSocket as a
client, logs every server-emitted event, replies to each
``falcor_message`` of subtype ``"question"`` with a canned answer, and
exits with rc=0 once ``config_generated`` arrives.

The driver does NOT integrate an LLM — the canned answers are a small
dict literal at the top of the file. Replacing them with a model call
is out of scope for the v0 skeleton (BON-870); a follow-up may swap
the answer source.

Usage::

    cd ~/work/bonfire-public && source .venv/bin/activate
    python scripts/petri_conversational_driver.py [--cwd PATH]

The driver runs the CLI in the directory it is invoked from unless
``--cwd`` is given. A ``bonfire.toml`` will be written to that
directory by the scan flow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

__all__ = [
    "DEFAULT_ANSWERS",
    "ConversationalDriver",
    "main",
    "parse_ws_url",
    "run_driver",
]


# ---------------------------------------------------------------------------
# Canned answers
# ---------------------------------------------------------------------------

# Keyed by 1-based question number (Q1, Q2, Q3 from
# ``src/bonfire/onboard/conversation.py``). Plain English; no profile-
# steering tricks. Worded long enough to pass the >=3-word "brief
# reflection" branch in conversation._SHORT_THRESHOLD so the engine
# walks the full analyzer for each answer.
DEFAULT_ANSWERS: dict[int, str] = {
    1: (
        "I shipped a Python pipeline that runs deterministic agents with "
        "strict tool gates and budgets, and watching it stay green was the "
        "most satisfying thing I built this year."
    ),
    2: (
        "I sketch a blueprint of the moving parts, then iterate on the "
        "smallest end-to-end slice until it stays green."
    ),
    3: (
        "They miss context across sessions and ignore my preferences, so "
        "I keep re-explaining the same constraints every time."
    ),
}


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_HTTP_URL_RE = re.compile(r"http://(?P<host>[^\s:/]+):(?P<port>\d+)")


def parse_ws_url(line: str) -> str | None:
    """Extract the WS URL from a ``bonfire scan`` stdout line.

    The CLI prints ``Front Door listening at http://<host>:<port>`` once
    the server is bound (``src/bonfire/cli/commands/scan.py:27``). The
    server itself constructs the WebSocket URL as
    ``ws://<host>:<port>/ws`` (``src/bonfire/onboard/server.py:124-127``).
    Returns ``None`` if no URL is found in the line.
    """
    match = _HTTP_URL_RE.search(line)
    if match is None:
        return None
    return f"ws://{match['host']}:{match['port']}/ws"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


@dataclass
class ConversationalDriver:
    """Stateful event handler for the Front Door WebSocket protocol.

    Wraps the dispatch logic so it can be unit-tested without spinning
    up a real WebSocket. ``handle_event`` accepts either a JSON string
    (as it would arrive over the wire) or an already-parsed dict, and
    returns a dict to send back to the server, or ``None`` if the event
    requires no reply.
    """

    answers: dict[int, str] | None = None
    logger: logging.Logger | None = None
    scan_updates_seen: list[dict[str, Any]] = field(default_factory=list)
    _question_index: int = 0
    _done: bool = False

    def __post_init__(self) -> None:
        if self.answers is None:
            self.answers = dict(DEFAULT_ANSWERS)
        if self.logger is None:
            self.logger = logging.getLogger("petri_conversational_driver")

    @property
    def is_done(self) -> bool:
        """True once a ``config_generated`` event has been observed."""
        return self._done

    async def handle_event(self, event: str | dict[str, Any]) -> dict[str, Any] | None:
        """Process one server event. Return a reply dict or ``None``.

        The driver is purely event-driven: ``scan_complete`` is NOT a
        barrier. Per ``orchestrator.py:104-110`` each panel emits its
        own ``ScanComplete`` the instant its scan finishes, while other
        panels are still emitting ``scan_update``s. The only event that
        terminates the driver is ``config_generated``.
        """
        assert self.logger is not None  # narrow Optional for type-checker
        data = self._coerce(event)
        if data is None:
            return None

        type_ = data.get("type")
        self.logger.info("event type=%s payload=%s", type_, data)

        if type_ == "scan_start":
            return None
        if type_ == "scan_update":
            self.scan_updates_seen.append(dict(data))
            return None
        if type_ == "scan_complete":
            return None
        if type_ == "all_scans_complete":
            return None
        if type_ == "conversation_start":
            return None
        if type_ == "falcor_message":
            return self._handle_falcor(data)
        if type_ == "config_generated":
            self._done = True
            return None

        self.logger.warning("Unknown event type %r; ignoring", type_)
        return None

    def _coerce(self, event: str | dict[str, Any]) -> dict[str, Any] | None:
        assert self.logger is not None
        if isinstance(event, dict):
            return event
        try:
            parsed = json.loads(event)
        except json.JSONDecodeError as exc:
            self.logger.warning("Invalid JSON frame, ignoring: %s", exc)
            return None
        if not isinstance(parsed, dict):
            self.logger.warning("Non-object JSON frame, ignoring: %r", parsed)
            return None
        return parsed

    def _handle_falcor(self, data: dict[str, Any]) -> dict[str, Any] | None:
        assert self.logger is not None
        subtype = data.get("subtype")
        text = data.get("text", "")
        if subtype == "question":
            self._question_index += 1
            answer = self._answer_for(self._question_index)
            self.logger.info(
                "Q%d -> answering with canned response (%d chars)",
                self._question_index,
                len(answer),
            )
            return {"type": "user_message", "text": answer}
        if subtype in ("narration", "reflection"):
            self.logger.info("falcor %s: %s", subtype, text)
            return None
        self.logger.warning("Unknown falcor subtype %r; ignoring", subtype)
        return None

    def _answer_for(self, q_number: int) -> str:
        assert self.answers is not None
        if q_number in self.answers:
            return self.answers[q_number]
        # Fallback: reuse the last canned answer rather than crash if the
        # server somehow asks a 4th question.
        last_key = max(self.answers.keys()) if self.answers else 0
        return self.answers.get(last_key, "Acknowledged.")


# ---------------------------------------------------------------------------
# WebSocket loop
# ---------------------------------------------------------------------------


async def run_driver(
    ws_url: str,
    drv: ConversationalDriver,
    logger: logging.Logger,
) -> int:
    """Open the WebSocket, dispatch events, exit when ``is_done``.

    Returns 0 on a clean ``config_generated``, 1 if the connection
    closes before the driver has finished.
    """
    logger.info("Connecting to %s", ws_url)
    async with websockets.connect(ws_url) as ws:
        try:
            async for raw in ws:
                if not isinstance(raw, str):
                    logger.warning("Non-text frame ignored")
                    continue
                reply = await drv.handle_event(raw)
                if reply is not None:
                    await ws.send(json.dumps(reply))
                if drv.is_done:
                    logger.info("config_generated received; exiting")
                    return 0
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket closed")
    return 0 if drv.is_done else 1


# ---------------------------------------------------------------------------
# Subprocess entry point
# ---------------------------------------------------------------------------


async def _read_until_url(stream: asyncio.StreamReader, logger: logging.Logger) -> str | None:
    """Read lines from ``stream`` until a ws URL is found. Logs each line."""
    while True:
        line_bytes = await stream.readline()
        if not line_bytes:
            return None
        line = line_bytes.decode("utf-8", errors="replace").rstrip()
        logger.info("[scan stdout] %s", line)
        url = parse_ws_url(line)
        if url is not None:
            return url


async def _drain(stream: asyncio.StreamReader, logger: logging.Logger, tag: str) -> None:
    """Forward every remaining line from ``stream`` to the logger."""
    while True:
        line_bytes = await stream.readline()
        if not line_bytes:
            return
        logger.info("[%s] %s", tag, line_bytes.decode("utf-8", errors="replace").rstrip())


def _build_scan_command(port: int) -> list[str]:
    """Build the argv that runs ``bonfire scan --no-browser`` from the
    active venv. Prefers the ``bonfire`` console script that sits next
    to ``sys.executable`` (so it is guaranteed to import the source
    tree's ``bonfire`` package, not a globally-installed alpha).

    Falls back to ``python -c`` invoking ``bonfire.cli.app`` directly if
    the console script is not present, since the package itself has no
    ``__main__`` module.
    """
    bonfire_script = Path(sys.executable).resolve().parent / "bonfire"
    if bonfire_script.exists():
        return [str(bonfire_script), "scan", "--no-browser", "--port", str(port)]
    found = shutil.which("bonfire")
    if found:
        return [found, "scan", "--no-browser", "--port", str(port)]
    return [
        sys.executable,
        "-c",
        "import sys; from bonfire.cli import app; sys.exit(app())",
        "scan",
        "--no-browser",
        "--port",
        str(port),
    ]


async def main(argv: list[str] | None = None) -> int:
    """CLI entry: spawn ``bonfire scan``, drive it, return rc."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory for the scan subprocess. Defaults to current dir.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to bind (0 = random).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("petri_conversational_driver")

    cmd = _build_scan_command(args.port)
    logger.info("Spawning: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=args.cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    # Forward the subprocess stderr to our logger in the background.
    stderr_task = asyncio.create_task(_drain(proc.stderr, logger, "scan stderr"))

    try:
        ws_url = await _read_until_url(proc.stdout, logger)
        if ws_url is None:
            logger.error("Scan exited before printing the listening URL")
            await proc.wait()
            return proc.returncode if proc.returncode is not None else 1

        # Continue forwarding stdout in the background.
        stdout_task = asyncio.create_task(_drain(proc.stdout, logger, "scan stdout"))

        drv = ConversationalDriver(logger=logger)
        rc = await run_driver(ws_url, drv, logger)

        # Allow the scan subprocess to settle (it shuts down on WS close).
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            logger.warning("Scan subprocess did not exit; terminating")
            proc.terminate()
            await proc.wait()

        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        scan_rc = proc.returncode if proc.returncode is not None else 0
        logger.info("driver rc=%d, scan rc=%d", rc, scan_rc)
        return rc or scan_rc
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
        stderr_task.cancel()


def _entrypoint() -> int:
    return asyncio.run(main())


if __name__ == "__main__":
    sys.exit(_entrypoint())
