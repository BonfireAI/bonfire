# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""vault_seed symlink + size-cap hardening.

These tests cover two threat models flagged as HIGH:

1. ``_scan_project_size`` recursing through a symlink loop or a
   ``/``-rooted symlink — fixed by switching to
   :func:`os.fwalk` with ``followlinks=False`` plus a hard entry cap.
2. ``_scan_test_config`` doing an unbounded ``Path.read_text`` on
   ``pyproject.toml`` — fixed by routing through
   :func:`bonfire._safe_read.safe_read_text`.

The tests construct *real* symlink loops and *real* oversize files via
``tmp_path``; nothing here is mocked. The symlink-loop test asserts
``_scan_project_size`` returns in bounded time and reports a finite
count — the cap-guarantee that ``followlinks=False`` provides.
"""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import AsyncMock

import pytest

from bonfire._safe_read import SAFE_READ_TRUNCATION_MARKER
from bonfire.onboard.protocol import ScanUpdate
from bonfire.onboard.scanners import vault_seed


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    return [c.args[0] for c in emit.call_args_list]


# ---------------------------------------------------------------------------
# Symlink loop — _scan_project_size
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="symlinks require elevated rights on Windows; loop semantics tested on POSIX",
)
async def test_symlink_loop_does_not_recurse(tmp_path) -> None:
    """A directory containing a self-loop symlink must NOT walk forever.

    Constructs ``loop_root/inner -> loop_root`` and one real file at
    ``loop_root/main.py``. With ``Path.rglob`` (legacy) this would walk
    forever; with ``os.fwalk(followlinks=False)`` the symlink directory
    is not descended into, so the walk terminates and reports a finite
    file count.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("x = 1\n")

    # Self-referential symlink: project/inner -> project. Walking with
    # follow-symlinks=True would recurse infinitely; followlinks=False
    # treats the symlink as a directory entry that is NOT descended.
    loop = project / "inner"
    loop.symlink_to(project, target_is_directory=True)

    emit = AsyncMock()
    # _scan_project_size always emits exactly one event; the test
    # passes iff the call returns at all (no infinite recursion).
    await vault_seed._scan_project_size(project, emit)

    events = _events(emit)
    size_events = [e for e in events if e.label == "project size"]
    assert len(size_events) == 1
    # Exactly one real file under the project tree.
    assert size_events[0].value == "~1 files"


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="symlinks require elevated rights on Windows",
)
async def test_symlink_loop_via_full_scan(tmp_path) -> None:
    """End-to-end ``scan()`` survives a symlink loop in the project tree."""
    (tmp_path / "main.py").write_text("y = 2\n")
    loop = tmp_path / "loop"
    loop.symlink_to(tmp_path, target_is_directory=True)

    emit = AsyncMock()
    count = await vault_seed.scan(tmp_path, emit)
    # The scan returned (did not hang) and emitted at least the size event.
    assert count >= 1
    events = _events(emit)
    assert any(e.label == "project size" for e in events)


