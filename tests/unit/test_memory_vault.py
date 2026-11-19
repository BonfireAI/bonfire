# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests: `InMemoryVaultBackend` O(n²) ingest hardening.

Found in a performance review. The
"in-memory" vault backend is the *shipping default* when knowledge is
unconfigured (`knowledge/__init__.py` factory returns it for both
``enabled=False`` and ``backend="memory"``).

The defect: ``exists(content_hash)`` is ``any(... for e in self._entries)`` —
linear in vault size. Every ingest path calls ``exists()`` once per entry
before storing, so ingesting *n* entries is **O(n²)**. ``query()`` also
re-lowercases ``e.content`` for every entry on every call.

These tests pin the *intended post-fix* complexity:

* ``exists`` must be O(1) — a hash-indexed dedup, not a list scan. Pinned
  deterministically by counting how many stored content-hash values are
  inspected per ``exists`` call (a counting ``str`` subclass instruments
  the ``==`` comparison). O(1) means a bounded, vault-size-independent
  comparison count; the current ``any(...)`` scan touches one comparison
  per stored entry.
* ``query`` must not allocate a fresh ``e.content.lower()`` per entry in
  the hot path — the lowercased form is cached at insert. Pinned by
  counting ``str.lower`` invocations across two successive queries.
* ingest of N and 2N entries does linear work — pinned by counting
  comparisons and interpreter instructions, not by timing (see
  ``TestIngestWorkIsLinear``).

