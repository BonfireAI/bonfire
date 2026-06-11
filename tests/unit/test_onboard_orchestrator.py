# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract tests for ``bonfire.onboard.orchestrator.run_scan``.

``run_scan`` is the public composition root that fans the six Front Door
scanners out across ``asyncio.gather`` and narrates their lifecycle through a
single ``emit`` callback. Its docstring declares a hard ordered-emit contract
and ``_run_one`` declares a failure-isolation contract — but until now nothing
pinned either, so a refactor could quietly drop ``ScanStart``, reorder the
lifecycle, mis-sum the total, or let one scanner's crash abort the whole gather
without a single test going red. (``test_scan_cli.py`` patches the unrelated CLI
helper ``bonfire.cli.commands.scan._run_scan``, not this orchestrator — so the
orchestrator's own contract was genuinely unguarded.)

These tests lock three clauses of that contract:

* CLAUSE 1 — ordered lifecycle: ``ScanStart(panels=[all 6])`` first, then one
  ``ScanComplete(panel, item_count)`` per scanner, then a single
  ``AllScansComplete(total_items)`` last.
* CLAUSE 2 — total accounting: ``AllScansComplete.total_items`` equals the sum
  of every scanner's count, and the int ``run_scan`` returns matches it.
* CLAUSE 3 — failure isolation (the Elegance Law made testable): when one
  scanner raises, ``_run_one`` lets the failure *speak* via ``_log.exception``
  and substitutes ``item_count=0`` for that panel, while every other scanner's
  count survives and the gather still completes.

Patching strategy: ``_get_scanners()`` rebuilds its ``(name, module)`` list on
every call precisely so tests can swap in deterministic ``scan`` coroutines. We
``monkeypatch.setattr`` each scanner module's ``scan`` attribute; ``_run_one``
calls ``module.scan(...)`` by attribute lookup, so the fakes are picked up. All
``emit`` calls are awaited, so the collector is an async callable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

# Eager runtime imports: the event types are asserted by ``isinstance`` and the
# scanner modules are the patch targets, so they must exist at runtime (not just
# under TYPE_CHECKING).
from bonfire.onboard import orchestrator
from bonfire.onboard.protocol import (
    AllScansComplete,
    ScanComplete,
    ScanStart,
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
    from collections.abc import Callable

# The six panels in the exact order ``_get_scanners`` builds them. The order is
# part of the contract: ScanStart.panels must list all six, and it is the order
# operators see the reel light up.
EXPECTED_PANELS = [
    "project_structure",
    "cli_toolchain",
    "claude_memory",
    "git_state",
    "mcp_servers",
    "vault_seed",
]

# Map panel name -> the imported scanner module, so a test can patch a chosen
# scanner's ``scan`` by name.
_MODULE_BY_PANEL = {
    "project_structure": project_structure,
    "cli_toolchain": cli_toolchain,
    "claude_memory": claude_memory,
    "git_state": git_state,
    "mcp_servers": mcp_servers,
    "vault_seed": vault_seed,
}


class EmitCollector:
    """Async ``emit`` stand-in that records every awaited event in order.

    ``run_scan`` awaits ``emit(event)`` for every lifecycle and scan event, so
    the collector is an async callable; the recorded ``events`` list is the
    ground truth for the ordered-emit assertions.
    """

    def __init__(self) -> None:
        self.events: list[object] = []

    async def __call__(self, event: object) -> None:
        self.events.append(event)


def _make_counting_scan(count: int) -> Callable:
    """Build a deterministic fake ``scan`` coroutine that returns *count*.

    Mirrors the real scanner interface ``async def scan(project_path, emit)``;
    it ignores its arguments and simply reports a fixed item count so the
    orchestrator's accounting can be asserted exactly.
    """

    async def _scan(project_path, emit) -> int:
        return count

    return _scan


def _make_raising_scan(message: str) -> Callable:
    """Build a fake ``scan`` coroutine that raises, to exercise isolation.

    The raised exception is loud and typed (``RuntimeError`` with a distinct
    message) so the failure-isolation test can confirm ``_run_one`` narrated the
    real cause via ``_log.exception`` rather than swallowing it silently.
    """

    async def _scan(project_path, emit) -> int:
        raise RuntimeError(message)

    return _scan


def _patch_all(monkeypatch: pytest.MonkeyPatch, counts: dict[str, int]) -> None:
    """Patch every scanner module's ``scan`` to a deterministic counting fake.

    Keyed by panel name so each scanner can return its own distinct count,
    letting the sum/total assertions distinguish a correct sum from an
    accidental ``len()`` or a dropped scanner.
    """
    for panel, module in _MODULE_BY_PANEL.items():
        monkeypatch.setattr(module, "scan", _make_counting_scan(counts[panel]))


async def test_emits_scan_start_first_with_all_six_panels(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """CLAUSE 1 (head): the very first event is ScanStart listing all 6 panels.

    Locks docstring step 1 — ``ScanStart(panels=[...])`` is emitted before any
    scanner work, and its ``panels`` lists exactly the six panel names in the
    ``_get_scanners`` order. A dropped or reordered ScanStart breaks this.
    """
    _patch_all(monkeypatch, dict.fromkeys(EXPECTED_PANELS, 1))
    collector = EmitCollector()

    await orchestrator.run_scan(tmp_path, collector)

    first = collector.events[0]
    assert isinstance(first, ScanStart), "first emitted event must be ScanStart"
    assert first.panels == EXPECTED_PANELS, (
        "ScanStart.panels must list all six panel names in _get_scanners order"
    )


async def test_emits_one_scan_complete_per_scanner_then_all_complete_last(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """CLAUSE 1 (body+tail): one ScanComplete per scanner, AllScansComplete last.

    Locks docstring steps 3 and 4 — between ScanStart and the single terminal
    ``AllScansComplete`` there is exactly one ``ScanComplete`` for each of the
    six panels (gather order may interleave, so we compare as a set), and
    ``AllScansComplete`` is strictly the final event.
    """
    _patch_all(monkeypatch, dict.fromkeys(EXPECTED_PANELS, 1))
    collector = EmitCollector()

    await orchestrator.run_scan(tmp_path, collector)

    events = collector.events
    # Terminal event is AllScansComplete, and only one of them exists.
    assert isinstance(events[-1], AllScansComplete), "last event must be AllScansComplete"
    assert sum(isinstance(e, AllScansComplete) for e in events) == 1, (
        "exactly one AllScansComplete may be emitted"
    )

    completes = [e for e in events if isinstance(e, ScanComplete)]
    assert len(completes) == len(EXPECTED_PANELS), (
        "exactly one ScanComplete per scanner is required"
    )
    assert {e.panel for e in completes} == set(EXPECTED_PANELS), (
        "every panel must report exactly one ScanComplete"
    )
    # ScanStart precedes all ScanCompletes, which precede AllScansComplete.
    start_idx = next(i for i, e in enumerate(events) if isinstance(e, ScanStart))
    all_done_idx = next(i for i, e in enumerate(events) if isinstance(e, AllScansComplete))
    complete_idxs = [i for i, e in enumerate(events) if isinstance(e, ScanComplete)]
    assert start_idx < min(complete_idxs), "ScanStart must precede every ScanComplete"
    assert max(complete_idxs) < all_done_idx, "every ScanComplete must precede AllScansComplete"


async def test_total_items_sums_counts_and_matches_return_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """CLAUSE 2: AllScansComplete.total_items == sum of counts == return value.

    Locks docstring step 4 + the ``-> int`` return contract. Distinct per-panel
    counts (no two equal) mean a correct sum can only come from adding every
    scanner's real count — not from ``len(scanners)`` or a dropped scanner. Each
    panel's reported ScanComplete.item_count is also checked against its source.
    """
    counts = {
        "project_structure": 3,
        "cli_toolchain": 5,
        "claude_memory": 7,
        "git_state": 11,
        "mcp_servers": 13,
        "vault_seed": 17,
    }
    expected_total = sum(counts.values())  # 56 — all distinct primes, no collisions
    _patch_all(monkeypatch, counts)
    collector = EmitCollector()

    returned = await orchestrator.run_scan(tmp_path, collector)

    assert returned == expected_total, "run_scan must return the summed item count"
    all_done = next(e for e in collector.events if isinstance(e, AllScansComplete))
    assert all_done.total_items == expected_total, (
        "AllScansComplete.total_items must equal the sum of per-scanner counts"
    )
    # Each scanner's own count flows through unchanged on its ScanComplete.
    by_panel = {e.panel: e.item_count for e in collector.events if isinstance(e, ScanComplete)}
    assert by_panel == counts, "each ScanComplete.item_count must match its scanner's count"


async def test_failing_scanner_is_isolated_logs_and_emits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    """CLAUSE 3: a crashing scanner is isolated — failure speaks, count becomes 0.

    Locks ``_run_one``'s failure-isolation contract (the Elegance Law made
    testable). When ``git_state.scan`` raises, the orchestrator must:
      * narrate the failure via ``_log.exception`` (loud, with traceback +
        panel name) rather than swallow it,
      * substitute ``ScanComplete(panel="git_state", item_count=0)`` so the reel
        still resolves, and
      * leave every other scanner's count and the gather itself intact.
    The crash must NOT propagate out of ``run_scan``.
    """
    counts = {
        "project_structure": 3,
        "cli_toolchain": 5,
        "claude_memory": 7,
        "git_state": 11,  # this one will be overridden with a raiser
        "mcp_servers": 13,
        "vault_seed": 17,
    }
    _patch_all(monkeypatch, counts)
    boom_message = "git_state scanner exploded on purpose"
    monkeypatch.setattr(git_state, "scan", _make_raising_scan(boom_message))

    collector = EmitCollector()
    with caplog.at_level(logging.ERROR, logger=orchestrator._log.name):
        returned = await orchestrator.run_scan(tmp_path, collector)

    # Failure isolation: the crash did not abort the gather; survivors are intact.
    by_panel = {e.panel: e.item_count for e in collector.events if isinstance(e, ScanComplete)}
    assert by_panel["git_state"] == 0, (
        "a failing scanner must emit ScanComplete(item_count=0), not abort the gather"
    )
    survivors = {p: c for p, c in counts.items() if p != "git_state"}
    for panel, count in survivors.items():
        assert by_panel[panel] == count, (
            f"survivor panel {panel!r} count must be untouched by another scanner's crash"
        )

    # Total reflects the substituted zero: full sum minus the failed scanner.
    expected_total = sum(survivors.values())
    assert returned == expected_total, (
        "total must drop only the failed scanner's contribution (0), keeping the rest"
    )

    # The failure speaks: an ERROR-level record names the panel and the real cause
    # (exc_info attached by _log.exception), proving it was narrated, not swallowed.
    failure_records = [
        r for r in caplog.records if r.levelno == logging.ERROR and "git_state" in r.getMessage()
    ]
    assert failure_records, "the failing scanner must be narrated at ERROR naming the panel"
    assert any(r.exc_info is not None for r in failure_records), (
        "_log.exception must attach the traceback so the real cause is visible"
    )