async def test_entry_cap_truncates_with_warning(tmp_path, caplog, monkeypatch) -> None:
    """When the entry cap is exceeded the walk returns + WARNS.

    Lowers ``_SCAN_ENTRY_CAP`` to 5 and creates 20 files. The scan must
    stop counting at the cap, return the partial size event, and log a
    WARNING — not raise, not hang.
    """
    monkeypatch.setattr(vault_seed, "_SCAN_ENTRY_CAP", 5)

    for i in range(20):
        (tmp_path / f"file_{i}.py").write_text("z = 0\n")

    emit = AsyncMock()
    with caplog.at_level(logging.WARNING, logger=vault_seed._log.name):
        await vault_seed._scan_project_size(tmp_path, emit)

    events = _events(emit)
    size_events = [e for e in events if e.label == "project size"]
    assert len(size_events) == 1
    # file_count is bounded by the cap (test infra may add zero or one
    # auxiliary entry; ``~5 files`` is the canonical value).
    assert size_events[0].value == "~5 files"
    assert any("entry cap" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# os.fwalk default check — defensive lock against future refactor
# ---------------------------------------------------------------------------


async def test_uses_fwalk_follow_symlinks_false(monkeypatch, tmp_path) -> None:
    """``_scan_project_size`` MUST call ``os.fwalk`` with ``follow_symlinks=False``.

    This is a defensive contract: if a future refactor flips the
    default to ``follow_symlinks=True`` (or moves back to
    ``Path.rglob`` which silently follows symlinks), the DoS
    surface returns quietly. The test fails loudly in that case.

    Note: ``os.fwalk`` uses ``follow_symlinks`` (matches ``os.stat``)
    while ``os.walk`` uses ``followlinks`` — the kwarg names differ
    across the stdlib.
    """
    seen: dict[str, object] = {}
    real_fwalk = os.fwalk

    def spy_fwalk(top, *args, **kwargs):
        seen["follow_symlinks"] = kwargs.get("follow_symlinks", "MISSING")
        return real_fwalk(top, *args, **kwargs)

    monkeypatch.setattr(vault_seed.os, "fwalk", spy_fwalk)

    (tmp_path / "main.py").write_text("a = 1\n")
    emit = AsyncMock()
    await vault_seed._scan_project_size(tmp_path, emit)

    assert seen.get("follow_symlinks") is False, (
        f"_scan_project_size must pass follow_symlinks=False to os.fwalk; got {seen}"
    )


# ---------------------------------------------------------------------------
# pyproject.toml size cap (`_scan_test_config`)
# ---------------------------------------------------------------------------


async def test_large_pyproject_truncated_under_cap(tmp_path, monkeypatch, caplog) -> None:
    """An oversize ``pyproject.toml`` is read truncated, not hung on."""
    # Drop cap to 256 bytes so the test is fast.
    monkeypatch.setenv("BONFIRE_VAULT_SEED_PYPROJECT_MAX_BYTES", "256")

    pyproject = tmp_path / "pyproject.toml"
    # Write a payload well over the cap; include [tool.pytest within the
    # first 256 bytes so the truncated-read still detects the marker.
    header = "[project]\nname='x'\n[tool.pytest.ini_options]\naddopts='-v'\n"
    padding = "# pad line\n" * 5000
    pyproject.write_text(header + padding)

    emit = AsyncMock()
    with caplog.at_level(logging.WARNING):
        await vault_seed._scan_test_config(tmp_path, emit)

    events = _events(emit)
    test_events = [e for e in events if e.label == "test config"]
    # Detection still works on the truncated content.
    assert any("pyproject.toml" in e.value for e in test_events)
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


async def test_large_pyproject_marker_marker_is_present_via_helper(tmp_path, monkeypatch) -> None:
    """The truncation marker is appended on oversize reads.

    Reading the file directly through ``safe_read_text`` confirms the
    same byte-cap mechanism the scanner relies on.
    """
    from bonfire._safe_read import safe_read_text

    monkeypatch.setenv("BONFIRE_VAULT_SEED_PYPROJECT_MAX_BYTES", "128")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='x'\n" + "x" * 10_000)

    out = safe_read_text(
        pyproject,
        env_var="BONFIRE_VAULT_SEED_PYPROJECT_MAX_BYTES",
        default_bytes=128,
    )
    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)


async def test_existing_pytest_detection_unbroken(tmp_path) -> None:
    """The legacy [tool.pytest detection still works on a normal file.

    Regression-pin against the cap mechanism accidentally breaking the
    small-file path.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='test'\n\n[tool.pytest.ini_options]\naddopts = '-v'\n"
    )

    emit = AsyncMock()
    await vault_seed._scan_test_config(tmp_path, emit)

    events = _events(emit)
    test_events = [e for e in events if e.label == "test config"]
    assert any("pyproject.toml" in e.value for e in test_events)
