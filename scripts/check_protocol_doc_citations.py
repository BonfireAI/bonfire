#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI
r"""Verify ``docs/scan-front-door-protocol.md`` source citations stay anchored.

The Front Door protocol doc cites ~60 ``src/bonfire/...py:NN[-NN]``
line ranges. After any wave of insert-heavy edits in the cited
modules (Wave 4 trust-triangle, Wave 9 Lane B oversize handling,
Wave 10 vault_seed symlink hardening, …) the line numbers drift
silently — the body still reads sensibly, but anyone clicking
through to verify lands in unrelated code. The CHANGELOG advertised
this doc as the authoritative third-party-client contract, so the
citations are part of the contract surface, not just decoration.

This script reads the doc, extracts every ``src/bonfire/.../<file>.py``
citation (Python only; ``ui.html`` citations have no AST) and resolves
each one against the source AST in two passes:

1. **Containment pass.** Find the innermost class/function/module-level
   assignment that *contains* the cited start line. A citation landing
   inside ``FrontDoorServer._ws_handler``'s body is OK whether or not the
   surrounding doc text names ``_ws_handler`` — the line still points at
   code inside that symbol.
2. **Hint pass (fallback).** If the cited line is at module level
   (imports, blank lines, banner comments), walk the doc up to 5 lines
   back for a backticked Python identifier (``\`ConversationEngine.start\```,
   ``\`_SERVER_TYPES\```) and assert the symbol's actual start line is
   within ``--tolerance`` of the cited start.

The honest exit contract
------------------------

====  =====================================================================
Exit  Meaning
====  =====================================================================
0     Clean. Every citation resolved (or is registered in
      ``citation-baseline.json``) AND the run graded a NON-EMPTY set.
1     DRIFT. The gate DID its job: a citation resolved to a symbol and the
      cited line is wrong. Re-anchor it.
2     COULD NOT VERIFY. The gate COULD NOT do its job: a citation it cannot
      mechanically resolve and that no registry entry covers, a cited
      source file absent or unparseable, an unreadable doc, a malformed or
      over-ratchet registry, a stale registry entry, or a run that graded
      ZERO citations.
====  =====================================================================

Exit 1 outranks exit 2 when both stand; every could-not-verify blocker is
still printed under the verdict, so nothing is masked.

This REPLACES the fail-open behaviour the script shipped with, which
reported unresolvable citations as ``unverified`` on stderr and returned 0
anyway. That made the gate MOST permissive exactly where its own
confidence was LOWEST, and the run that measured it found BOTH of its
``unverified`` citations were real drift, laundered into a category
structurally incapable of failing. ``unverified`` is no longer a pass.

To land the strict gate ahead of the doc repair it demands, each
known-unverifiable citation is named — one at a time, with a written
finding and a written reason, under a ratchet — in
``citation-baseline.json`` (see ``scripts/citation_baseline.py``). The
registry covers the ``unverified`` bucket ONLY; it can never launder a
``drift``, and it can never cover a source file the gate could not read.

Collaborators: ``citation_doc`` (the doc side), ``citation_source`` (the
source side), ``citation_baseline`` (the registry), ``citation_report``
(the verdict, the report and the exit code). This file owns the
resolution rules and the CLI.

Usage::

    python scripts/check_protocol_doc_citations.py
    python scripts/check_protocol_doc_citations.py --json
    python scripts/check_protocol_doc_citations.py --tolerance 0

``--doc``, ``--source-root`` and ``--baseline`` exist so the control rods
can point the whole gate at a fixture tree. They relocate WHAT is graded;
none of them can switch a verdict off.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ``scripts/`` is not a package, so the collaborator modules are imported
# by bare name. The interpreter already seeds ``sys.path[0]`` with this
# directory when the script runs as ``python scripts/<this>.py``; the
# insert is what makes the imports work when a test loads this file by
# path (``importlib.util.spec_from_file_location``) from another cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_baseline import BASELINE_FILENAME, CitationBaselineError, load_baseline
from citation_doc import (
    CONTEXT_BACK_LINES,
    Citation,
    HintProbe,
    extract_citations,
    hint_for_citation,
)
from citation_report import CheckResult, Graded, fail_to_run, report
from citation_source import (
    SourceIndexError,
    SymbolIndex,
    index_symbols,
    innermost_containing,
    neighbours,
)

# Repo root is the parent of this script's parent (``scripts/``).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "scan-front-door-protocol.md"
_SOURCE_ROOT = _REPO_ROOT / "src" / "bonfire"
_BASELINE_PATH = _REPO_ROOT / BASELINE_FILENAME

# Tolerance window (lines) for "cited start line is close to the
# symbol's start line". Wave-to-wave inserts of 1-2 lines inside a
# function are common; treating those as drift would produce noise.
# A function-internal citation passes when the cited line falls
# anywhere inside the function body (handled separately below); the
# tolerance only applies when the cited line is meant to point AT the
# symbol's def/class line.
_DEFAULT_TOLERANCE = 3


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _rejected_hints_text(probe: HintProbe | None) -> str:
    """Say what the hint pass found and threw away, or that it found nothing."""
    rejected = probe.rejected if probe is not None else ()
    if not rejected:
        return (
            f"no backticked identifier found in the {CONTEXT_BACK_LINES} doc lines "
            "before the citation"
        )
    shown = ", ".join(f"`{ident}` ({why})" for ident, why in rejected)
    return f"doc hints found and rejected: {shown}"


def _unverified_detail(
    cite: Citation,
    index: SymbolIndex,
    hint: str | None,
    probe: HintProbe | None,
) -> str:
    """Say what the cited line actually IS, so a human can act on it."""
    above, below = neighbours(index, cite.start)
    parts = [
        f"cited line {cite.start} is not inside any indexed symbol",
        f"nearest symbol above: {above}",
        f"nearest symbol below: {below}",
    ]
    if hint is None:
        parts.append(_rejected_hints_text(probe))
    else:
        parts.append(f"doc hint `{hint}` is not an indexed symbol in src/bonfire/{cite.path}")
    parts.append(
        "FIX: re-point the citation at the symbol the doc names, or name that symbol in "
        "backticks within the preceding doc lines so the hint pass can resolve it"
    )
    return "; ".join(parts)


def _check_citation(
    cite: Citation,
    *,
    hint: str | None,
    index: SymbolIndex,
    tolerance: int,
    probe: HintProbe | None = None,
) -> CheckResult:
    """Return the verdict for a single citation.

    Containment-first: if the cited start line is inside any indexed
    class/function/assignment, the citation is OK and the containing
    symbol is reported as the resolved name. The hint heuristic is
    only used as a tie-breaker / cross-check when containment alone
    cannot decide (e.g. citation points at top-level whitespace) OR
    when the doc hint names a specific symbol AND that symbol exists
    AND the citation's start line is NOT inside that symbol (drift).
    """
    containing = innermost_containing(index, cite.start)
    if containing is not None:
        c_start, c_end, c_name = containing
        # Containment wins. The hint heuristic is too loose (it walks
        # back several lines, often into the *previous* bullet) to
        # safely override a positive containment match. If the doc
        # text near the citation names a different symbol, the human
        # reader will see the discrepancy when reading the doc, but
        # mechanically the citation still resolves to real code.
        return CheckResult(
            citation=cite,
            status="ok",
            resolved_symbol=c_name,
            expected_start=c_start,
            expected_end=c_end,
            detail=(
                f"resolved via containment (nearest doc-hint was {hint!r})"
                if hint
                else "resolved via containment"
            ),
        )

    # Cited line is NOT inside any indexed symbol — fall back to the
    # hint heuristic. Used for module-level top-of-file citations
    # (imports, blank lines, docstring spans).
    if hint is None or hint not in index.by_name:
        if hint and "." in hint:
            tail = hint.rsplit(".", 1)[1]
            if tail in index.by_name:
                return _verdict(cite, hint, index.by_name[tail], tolerance)
        return CheckResult(
            citation=cite,
            status="unverified",
            detail=_unverified_detail(cite, index, hint, probe),
        )

    return _verdict(cite, hint, index.by_name[hint], tolerance)


def _verdict(
    cite: Citation,
    symbol: str,
    expected: tuple[int, int],
    tolerance: int,
) -> CheckResult:
    """Compare a single citation against the symbol's actual range."""
    exp_start, exp_end = expected

    # Case A: citation is meant to point AT the symbol's def line
    # (single-line citation OR multi-line citation whose start line
    # matches the def within ``tolerance``).
    start_diff = abs(cite.start - exp_start)
    if start_diff <= tolerance:
        return CheckResult(
            citation=cite,
            status="ok",
            resolved_symbol=symbol,
            expected_start=exp_start,
            expected_end=exp_end,
        )

    # Case B: citation points inside the symbol's body (an emit site
    # within a function, e.g. ``flow.py:175`` inside ``scan_emit``).
    # That's fine — the cited line lives in the symbol.
    if exp_start <= cite.start <= exp_end:
        return CheckResult(
            citation=cite,
            status="ok",
            resolved_symbol=symbol,
            expected_start=exp_start,
            expected_end=exp_end,
            detail="cited line inside symbol body",
        )

    return CheckResult(
        citation=cite,
        status="drift",
        resolved_symbol=symbol,
        expected_start=exp_start,
        expected_end=exp_end,
        detail=(
            f"cited start={cite.start} differs from symbol "
            f"start={exp_start} by {start_diff} lines (and is "
            f"outside body {exp_start}-{exp_end})"
        ),
    )


