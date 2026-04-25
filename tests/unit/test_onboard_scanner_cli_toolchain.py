"""RED tests for bonfire.onboard.scanners.cli_toolchain — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 14 tests per Sage §D6 Row 4. Verbatim v1 port. No innovations (conservative lens).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_events(emit: AsyncMock) -> list[ScanUpdate]:
    """Extract all ScanUpdate objects passed to the emit callback."""
    return [call.args[0] for call in emit.call_args_list]


def _find_event(events: list[ScanUpdate], label: str) -> ScanUpdate | None:
    """Find a single event by label."""
    matches = [e for e in events if e.label == label]
    return matches[0] if matches else None


def _mock_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> AsyncMock:
    """Create a mock subprocess with given outputs."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_detects_installed_tool(tmp_path: Path):
    """A tool found by shutil.which should be emitted with its version."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/git" if t == "git" else None

        mock_proc = _mock_proc(stdout=b"git version 2.43.0\n")
        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            count = await scan(tmp_path, emit)

    assert count >= 1
    events = _collect_events(emit)
    git_ev = _find_event(events, "git")
    assert git_ev is not None
    assert git_ev.value == "2.43.0"
    assert git_ev.panel == "cli_toolchain"


async def test_skips_tool_not_found(tmp_path: Path):
    """Tools not found by shutil.which should produce no events."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.return_value = None  # nothing installed

        from bonfire.onboard.scanners.cli_toolchain import scan

        count = await scan(tmp_path, emit)

    assert count == 0
    emit.assert_not_called()


async def test_extracts_version_from_stdout(tmp_path: Path):
    """Version string should be extracted from the first matching X.Y.Z."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/python3" if t == "python3" else None

        mock_proc = _mock_proc(stdout=b"Python 3.12.3\n")
        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    py_ev = _find_event(events, "python3")
    assert py_ev is not None
    assert py_ev.value == "3.12.3"


async def test_extracts_version_from_stderr(tmp_path: Path):
    """Some tools (e.g. java) output version to stderr."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/java" if t == "java" else None

        mock_proc = _mock_proc(stdout=b"", stderr=b'openjdk version "21.0.2" 2024-01-16\n')
        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    java_ev = _find_event(events, "java")
    assert java_ev is not None
    assert java_ev.value == "21.0.2"


async def test_handles_version_timeout_gracefully(tmp_path: Path):
    """If version detection times out, tool should still be emitted as 'installed'."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/docker" if t == "docker" else None

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            count = await scan(tmp_path, emit)

    assert count >= 1
    events = _collect_events(emit)
    docker_ev = _find_event(events, "docker")
    assert docker_ev is not None
    assert docker_ev.value == "installed"


async def test_handles_subprocess_failure_gracefully(tmp_path: Path):
    """If --version fails (non-zero exit), tool emitted as 'installed'."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/make" if t == "make" else None

        mock_proc = _mock_proc(stdout=b"", stderr=b"", returncode=1)
        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    make_ev = _find_event(events, "make")
    assert make_ev is not None
    assert make_ev.value == "installed"


async def test_handles_oserror_on_exec(tmp_path: Path):
    """If creating the subprocess raises OSError, tool emitted as 'installed'."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/cargo" if t == "cargo" else None

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            side_effect=OSError("exec format error"),
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            count = await scan(tmp_path, emit)

    assert count == 1
    events = _collect_events(emit)
    cargo_ev = _find_event(events, "cargo")
    assert cargo_ev is not None
    assert cargo_ev.value == "installed"


async def test_panel_name_always_cli_toolchain(tmp_path: Path):
    """Every emitted event must have panel='cli_toolchain'."""
    emit = AsyncMock()

    tools_found = {"git": "/usr/bin/git", "node": "/usr/bin/node", "jq": "/usr/bin/jq"}

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: tools_found.get(t)

        mock_proc = _mock_proc(stdout=b"v1.0.0\n")
        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    assert len(events) == 3
    for ev in events:
        assert ev.panel == "cli_toolchain"


async def test_count_matches_emitted_events(tmp_path: Path):
    """Return value must equal the number of emitted ScanUpdate events."""
    emit = AsyncMock()

    tools_found = {"git": "/usr/bin/git", "pip": "/usr/bin/pip"}

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: tools_found.get(t)

        mock_proc = _mock_proc(stdout=b"version 1.2.3\n")
        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            count = await scan(tmp_path, emit)

    events = _collect_events(emit)
    assert count == len(events)
    assert count == 2


async def test_gh_capability_check_authenticated(tmp_path: Path):
    """When gh is installed AND gh auth status succeeds, detail='authenticated'."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/gh" if t == "gh" else None

        # First call: gh --version. Second call: gh auth status.
        version_proc = _mock_proc(stdout=b"gh version 2.44.1 (2024-03-01)\n")
        auth_proc = _mock_proc(returncode=0)

        procs = iter([version_proc, auth_proc])

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    gh_ev = _find_event(events, "gh")
    assert gh_ev is not None
    assert gh_ev.value == "2.44.1"
    assert gh_ev.detail == "authenticated"


