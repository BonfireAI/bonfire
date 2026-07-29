# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The VERDICT side: what one citation graded to, how a run reports, what it exits.

One of four modules behind ``check_protocol_doc_citations.py`` (see
``citation_doc`` for the split). This module owns the exit contract's
arithmetic and its prose:

* ``0`` — every citation resolved or is registered, AND the graded set
  was non-empty.
* ``1`` — DRIFT: the gate DID its job and found a citation pointing at
  moved code.
* ``2`` — COULD NOT VERIFY: the gate COULD NOT do its job.

Exit 1 outranks exit 2 when both stand, because drift is the more
actionable signal — and every could-not-verify blocker is still printed
under the verdict, so nothing is masked. Everything the gate refuses on
is printed BEFORE the verdict, and every pass bought by the registry is
printed WITH its reason: a blessing nobody reads is a silent one.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from citation_baseline import (
    BASELINE_FILENAME,
    Baseline,
    BaselineEntry,
    CitationKey,
    Coverage,
    cover,
    ratchet,
)
from citation_doc import Citation, cited_range


@dataclass
class CheckResult:
    """Per-citation verdict.

    ``status`` is one of:

    * ``ok`` — resolved, and the cited line points at the symbol.
    * ``drift`` — resolved, and the cited line is wrong. Exit 1.
    * ``unverified`` — the source was read and indexed, but this
      citation could not be resolved mechanically. Exit 2 unless a
      ``citation-baseline.json`` entry covers it. NOT a pass on its own.
    * ``blocked`` — the cited source could not be read or parsed, so the
      gate never got to look. Always exit 2, and NEVER registrable: a
      registry able to bless a missing file would bless the gate's own
      blindness.
    """

    citation: Citation
    status: str  # "ok" | "drift" | "unverified" | "blocked"
    resolved_symbol: str | None = None
    expected_start: int | None = None
    expected_end: int | None = None
    detail: str = ""


@dataclass
class Graded:
    """What one run extracted and what it actually graded.

    Both counts are load-bearing: the verdict asserts they are equal and
    non-zero, so a gate that selected an empty set cannot report clean.
    """

    results: list[CheckResult]
    extracted: int


def citation_key(cite: Citation) -> CitationKey:
    """The registry identity of a citation: doc line, path, cited range."""
    return (cite.doc_line, cite.path, cite.start, cite.end)


def _write(text: str) -> None:
    sys.stderr.write(text)


def _report_notices(notices: list[str]) -> None:
    for line in notices:
        _write(f"\n{line}\n")


def _report_drift(drifts: list[CheckResult]) -> None:
    if not drifts:
        return
    _write(f"\nDRIFT: {len(drifts)} citation(s) point at moved symbols:\n")
    for r in drifts:
        _write(
            f"  doc line {r.citation.doc_line}: {cited_range(r.citation)}"
            f"  symbol={r.resolved_symbol!r} expected={r.expected_start}-{r.expected_end}\n"
            f"    {r.detail}\n"
        )


def _report_registered(
    covered: tuple[tuple[CitationKey, BaselineEntry], ...],
    by_key: dict[CitationKey, CheckResult],
) -> None:
    """Print every registry-bought pass with its reason. Loud, never silent."""
    if not covered:
        return
    _write(
        f"\n{len(covered)} unverifiable citation(s) are REGISTERED in "
        f"{BASELINE_FILENAME} and pass loudly:\n"
    )
    for key, entry in covered:
        _write(
            f"  {entry.label()}\n"
            f"    finding: {entry.finding}\n"
            f"    reason:  {entry.reason}\n"
            f"    gate saw: {by_key[key].detail}\n"
        )


def _report_unregistered(
    uncovered: tuple[CitationKey, ...],
    by_key: dict[CitationKey, CheckResult],
) -> None:
    if not uncovered:
        return
    _write(
        f"\n{len(uncovered)} citation(s) could not be mechanically verified and are NOT "
        f"registered in {BASELINE_FILENAME}:\n"
    )
    for key in uncovered:
        result = by_key[key]
        _write(
            f"  doc line {result.citation.doc_line}: {cited_range(result.citation)}\n"
            f"    {result.detail}\n"
        )


def _report_blocked(blocked: list[CheckResult]) -> None:
    if not blocked:
        return
    _write(f"\n{len(blocked)} citation(s) name source the gate could not read:\n")
    for r in blocked:
        _write(f"  doc line {r.citation.doc_line}: {cited_range(r.citation)}\n    {r.detail}\n")