Test authors and implementation authors are different hands (TDD law).
Implementation NEVER edits this file.
"""

from __future__ import annotations

import importlib
import sys
import time
import types
from collections.abc import Callable

from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultEntry

# Sizes for the work-counting tests in ``TestIngestWorkIsLinear``.
_WORK_N = 2_000
_WORK_2N = 4_000


class _CountingStr(str):
    """A ``str`` that counts how many times it is compared with ``==``.

    Used to instrument ``exists(content_hash)``: the backend compares the
    looked-up hash against stored hashes. A linear scan compares against
    *every* stored entry; an O(1) hash-indexed lookup compares against at
    most a small constant number.
    """

    eq_calls = 0
    hash_calls = 0

    def __eq__(self, other: object) -> bool:
        type(self).eq_calls += 1
        return str.__eq__(self, other)

    def __hash__(self) -> int:
        type(self).hash_calls += 1
        return str.__hash__(self)


class _CountingLowerStr(str):
    """A ``str`` whose ``.lower()`` invocations are counted.

    Pydantic coerces ``VaultEntry.content`` to a plain ``str`` at
    construction, so this subclass is injected onto the *stored* entries
    after the fact (see ``test_query_does_not_lower_content_on_every_call``)
    to instrument ``query()``: the current implementation calls
    ``e.content.lower()`` once per entry per query; a cached-at-insert
    design calls ``.lower()`` on the content at most once total.
    """

    lower_calls = 0

    def lower(self) -> str:
        type(self).lower_calls += 1
        return str.lower(self)


async def _ingest(
    backend: InMemoryVaultBackend,
    n: int,
    *,
    prefix: str = "h",
    hash_factory: Callable[[str], str] = str,
) -> None:
    """Ingest n entries the way real ingest paths do: exists-check then store."""
    for i in range(n):
        c_hash = hash_factory(f"{prefix}{i}")
        if not await backend.exists(c_hash):
            await backend.store(
                VaultEntry(
                    content=f"payload number {i}",
                    entry_type="code_chunk",
                    content_hash=c_hash,
                )
            )


class MonitoringToolBusyError(RuntimeError):
    """The interpreter-work counter cannot run: its monitoring tool id is taken.

    Raised instead of skipping, so a busy profiler can never turn the test
    into a silent pass.
    """

    code = "sys_monitoring_tool_busy"


def _memory_module_code_objects(module: types.ModuleType) -> list[types.CodeType]:
    """Every code object defined in ``module``'s file, nested ones included.

    Walks module-level functions and class members, then each code object's
    ``co_consts`` so nested generator expressions and inner functions are
    found. The walk is bounded by the finite nesting depth of the source.
    """
    found: dict[int, types.CodeType] = {}

    def add(code: types.CodeType) -> None:
        if code.co_filename != module.__file__ or id(code) in found:
            return
        found[id(code)] = code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                add(const)

    def add_member(member: object) -> None:
        member = getattr(member, "__func__", member)
        member = getattr(member, "fget", member)
        code = getattr(member, "__code__", None)
        if isinstance(code, types.CodeType):
            add(code)

    for value in vars(module).values():
        if isinstance(value, type):
            for member in vars(value).values():
                add_member(member)
        else:
            add_member(value)
    return list(found.values())


async def _count_interpreter_ops(n: int, *, prefix: str) -> int:
    """Count bytecode instructions run inside ``knowledge/memory.py`` by an ingest."""
    mod = importlib.import_module("bonfire.knowledge.memory")
    codes = _memory_module_code_objects(mod)
    monitoring = sys.monitoring
    tool = monitoring.PROFILER_ID
    if monitoring.get_tool(tool) is not None:
        raise MonitoringToolBusyError(
            f"sys.monitoring tool id {tool} is in use; cannot count interpreter work"
        )
    counter = [0]

    def on_instruction(code: types.CodeType, offset: int) -> None:
        counter[0] += 1

    monitoring.use_tool_id(tool, "memory-ingest-work")
    try:
        monitoring.register_callback(tool, monitoring.events.INSTRUCTION, on_instruction)
        for code in codes:
            monitoring.set_local_events(tool, code, monitoring.events.INSTRUCTION)
        await _ingest(mod.InMemoryVaultBackend(), n, prefix=prefix)
    finally:
        for code in codes:
            monitoring.set_local_events(tool, code, 0)
        monitoring.register_callback(tool, monitoring.events.INSTRUCTION, None)
        monitoring.free_tool_id(tool)
    return counter[0]


class TestIngestWorkIsLinear:
    """Ingest does linear work: counted, not timed.

    Two counters, each compared at N and 2N entries against an absolute
    linear bound (never a ratio):

    * comparisons: stored hashes are compared with ``==`` (``_CountingStr``).
    * interpreter work: bytecode instructions run inside
      ``knowledge/memory.py`` (``sys.monitoring``).

    Known residue: quadratic work done entirely in C, for example a list
    copied on every store (``self._entries = self._entries + [entry]``),
    raises neither counter. This class does not cover that family.

    History: an earlier test timed ingest at 100k and 200k entries and capped
    the ratio at 3.0x. On a shared CI runner it measured 3.16x on a correct
    implementation, so it was replaced by counts that do not depend on
    machine load.
    """

    async def test_ingest_comparisons_scale_linearly(self) -> None:
        counts: dict[int, tuple[int, int]] = {}
        for n in (_WORK_N, _WORK_2N):
            _CountingStr.eq_calls = 0
            _CountingStr.hash_calls = 0
            await _ingest(InMemoryVaultBackend(), n, prefix="c", hash_factory=_CountingStr)
            counts[n] = (_CountingStr.eq_calls, _CountingStr.hash_calls)
            assert counts[n][1] >= n, (
                f"VOID: only {counts[n][1]} hash lookups for {n} entries — "
                "the counting probe never reached the exists() lookup"
            )
        eq_n, eq_2n = counts[_WORK_N][0], counts[_WORK_2N][0]
        assert eq_2n <= 2 * eq_n + 16, (
            f"comparisons grew quadratically: {eq_n} at {_WORK_N} entries, "
            f"{eq_2n} at {_WORK_2N} entries"
        )

    async def test_ingest_interpreter_work_scales_linearly(self) -> None:
        ops_n = await _count_interpreter_ops(_WORK_N, prefix="o")
        ops_2n = await _count_interpreter_ops(_WORK_2N, prefix="p")
        assert ops_n >= _WORK_N, (
            f"VOID: {ops_n} instructions counted for {_WORK_N} entries — "
            "the counter never fired inside knowledge/memory.py"
        )
        assert ops_2n <= 2 * ops_n + 64, (
            "interpreter work in knowledge/memory.py grew quadratically: "
            f"{ops_n} instructions at {_WORK_N} entries, {ops_2n} at {_WORK_2N} entries"
        )


class TestExistsIsConstantTime:
    """AC: ``InMemoryVaultBackend.exists`` is O(1) (hash-indexed dedup)."""

    async def test_exists_does_not_scan_every_entry(self) -> None:
        """A single ``exists`` call on a 500-entry vault must inspect a
        bounded, vault-size-independent number of stored hashes.

        The O(n²) defect: ``exists`` is ``any(e.content_hash == h for e in
        self._entries)`` — one ``==`` per stored entry. A hash-indexed
        ``dict`` lookup performs at most a small constant number of
        comparisons. We pin "constant" generously at <= 8 to tolerate a
        dict's internal probing while still failing hard on a 500-wide
        linear scan.
        """
        backend = InMemoryVaultBackend()
        n = 500
        for i in range(n):
            await backend.store(
                VaultEntry(
                    content=f"entry {i}",
                    entry_type="code_chunk",
                    content_hash=f"stored-{i}",
                )
            )

        _CountingStr.eq_calls = 0
        # Look up a hash that IS present (forces full scan in the buggy impl).
        found = await backend.exists(_CountingStr("stored-499"))
        assert found is True
        assert _CountingStr.eq_calls <= 8, (
            f"exists() inspected {_CountingStr.eq_calls} stored hashes for a "
            f"{n}-entry vault — expected O(1) hash-indexed lookup, not a linear scan"
        )

    async def test_exists_comparison_count_does_not_grow_with_vault_size(self) -> None:
        """The per-call comparison count for ``exists`` must not grow as the
        vault grows. O(1) means the count for a 1000-entry vault equals the
        count for a 100-entry vault; an O(n) scan makes it grow 10x.
        """

        async def _count_for(size: int) -> int:
            backend = InMemoryVaultBackend()
            for i in range(size):
                await backend.store(
                    VaultEntry(
                        content=f"c{i}",
                        entry_type="code_chunk",
                        content_hash=f"k-{i}",
                    )
                )
            _CountingStr.eq_calls = 0
            # Miss case — the buggy `any(...)` scans the whole list on a miss.
            await backend.exists(_CountingStr("absent-hash"))
            return _CountingStr.eq_calls

        small = await _count_for(100)
        large = await _count_for(1000)
        assert large <= small + 4, (
            f"exists() comparison count grew from {small} (100 entries) to "
            f"{large} (1000 entries) — that is O(n), not O(1)"
        )


class TestQueryDoesNotRelowerPerEntry:
    """AC: ``query`` runs without per-entry ``.lower()`` allocation in the
    hot path (content lowercased once, cached at insert)."""

    async def test_query_does_not_relower_content_on_every_call(self) -> None:
        """``query()`` must not re-lower every entry's content on every call.

        The defect: ``query`` does ``e.content.lower()`` inside the scoring
        comprehension — every entry, every query. The fix caches the
        lowercased form (at insert, or lazily once per entry). Either way,
        ``content.lower()`` is invoked **at most once per entry total**, not
        once per entry per query.

        Pydantic coerces ``VaultEntry.content`` to a plain ``str``, so the
        instrumented ``_CountingLowerStr`` is placed via ``model_construct``
        (validation-bypassing) and stored through the real ``store()`` path,
        which appends the entry as-is.

        With N=20 entries and 3 queries:
          * buggy impl  -> 3 * 20 = 60 ``.lower()`` calls
          * cached impl -> <= 20 calls (once per entry, at store or first use)
        Threshold ``<= 20`` passes any valid cache and fails the re-lower.
        """
        backend = InMemoryVaultBackend()
        n = 20
        for i in range(n):
            entry = VaultEntry.model_construct(
                content=_CountingLowerStr(f"alpha beta entry {i}"),
                entry_type="code_chunk",
                content_hash=f"q-{i}",
            )
            await backend.store(entry)
        # Confirm the instrumented subclass actually survived onto the
        # stored entries — otherwise the test would be vacuously green.
        assert all(isinstance(e.content, _CountingLowerStr) for e in backend._entries)

        _CountingLowerStr.lower_calls = 0
        await backend.query("alpha")
        await backend.query("beta")
        await backend.query("entry")
        assert _CountingLowerStr.lower_calls <= n, (
            f"query() invoked content.lower() {_CountingLowerStr.lower_calls} times "
            f"across 3 queries over {n} entries — expected <= {n} (lowercased form "
            "cached per entry, not recomputed every query)"
        )


class TestIngestHasTimeCap:
    """AC: ingest of many entries completes under a generous wall-clock cap."""

    async def test_ten_thousand_entry_ingest_completes_under_cap(self) -> None:
        """The AC's explicit wall-clock check: ingest of 10,000 entries
        completes well under a generous cap. O(n²) ingest of 10k entries
        does ~50M comparisons and blows past this; O(n) finishes in a blink.
        """
        backend = InMemoryVaultBackend()
        start = time.perf_counter()
        await _ingest(backend, 10_000, prefix="cap")
        elapsed = time.perf_counter() - start
        assert len(backend._entries) == 10_000
        assert elapsed < 1.0, (
            f"Ingest of 10,000 entries took {elapsed:.3f}s — expected < 1.0s for "
            "linear ingest; a quadratic exists()-per-entry scan is far slower"
        )
