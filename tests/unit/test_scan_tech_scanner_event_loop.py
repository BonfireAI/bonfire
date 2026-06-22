"""`TechScanner.scan` keeps the event loop responsive.

The blocking filesystem walk (``Path.rglob``) and dependency-file reads
(``Path.read_text``) in ``bonfire.scan.tech_scanner.TechScanner`` ran on
the asyncio loop. When ``run_scan`` fans scanners out in parallel, those
sync syscalls block every coroutine on the same loop, including the
WebSocket emitter that feeds the Front Door UI's live progress.

This test pins the contract that ``scan()`` returns control to the
event loop while the blocking work happens — i.e. a concurrent
coroutine running alongside ``scanner.scan()`` is NOT starved.

The verification model is "another coroutine makes progress while
``scan`` is in flight" rather than wall-clock timing. Wall-clock
ratios on a CI runner are flaky; concurrent-progress is a direct
observation of off-loop dispatch.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bonfire.scan.tech_scanner import TechScanner


class TestEventLoopResponsiveDuringScan:
    """``await scanner.scan()`` must yield to the event loop.

    Coroutine ``ticker`` increments a counter every ``asyncio.sleep(0)``
    pass. If ``scan()`` blocks the loop, ``ticker`` runs only after
    ``scan`` finishes — counter never moves while ``scan`` is in
    flight. If ``scan()`` dispatches its blocking work to a thread,
    ``ticker`` continues counting concurrently.
    """

    @pytest.mark.asyncio
    async def test_scan_yields_to_concurrent_coroutine(self, tmp_path: Path) -> None:
        # Make rglob non-trivial: synthesize a tree large enough that a
        # blocking walk would be measurable. 200 files is enough to take
        # several ms of stat syscalls on a typical disk; on a blocking
        # loop the ticker would be stuck at 0 for that whole window.
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n[project.dependencies]\n")
        for i in range(200):
            (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")

        scanner = TechScanner(tmp_path, project_name="demo")

        ticks = 0
        stop = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                # asyncio.sleep(0) yields without delay — the only way
                # this loop runs is if some other coroutine releases
                # the loop. If scan() blocks the loop, ticks stays at
                # its pre-scan value for the entire scan duration.
                await asyncio.sleep(0)

        ticker_task = asyncio.create_task(ticker())
        try:
            # Snapshot ticks just before scan starts.
            await asyncio.sleep(0)
            ticks_before = ticks
            entries = await scanner.scan()
        finally:
            stop.set()
            await ticker_task

        # Scan returns a list (sanity check — the new wiring still
        # produces the expected output shape).
        assert isinstance(entries, list)
        # The ticker must have advanced WHILE scan was awaiting its
        # off-loop thread. A purely-sync scan() would only let ticker
        # run after scan returned; in that case the increment happens
        # only on the ``await asyncio.sleep(0)`` before the scan call.
        # We require strictly more than that — i.e. ticker advanced
        # DURING scan's await, not just before/after.
        assert ticks > ticks_before + 1, (
            f"event loop appears blocked during scan: "
            f"ticks_before={ticks_before}, ticks_after={ticks}"
        )

    @pytest.mark.asyncio
    async def test_scan_returns_when_filesystem_reads_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with a slow-reading ``Path.read_text`` (e.g. network FS,
        slow disk), ``await scan(...)`` still returns. The simulated
        slowness is bounded so the test stays fast, but the principle
        — that read latency does not deadlock the loop — is what's
        pinned.
        """
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname='demo'\n[project.dependencies]\ndjango = \">=5.0\"\n"
        )

        # Wrap read_text with a small synchronous delay. Because the
        # call is dispatched to a thread, the loop stays free.
        original_read_text = Path.read_text

        def slow_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            import time

            time.sleep(0.05)
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", slow_read_text)

        scanner = TechScanner(tmp_path, project_name="demo")
        entries = await asyncio.wait_for(scanner.scan(), timeout=5.0)
        assert isinstance(entries, list)
        # Django still detected through the slow read.
        techs = {e.metadata["technology"] for e in entries}
        assert "Django" in techs