def _grade(doc_text: str, source_root: Path, tolerance: int) -> Graded:
    """Grade every citation in *doc_text* against *source_root*.

    A source file that cannot be read or parsed blocks only its own
    citations; the rest of the doc is still graded, so one missing
    module cannot shrink the report to nothing without saying so.
    """
    doc_lines = doc_text.splitlines()
    citations = extract_citations(doc_text)
    indices: dict[str, SymbolIndex] = {}
    blocked: dict[str, str] = {}
    results: list[CheckResult] = []
    for cite in citations:
        if cite.path not in indices and cite.path not in blocked:
            try:
                indices[cite.path] = index_symbols(source_root / cite.path)
            except SourceIndexError as exc:
                blocked[cite.path] = str(exc)
        if cite.path in blocked:
            results.append(CheckResult(citation=cite, status="blocked", detail=blocked[cite.path]))
            continue
        probe = hint_for_citation(doc_lines, cite)
        results.append(
            _check_citation(
                cite,
                hint=probe.symbol,
                index=indices[cite.path],
                tolerance=tolerance,
                probe=probe,
            )
        )
    return Graded(results=results, extracted=len(citations))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _emit_json(results: list[CheckResult]) -> None:
    payload = [
        {
            "status": r.status,
            "doc_line": r.citation.doc_line,
            "path": r.citation.path,
            "cited_start": r.citation.start,
            "cited_end": r.citation.end,
            "symbol": r.resolved_symbol,
            "expected_start": r.expected_start,
            "expected_end": r.expected_end,
            "detail": r.detail,
        }
        for r in results
    ]
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tolerance",
        type=int,
        default=_DEFAULT_TOLERANCE,
        help="Allowed |cited_start - symbol_start| in lines (default: 3).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout in addition to the text report.",
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=_DOC_PATH,
        help="Path to the protocol doc (default: docs/scan-front-door-protocol.md).",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=_SOURCE_ROOT,
        help="Root the citations' paths resolve against (default: src/bonfire).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=_BASELINE_PATH,
        help=f"Registry of reasoned unverifiable citations (default: {BASELINE_FILENAME}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        doc_text = args.doc.read_text(encoding="utf-8")
    except OSError as exc:
        return fail_to_run(f"cannot read the doc under test: {exc}")
    try:
        baseline = load_baseline(args.baseline)
    except CitationBaselineError as exc:
        return fail_to_run(f"{BASELINE_FILENAME} is unusable: {exc}")
    graded = _grade(doc_text, args.source_root, args.tolerance)
    if args.json:
        _emit_json(graded.results)
    return report(graded, baseline, args.doc)


if __name__ == "__main__":
    raise SystemExit(main())