async def test_gh_capability_check_not_authenticated(tmp_path: Path):
    """When gh auth status fails, detail should be empty."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/gh" if t == "gh" else None

        version_proc = _mock_proc(stdout=b"gh version 2.44.1 (2024-03-01)\n")
        auth_proc = _mock_proc(returncode=1, stderr=b"not logged in\n")

        procs = iter([version_proc, auth_proc])

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    gh_ev = _find_event(events, "gh")
    assert gh_ev is not None
    assert gh_ev.detail == ""


async def test_docker_capability_check_daemon_running(tmp_path: Path):
    """When docker is installed AND docker info succeeds, detail='daemon running'."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/docker" if t == "docker" else None

        version_proc = _mock_proc(stdout=b"Docker version 25.0.3, build 4debf41\n")
        info_proc = _mock_proc(returncode=0)

        procs = iter([version_proc, info_proc])

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    docker_ev = _find_event(events, "docker")
    assert docker_ev is not None
    assert docker_ev.value == "25.0.3"
    assert docker_ev.detail == "daemon running"


async def test_docker_capability_check_daemon_not_running(tmp_path: Path):
    """When docker info fails, detail should be empty."""
    emit = AsyncMock()

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: "/usr/bin/docker" if t == "docker" else None

        version_proc = _mock_proc(stdout=b"Docker version 25.0.3, build 4debf41\n")
        info_proc = _mock_proc(returncode=1, stderr=b"Cannot connect to Docker daemon\n")

        procs = iter([version_proc, info_proc])

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            side_effect=lambda *a, **kw: next(procs),
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            await scan(tmp_path, emit)

    events = _collect_events(emit)
    docker_ev = _find_event(events, "docker")
    assert docker_ev is not None
    assert docker_ev.detail == ""


async def test_multiple_tools_detected_in_parallel(tmp_path: Path):
    """Multiple installed tools should all be detected."""
    emit = AsyncMock()

    tools_found = {
        "git": "/usr/bin/git",
        "python3": "/usr/bin/python3",
        "ruff": "/usr/bin/ruff",
    }

    version_map = {
        "git": b"git version 2.43.0\n",
        "python3": b"Python 3.12.3\n",
        "ruff": b"ruff 0.4.1\n",
    }

    with patch("bonfire.onboard.scanners.cli_toolchain.shutil.which") as mock_which:
        mock_which.side_effect = lambda t: tools_found.get(t)

        async def mock_exec(*args, **kwargs):
            tool_name = args[0]
            stdout = version_map.get(tool_name, b"unknown 0.0.0\n")
            return _mock_proc(stdout=stdout)

        with patch(
            "bonfire.onboard.scanners.cli_toolchain.asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from bonfire.onboard.scanners.cli_toolchain import scan

            count = await scan(tmp_path, emit)

    assert count == 3
    events = _collect_events(emit)
    labels = {e.label for e in events}
    assert labels == {"git", "python3", "ruff"}
    assert _find_event(events, "git").value == "2.43.0"
    assert _find_event(events, "python3").value == "3.12.3"
    assert _find_event(events, "ruff").value == "0.4.1"
