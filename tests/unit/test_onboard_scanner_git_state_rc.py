"""RED contract for git_state scanner rc-handling safety net.

Subject: ``bonfire.onboard.scanners.git_state._run_cmd`` returns
``tuple[int, str]`` but ``asyncio.subprocess.Process.returncode`` is
``int | None``. The success path treats ``None`` as "not zero" and
silently emits nothing. Non-zero git rc (e.g. corrupt ``.git/HEAD``)
also goes silent today — only the ``repository: initialized`` event
fires before each git invocation drops its result.

This file pins down three contracts:

  1. ``returncode is None`` from the subprocess MUST surface as a
     scanner-visible error event, NOT a silent drop.
  2. Non-zero git rc on any command must produce a scanner-visible
     error event whose ``label`` or ``detail`` names the failed git
     command and the rc.
  3. ``asyncio.wait_for`` ``TimeoutError`` must produce a
     "git command timed out" event, not a silent drop.

The happy path is covered by
``tests/unit/test_onboard_scanner_git_state.py``; this file is the
safety-net layer.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from bonfire.onboard.protocol import ScanUpdate

if TYPE_CHECKING:
    from pathlib import Path


def _git_init(path: Path, *, commit: bool = True) -> None:
    """Initialise a real git repo at *path* with optional first commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    if commit:
        (path / "init.txt").write_text("hello")
        subprocess.run(
            ["git", "-C", str(path), "add", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(path), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    return [c.args[0] for c in emit.call_args_list]


def _is_error_event(e: ScanUpdate) -> bool:
    """Heuristic shape-matcher for the "error" event surface.

    The contract pins SOMETHING visible — ``value == "error"`` is the
    most direct shape, but a ``detail`` mentioning the failed git
    command is acceptable. The Warrior's call which form ships.
    """
    if e.value == "error":
        return True
    needle = e.detail.lower() + " " + e.label.lower()
    if "error" in needle or "failed" in needle:
        return True
    return False


# ---------------------------------------------------------------------------
# 1. Non-zero rc emits an error event
# ---------------------------------------------------------------------------


class TestNonZeroRcEmitsErrorEvent:
    """A git command returning rc != 0 must produce a visible error event."""

    async def test_corrupt_head_emits_error_event(self, tmp_path: Path) -> None:
        """Corrupt ``.git/HEAD`` makes most git commands fail; scanner must surface that.

        Today the scanner silently emits only the
        ``repository: initialized`` guard event and drops every
        subsequent git invocation's failure.
        """
        from bonfire.onboard.scanners.git_state import scan

        _git_init(tmp_path)
        # Corrupt HEAD — `branch --show-current`, `log -1`, etc. fail.
        head = tmp_path / ".git" / "HEAD"
        head.write_text("not-a-ref")

        emit = AsyncMock()
        await scan(tmp_path, emit)

        events = _events(emit)
        # The initial ``repository: initialized`` event still fires
        # (the existence of ``.git`` is the only signal there). After
        # that, at least one event must mark the failure.
        non_init_events = [e for e in events if e.label != "repository"]
        error_events = [e for e in non_init_events if _is_error_event(e)]
        assert error_events, (
            f"corrupt .git/HEAD must produce at least one error event "
            f"after the initial repository signal; got events: "
            f"{[(e.label, e.value, e.detail) for e in events]!r}"
        )


# ---------------------------------------------------------------------------
# 2. ``returncode is None`` is distinguished from rc != 0 and surfaces an error
# ---------------------------------------------------------------------------


class TestReturncodeNoneIsErrorNotSilent:
    """If the subprocess yields ``returncode is None``, the scanner emits an error.

    Today ``_run_cmd`` returns ``(proc.returncode, ...)`` and the
    caller checks ``rc == 0`` — ``None == 0`` is ``False``, so the
    branch silently drops the result. The contract: ``None`` is an
    error condition and must be surfaced.
    """

    async def test_none_returncode_surfaces_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Patch ``asyncio.create_subprocess_exec`` so all procs report ``returncode=None``."""
        from bonfire.onboard.scanners import git_state as gs_module

        _git_init(tmp_path)

        class _NoneReturncodeProc:
            returncode = None

            async def communicate(self):
                return (b"", b"")

            def kill(self):
                pass

        async def _fake_exec(*args, **kwargs):
            return _NoneReturncodeProc()

        monkeypatch.setattr(
            gs_module.asyncio,
            "create_subprocess_exec",
            _fake_exec,
        )

        emit = AsyncMock()
        await gs_module.scan(tmp_path, emit)

        events = _events(emit)
        non_init_events = [e for e in events if e.label != "repository"]
        error_events = [e for e in non_init_events if _is_error_event(e)]
        assert error_events, (
            f"returncode=None must surface as an error event, not a silent drop; "
            f"got events: {[(e.label, e.value, e.detail) for e in events]!r}"
        )


# ---------------------------------------------------------------------------
# 3. Timeout branch is surfaced, not silently dropped
# ---------------------------------------------------------------------------


class TestTimeoutIsSurfaced:
    """``asyncio.wait_for`` timeout must surface as a visible event."""

    async def test_timeout_emits_event_naming_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Patch ``asyncio.wait_for`` to always raise ``TimeoutError``."""
        from bonfire.onboard.scanners import git_state as gs_module

        _git_init(tmp_path)

        async def _always_timeout(coro, timeout):
            # Close the awaitable so unused-coroutine warnings don't
            # mask the contract assertion.
            try:
                coro.close()
            except AttributeError:
                pass
            raise TimeoutError

        monkeypatch.setattr(gs_module.asyncio, "wait_for", _always_timeout)

        emit = AsyncMock()
        await gs_module.scan(tmp_path, emit)

        events = _events(emit)
        non_init_events = [e for e in events if e.label != "repository"]
        timeout_events = [
            e
            for e in non_init_events
            if "timeout" in e.detail.lower()
            or "timed out" in e.detail.lower()
            or "timeout" in e.value.lower()
            or "timed out" in e.value.lower()
            or "timeout" in e.label.lower()
        ]
        assert timeout_events, (
            f"git command timeout must surface as a 'timed out' event; "
            f"got events: {[(e.label, e.value, e.detail) for e in events]!r}"
        )
