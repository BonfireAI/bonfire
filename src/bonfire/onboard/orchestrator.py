# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Scan Orchestrator — composition root for all 6 Front Door scanners.

Runs every scanner in parallel via ``asyncio.gather``, emits lifecycle
events (``ScanStart``, ``ScanComplete``, ``AllScansComplete``), and
routes per-scanner ``ScanUpdate`` events through a single callback.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import (
    AllScansComplete,
    FrontDoorMessage,
    ScanComplete,
    ScanStart,
    ScanUpdate,
)
from bonfire.onboard.scanners import (
    claude_memory,
    cli_toolchain,
    git_state,
    mcp_servers,
    project_structure,
    vault_seed,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from types import ModuleType

__all__ = ["run_scan"]

_log = logging.getLogger(__name__)


def _get_scanners() -> list[tuple[str, ModuleType]]:
    """Build scanner list at call-time so tests can patch module names."""
    return [
        ("project_structure", project_structure),
        ("cli_toolchain", cli_toolchain),
        ("claude_memory", claude_memory),
        ("git_state", git_state),
        ("mcp_servers", mcp_servers),
        ("vault_seed", vault_seed),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_scan(
    project_path: Path,
    emit: Callable[[FrontDoorMessage], Awaitable[None]],
) -> int:
    """Run all 6 scanners in parallel, emit lifecycle + scan events.

    Emits in order:

    1. ``ScanStart(panels=[...])`` — all 6 panel names
    2. ``ScanUpdate`` events from each scanner (interleaved, parallel)
    3. ``ScanComplete(panel=..., item_count=N)`` — per scanner as each finishes
    4. ``AllScansComplete(total_items=N)`` — when all are done

    Returns total item count across all scanners.
    """
    scanners = _get_scanners()
    panel_names = [name for name, _ in scanners]
    await emit(ScanStart(panels=panel_names))

    tasks = [_run_one(panel, module, project_path, emit) for panel, module in scanners]
    results: list[tuple[int, bool]] = await asyncio.gather(*tasks)

    total = sum(count for count, _ in results)
    failed_panels = sum(1 for _, failed in results if failed)
    await emit(AllScansComplete(total_items=total, failed_panels=failed_panels))
    return total


# ---------------------------------------------------------------------------
# Per-scanner wrapper
# ---------------------------------------------------------------------------


async def _run_one(
    panel: str,
    module: ModuleType,
    project_path: Path,
    emit: Callable[[FrontDoorMessage], Awaitable[None]],
) -> tuple[int, bool]:
    """Execute a single scanner, emit ScanComplete, report ``(count, failed)``.

    A crashed scanner used to be indistinguishable from a clean scan
    that found nothing: both emitted ``item_count=0`` and the browser
    said "we scanned and found nothing" over a scanner that had died.
    The exception is still swallowed — one broken scanner must not
    abort the other five — but it is now REPORTED rather than erased.
    """

    async def _narrow_emit(event: ScanUpdate) -> None:
        """Forward ScanUpdate from the scanner to the orchestrator emit."""
        await emit(event)

    failed = False
    error: str | None = None
    try:
        count = await module.scan(project_path, _narrow_emit)
    except Exception as exc:  # noqa: BLE001
        _log.exception("Scanner %s failed", panel)
        count = 0
        failed = True
        error = f"{type(exc).__name__}: {exc}"

    await emit(ScanComplete(panel=panel, item_count=count, failed=failed, error=error))
    return count, failed
