# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""BON-1757 — narrowed-except contract for the git_state timeout drain.

After ``asyncio.wait_for(proc.communicate())`` times out, ``_run_cmd``
kills the subprocess and drains it with a second ``await
proc.communicate()`` inside a best-effort try/except. That except was a
broad ``except Exception  # noqa: BLE001,...``; BON-1757 narrows it to
``(OSError, asyncio.TimeoutError)`` while KEEPING the ``S110``
suppression (the body is still ``pass`` — a try-except-pass is the
intended best-effort shape here).

These tests pin that the drain still swallows the in-set failure
(``OSError`` from the second ``communicate``) and that ``_run_cmd``
returns the timeout sentinel ``(_RC_TIMEOUT, "")`` regardless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class _DrainBoomProc:
    """Subprocess double whose drain ``communicate`` raises ``OSError``."""

    returncode = None

    def __init__(self) -> None:
        self._calls = 0

    async def communicate(self):
        self._calls += 1
        # Second call is the post-kill drain — raise the in-set error.
        raise OSError("drain pipe broke")

    def kill(self) -> None:
        pass


async def test_timeout_drain_swallows_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``OSError`` from the post-timeout drain ``communicate`` is swallowed.

    Patches ``wait_for`` to raise ``TimeoutError`` (driving execution into
    the kill+drain branch) and uses a proc whose drain ``communicate``
    raises ``OSError``. ``_run_cmd`` must NOT propagate it — it returns the
    timeout sentinel ``(_RC_TIMEOUT, "")``.
    """
    from bonfire.onboard.scanners import git_state as gs

    async def _fake_exec(*args, **kwargs):
        return _DrainBoomProc()

    async def _always_timeout(coro, timeout):
        try:
            coro.close()
        except AttributeError:
            pass
        raise TimeoutError

    monkeypatch.setattr(gs.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(gs.asyncio, "wait_for", _always_timeout)

    rc, out = await gs._run_cmd(["git", "status"], cwd=tmp_path)

    assert rc == gs._RC_TIMEOUT
    assert out == ""


async def test_timeout_drain_swallows_timeouterror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``asyncio.TimeoutError`` from the drain is also in the narrowed set."""
    from bonfire.onboard.scanners import git_state as gs

    class _DrainTimeoutProc:
        returncode = None

        async def communicate(self):
            raise TimeoutError

        def kill(self) -> None:
            pass

    async def _fake_exec(*args, **kwargs):
        return _DrainTimeoutProc()

    async def _always_timeout(coro, timeout):
        try:
            coro.close()
        except AttributeError:
            pass
        raise TimeoutError

    monkeypatch.setattr(gs.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(gs.asyncio, "wait_for", _always_timeout)

    rc, out = await gs._run_cmd(["git", "status"], cwd=tmp_path)

    assert rc == gs._RC_TIMEOUT
    assert out == ""