def _vacuity_blockers(graded: Graded, doc: Path) -> list[str]:
    """The control rod on the gate itself: a graded set of zero is a failure."""
    if graded.extracted == 0:
        empty = (
            f"the gate GRADED NOTHING: 0 citations extracted from {doc}. A gate that grades an "
            "empty set reports clean having checked nothing, so an empty set is a failure, not "
            "a pass — check the doc path and the citation shape (src/bonfire/<file>.py:NN[-NN])."
        )
        return [empty]
    if len(graded.results) != graded.extracted:
        shortfall = (
            f"the gate graded {len(graded.results)} of the {graded.extracted} citations it "
            "extracted: every extracted citation must produce a verdict, so a shortfall means "
            "the grading loop dropped work."
        )
        return [shortfall]
    return []


def _blockers(
    graded: Graded,
    coverage: Coverage,
    blocked: list[CheckResult],
    ratchet_violations: list[str],
    doc: Path,
) -> list[str]:
    """Every reason the gate could not do its job, in exit-2 terms."""
    reasons = list(ratchet_violations)
    reasons.extend(
        f"unregistered unverifiable citation: doc line {key[0]}, src/bonfire/{key[1]}:"
        f"{key[2]}-{key[3]} — resolve it, or register it with a reason and bump frozen_count"
        for key in coverage.uncovered
    )
    reasons.extend(
        f"cited source the gate could not read: doc line {r.citation.doc_line} "
        f"({cited_range(r.citation)}) — {r.detail}"
        for r in blocked
    )
    reasons.extend(
        f"stale {BASELINE_FILENAME} entry: {entry.label()} matches no unverifiable citation — "
        "the citation moved or was repaired, so the blessing must be re-read or removed"
        for entry in coverage.stale
    )
    reasons.extend(_vacuity_blockers(graded, doc))
    return reasons


def _write_summary(
    graded: Graded,
    drifts: list[CheckResult],
    coverage: Coverage,
    blocked: list[CheckResult],
) -> None:
    ok_count = sum(1 for r in graded.results if r.status == "ok")
    checked = len(graded.results)
    _write(
        f"\nSummary: {ok_count} ok, {len(drifts)} drift, "
        f"{len(coverage.covered)} registered-unverifiable, "
        f"{len(coverage.uncovered)} unregistered-unverifiable, {len(blocked)} blocked, "
        f"checked={checked} of {graded.extracted} extracted.\n"
    )
    passed = checked > 0 and checked == graded.extracted
    _write(f"Non-vacuity: {'PASS' if passed else 'FAIL'} — checked={checked} (> 0 required).\n")


def _write_blockers(blockers: list[str]) -> None:
    for reason in blockers:
        _write(f"  - {reason}\n")


def _decide(drifts: list[CheckResult], blockers: list[str]) -> int:
    """Write the verdict block and return the exit code."""
    if drifts:
        _write(
            f"\nVerdict: exit 1 — DRIFT. The gate DID its job and found {len(drifts)} "
            "citation(s) pointing at moved code. Re-anchor them.\n"
        )
        if blockers:
            _write(
                f"  ({len(blockers)} could-not-verify blocker(s) also stand; exit 1 outranks "
                "exit 2 because drift is the more actionable signal:)\n"
            )
            _write_blockers(blockers)
        return 1
    if blockers:
        _write(
            "\nVerdict: exit 2 — COULD NOT VERIFY. This is NOT 'the gate did its job and "
            "found drift' (exit 1); it is 'the gate could not do its job':\n"
        )
        _write_blockers(blockers)
        return 2
    _write(
        "\nVerdict: exit 0 — every citation resolved or is registered, and the graded "
        "set is non-empty.\n"
    )
    return 0


def report(graded: Graded, baseline: Baseline, doc: Path) -> int:
    """Print the whole board, then decide once. Returns the exit code."""
    drifts = [r for r in graded.results if r.status == "drift"]
    unverified = [r for r in graded.results if r.status == "unverified"]
    blocked = [r for r in graded.results if r.status == "blocked"]
    by_key = {citation_key(r.citation): r for r in unverified}
    coverage = cover(list(by_key), baseline)
    ratchet_violations, ratchet_notices = ratchet(baseline)

    _report_notices(ratchet_notices)
    _report_drift(drifts)
    _report_registered(coverage.covered, by_key)
    _report_unregistered(coverage.uncovered, by_key)
    _report_blocked(blocked)
    _write_summary(graded, drifts, coverage, blocked)
    return _decide(drifts, _blockers(graded, coverage, blocked, ratchet_violations, doc))


def fail_to_run(message: str) -> int:
    """Report a structural inability to run and return the reserved code."""
    verdict = "\nVerdict: exit 2 — COULD NOT VERIFY. The gate could not do its job:\n"
    _write(f"{verdict}  - {message}\n")
    return 2
