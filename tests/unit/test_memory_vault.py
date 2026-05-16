# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests — BON-907 — `InMemoryVaultBackend` O(n²) ingest hardening.

Surfaced by the Mirror Path B production-1 performance Scout. The
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
* a scaling benchmark asserts ingest of N and 2N entries stays roughly
  linear (the time ratio is ~2x, not ~4x) — the AC's wall-clock cap,
  expressed as a ratio so it is robust to machine speed.

Test authors and implementation authors are different hands (TDD law).
Implementation NEVER edits this file.
"""

from __future__ import annotations

import time

from bonfire.knowledge.memory import InMemoryVaultBackend
from bonfire.protocols import VaultEntry

# Scaling-benchmark sizes for ``test_ingest_does_not_scale_quadratically``.
# Sized to make the small-n timing noise wash out: at n=10k the ratio's noise
# tail on shared GitHub runners spiked into the 3.4-3.5x band even for a
# correct linear-time impl, failing the gate on BOTH buggy and fixed code.
# At n=50k the first-run still pushed 2.7x on a developer machine — too close
# to the 3.0 cap for shared-runner comfort. At n=100k/200k the asymptotic
# O(n²) vs O(n) separation dominates the noise — a correct impl settles
# tightly into the ~1.9-2.3x band over 5 runs and a regression to O(n²)
# still clears the ~4x bar by a wide margin. Bumping n (not the cap) is the
# right knob; the < 3.0 cap stays. Total wall-clock ~3s per run on a
# developer machine, well under the 30s test-budget ceiling.
_INGEST_N_SMALL = 100_000
_INGEST_N_LARGE = 200_000


class _CountingStr(str):
    """A ``str`` that counts how many times it is compared with ``==``.

    Used to instrument ``exists(content_hash)``: the backend compares the
    looked-up hash against stored hashes. A linear scan compares against
    *every* stored entry; an O(1) hash-indexed lookup compares against at
    most a small constant number.
    """

    eq_calls = 0

    def __eq__(self, other: object) -> bool:  # noqa: D105
        type(self).eq_calls += 1
        return str.__eq__(self, other)

    def __hash__(self) -> int:  # noqa: D105
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

    def lower(self) -> str:  # noqa: D102
        type(self).lower_calls += 1
        return str.lower(self)


async def _ingest(backend: InMemoryVaultBackend, n: int, *, prefix: str = "h") -> None:
    """Ingest n entries the way real ingest paths do: exists-check then store."""
    for i in range(n):
        c_hash = f"{prefix}{i}"
        if not await backend.exists(c_hash):
            await backend.store(
                VaultEntry(
                    content=f"payload number {i}",
                    entry_type="code_chunk",
                    content_hash=c_hash,
                )
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


class TestIngestScalesLinearly:
    """AC: a benchmark asserts ingest of many entries completes in linear
    time. Expressed as a scaling ratio so it is robust across machines:
    doubling the entry count must roughly double the wall time, not
    quadruple it."""

    async def test_ingest_does_not_scale_quadratically(self) -> None:
        """Ingest N and 2N entries; assert the time ratio is sub-quadratic.

        O(n²) ingest gives a ~4x ratio when n doubles; O(n) gives ~2x. We
        fail above 3.0x — comfortably between the two so timing jitter on a
        loaded machine does not flake a correct linear implementation, but a
        genuine quadratic regression (4x+) is caught.

        Scale history. n=10_000 was the original sizing: characterized GREEN
        (set-indexed exists) showed median ~2.05x, max ~2.48x over 10 runs
        on a developer machine; characterized PRE-FIX (linear-scan exists)
        showed median ~4.09x, min ~3.57x over 5 runs. (Smaller n e.g. 4_000
        produced a flat ~2.2x median for BOTH buggy and fixed — the signal
        had not yet risen out of timing noise.)

        Scale today: n = 100_000 / 2n = 200_000. On shared GitHub runners the
        n=10_000 ratio's noise tail spiked into the 3.4-3.5x band even with
        the linear-time fix in place, failing the gate on both buggy and
        fixed code — i.e. the cap discriminated nothing. The right knob is
        larger n, NOT raising the cap: asymptotic O(n) vs O(n²) behavior
        dominates at higher n while wall-clock noise stays bounded. At
        100k/200k the ratio sits tightly in the ~1.9-2.3x band on a
        developer machine over 5 runs (max ratio 2.27, well below the cap)
        and a true quadratic still clears 4x by a wide margin. The < 3.0
        cap stays. Test wall-clock ~3s per run on a developer machine.

        If CI runners ever can't budget the wall-clock cost, mark this
        with ``@pytest.mark.slow`` rather than weakening the cap or
        lowering n. The cap is the load-bearing invariant; n is the knob
        that makes the cap meaningful.
        """
        n_small = _INGEST_N_SMALL
        n_large = _INGEST_N_LARGE

        backend_n = InMemoryVaultBackend()
        start = time.perf_counter()
        await _ingest(backend_n, n_small, prefix="a")
        elapsed_n = time.perf_counter() - start

        backend_2n = InMemoryVaultBackend()
        start = time.perf_counter()
        await _ingest(backend_2n, n_large, prefix="b")
        elapsed_2n = time.perf_counter() - start

        # Guard against a near-zero denominator on a very fast machine.
        floor = 1e-4
        ratio = elapsed_2n / max(elapsed_n, floor)
        # performance: linear-time invariant. Ratio of wall-clock for 2n vs n
        # ingest must stay sub-quadratic. ~2.0 = O(n), ~4.0 = O(n²); the 3.0
        # cap is load-bearing — see this method's docstring for the
        # characterization data behind the choice of cap and n.
        assert ratio < 3.0, (
            f"Doubling ingest from {n_small} to {n_large} entries took "
            f"{ratio:.2f}x longer ({elapsed_n:.4f}s -> {elapsed_2n:.4f}s) — "
            "expected ~2x for linear ingest; ~4x indicates the O(n²) "
            "exists()-per-entry defect"
        )

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
