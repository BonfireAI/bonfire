#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI
r"""Verify ``docs/scan-front-door-protocol.md`` source citations stay anchored.

The Front Door protocol doc cites ~70 ``src/bonfire/...py:NN[-NN]``
line ranges. After any wave of insert-heavy edits in the cited
modules (Wave 4 trust-triangle, Wave 9 Lane B oversize handling,
Wave 10 vault_seed symlink hardening, …) the line numbers drift
silently — the body still reads sensibly, but anyone clicking
through to verify lands in unrelated code. The CHANGELOG advertised
this doc as the authoritative third-party-client contract, so the
citations are part of the contract surface, not just decoration.

This script:

* Reads ``docs/scan-front-door-protocol.md``.
* Extracts every ``src/bonfire/.../<file>.py:NN`` and
  ``src/bonfire/.../<file>.py:NN-NN`` citation (Python files only;
  ``ui.html`` citations are skipped because they have no AST).
* Resolves each citation against the source AST in two passes:
  1. **Containment pass.** Find the innermost class/function/
     module-level assignment that *contains* the cited start line.
     A citation that lands inside ``FrontDoorServer._ws_handler``'s
     body is OK regardless of whether the surrounding doc text
     names ``_ws_handler``, because the line still points at code
     inside that symbol.
  2. **Hint pass (fallback).** If the cited line is in module
     top-level whitespace/imports, walks the doc up to 5 lines back
     looking for a backticked Python identifier
     (``\`ConversationEngine.start\```, ``\`_SERVER_TYPES\```)
     and asserts the symbol's actual start line is within
     ``--tolerance`` of the cited start.
* Fails (exit 1) with one line per drifted citation.

The check is intentionally conservative: citations whose symbol
cannot be matched mechanically AND don't land in any indexed body
are reported as ``unverified`` on stderr and do NOT fail the run.
The script's job is to catch silent drift on the citations we CAN
mechanise, not to gate the whole doc on perfect machine-readability.

Usage::

    python scripts/check_protocol_doc_citations.py
    python scripts/check_protocol_doc_citations.py --json
    python scripts/check_protocol_doc_citations.py --tolerance 0

Exits 0 when every verifiable citation resolves; 1 on any drift.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Repo root is the parent of this script's parent (``scripts/``).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "scan-front-door-protocol.md"

# Matches ``src/bonfire/<anything>.py:NN`` or ``.py:NN-NN`` inside a
# markdown backtick span. We accept either an opening ``\``` directly
# before the path or surrounding text — the doc uses both shapes.
_CITATION_RE = re.compile(
    r"src/bonfire/(?P<path>[A-Za-z0-9_/]+\.py):(?P<start>\d+)(?:-(?P<end>\d+))?"
)

# Matches an inline-code Python identifier. Used to find a symbol hint
# in the 5 lines preceding a citation. We capture dotted names
# (``ConversationEngine.start``) so we can resolve method-on-class
# citations as well as bare ``parse_server_message`` shapes.
_IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`")

# How many lines of doc context to scan backwards from a citation for
# a symbol hint. The doc's pattern is "**Source (model)**:
# `src/.../protocol.py:NN-NN`." with the symbol named within the
# preceding paragraph; 5 lines is enough for the longest case
# (multi-line bullet) but tight enough that we don't capture an
# unrelated symbol two paragraphs up.
_CONTEXT_BACK_LINES = 5

# Tolerance window (lines) for "cited start line is close to the
# symbol's start line". Wave-to-wave inserts of 1-2 lines inside a
# function are common; treating those as drift would produce noise.
# A function-internal citation passes when the cited line falls
# anywhere inside the function body (handled separately below); the
# tolerance only applies when the cited line is meant to point AT the
# symbol's def/class line.
_DEFAULT_TOLERANCE = 3

# Identifiers that are doc-shorthand for line ranges we do NOT want
# to resolve mechanically — protocol modules expose them but they're
# referenced for context rather than as load-bearing pointers, and a
# false "drift" alert would be more noise than signal.
_SKIP_HINTS = frozenset(
    {
        # Generic terms that match many things or are doc verbs
        "true",
        "false",
        "none",
        "type",
        "yes",
        "no",
        # Doc section-anchor backticks that aren't Python symbols
        "narration",
        "question",
        "reflection",
        "scan_start",
        "scan_update",
        "scan_complete",
        "all_scans_complete",
        "conversation_start",
        "falcor_message",
        "config_generated",
        "user_message",
        "server_error",
    }
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Citation:
    """One ``src/bonfire/...py:NN-NN`` reference in the doc."""

    doc_line: int  # 1-based line number in the doc
    path: str  # e.g. "onboard/protocol.py"
    start: int  # cited start line
    end: int  # cited end line (= start when single-line)


@dataclass
class SymbolIndex:
    """Top-level + nested symbols extracted from a source file via ``ast``."""

    # name -> (start_line, end_line). Includes both top-level and
    # dotted ``Class.method`` entries so the doc's
    # ``ConversationEngine.start`` shape resolves naturally.
    by_name: dict[str, tuple[int, int]] = field(default_factory=dict)

    # Flat ordered list of (start_line, end_line, name) for the
    # containment pass. Ordered by widening end-line so the FIRST
    # match while iterating innermost-out gives the tightest
    # enclosing symbol.
    intervals: list[tuple[int, int, str]] = field(default_factory=list)


@dataclass
class CheckResult:
    """Per-citation verdict."""

    citation: Citation
    status: str  # "ok" | "drift" | "unverified"
    resolved_symbol: str | None = None
    expected_start: int | None = None
    expected_end: int | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# Source-file symbol indexing
# ---------------------------------------------------------------------------


def _index_symbols(source_path: Path) -> SymbolIndex:
    """Return name -> line-range map for every def/class in *source_path*.

    Top-level functions/classes are keyed by their bare name. Methods
    are also keyed dotted (``Class.method``). Module-level assignments
    to ``UPPER_CASE`` or ``_underscore`` names (``_SERVER_TYPES``,
    ``MAX_USER_MESSAGE_LEN``, etc.) are indexed too — the doc cites
    those tables/constants by name and we want to detect when they
    move.
    """
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))
    index = SymbolIndex()

    def _add(name: str, lineno: int, end_lineno: int | None) -> None:
        if end_lineno is None:
            end_lineno = lineno
        # First-write-wins so a re-bound name doesn't clobber the
        # earlier (and usually authoritative) definition.
        index.by_name.setdefault(name, (lineno, end_lineno))
        index.intervals.append((lineno, end_lineno, name))

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            _add(node.name, node.lineno, node.end_lineno)
        elif isinstance(node, ast.ClassDef):
            _add(node.name, node.lineno, node.end_lineno)
            # Walk class body for methods.
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    _add(child.name, child.lineno, child.end_lineno)
                    _add(f"{node.name}.{child.name}", child.lineno, child.end_lineno)
        elif isinstance(node, ast.Assign):
            # Module-level constants / tables.
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _add(target.id, node.lineno, node.end_lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            _add(node.target.id, node.lineno, node.end_lineno)

    # Sort intervals so the tightest (smallest span) enclosing range
    # comes first when we filter by ``start <= cited <= end``.
    index.intervals.sort(key=lambda triple: triple[1] - triple[0])
    return index


def _innermost_containing(index: SymbolIndex, lineno: int) -> tuple[int, int, str] | None:
    """Return the smallest indexed (start, end, name) that contains ``lineno``."""
    for start, end, name in index.intervals:
        if start <= lineno <= end:
            return (start, end, name)
    return None


# ---------------------------------------------------------------------------
# Doc parsing
# ---------------------------------------------------------------------------


def _extract_citations(doc_text: str) -> list[Citation]:
    """Return one ``Citation`` per ``src/bonfire/...py:NN[-NN]`` match."""
    citations: list[Citation] = []
    for doc_line_idx, line in enumerate(doc_text.splitlines(), start=1):
        for match in _CITATION_RE.finditer(line):
            path = match.group("path")
            start = int(match.group("start"))
            end_raw = match.group("end")
            end = int(end_raw) if end_raw is not None else start
            citations.append(Citation(doc_line=doc_line_idx, path=path, start=start, end=end))
    return citations


def _hint_for_citation(doc_lines: list[str], cite: Citation) -> str | None:
    """Walk back up to ``_CONTEXT_BACK_LINES`` looking for a backticked symbol."""
    # doc_lines is 0-indexed; cite.doc_line is 1-based.
    end_idx = cite.doc_line - 1
    start_idx = max(0, end_idx - _CONTEXT_BACK_LINES)
    # Walk back from the citation's own line first so an "on the same
    # line" hint wins ("``parse_server_message``: ``src/...:NN-NN``").
    for idx in range(end_idx, start_idx - 1, -1):
        line = doc_lines[idx]
        for hit in _IDENT_RE.findall(line):
            head = hit.split(".", 1)[0]
            if head.lower() in _SKIP_HINTS:
                continue
            # Skip pure module shorthands that aren't symbols.
            if hit in {"flow.py", "server.py", "protocol.py", "scan.py", "ui.html"}:
                continue
            return hit
    return None


# ---------------------------------------------------------------------------
# Check logic
# ---------------------------------------------------------------------------


def _check_citation(
    cite: Citation,
    *,
    hint: str | None,
    index: SymbolIndex,
    tolerance: int,
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
    containing = _innermost_containing(index, cite.start)
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
                expected = index.by_name[tail]
                return _verdict(cite, hint, expected, tolerance)
        return CheckResult(
            citation=cite,
            status="unverified",
            detail=(
                f"cited line {cite.start} not inside any indexed symbol "
                f"and no symbol hint resolvable (hint={hint!r})"
            ),
        )

    expected = index.by_name[hint]
    return _verdict(cite, hint, expected, tolerance)


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


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    doc_text = args.doc.read_text(encoding="utf-8")
    doc_lines = doc_text.splitlines()
    citations = _extract_citations(doc_text)

    # Cache: src-path-string -> SymbolIndex.
    indices: dict[str, SymbolIndex] = {}

    results: list[CheckResult] = []
    for cite in citations:
        if cite.path not in indices:
            source_file = _REPO_ROOT / "src" / "bonfire" / cite.path
            if not source_file.is_file():
                results.append(
                    CheckResult(
                        citation=cite,
                        status="unverified",
                        detail=f"source not found: {source_file}",
                    )
                )
                continue
            indices[cite.path] = _index_symbols(source_file)
        hint = _hint_for_citation(doc_lines, cite)
        results.append(
            _check_citation(
                cite,
                hint=hint,
                index=indices[cite.path],
                tolerance=args.tolerance,
            )
        )

    drifts = [r for r in results if r.status == "drift"]
    unverified = [r for r in results if r.status == "unverified"]

    if args.json:
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

    # Human report.
    if drifts:
        sys.stderr.write(f"\nDRIFT: {len(drifts)} citation(s) point at moved symbols:\n")
        for r in drifts:
            sys.stderr.write(
                f"  doc line {r.citation.doc_line}: "
                f"src/bonfire/{r.citation.path}:{r.citation.start}"
                f"{'-' + str(r.citation.end) if r.citation.end != r.citation.start else ''}"
                f"  symbol={r.resolved_symbol!r} "
                f"expected={r.expected_start}-{r.expected_end}\n"
                f"    {r.detail}\n"
            )
    if unverified:
        sys.stderr.write(
            f"\n{len(unverified)} citation(s) could not be mechanically verified "
            "(no symbol hint in surrounding context — review manually):\n"
        )
        for r in unverified:
            sys.stderr.write(
                f"  doc line {r.citation.doc_line}: "
                f"src/bonfire/{r.citation.path}:{r.citation.start} "
                f"({r.detail})\n"
            )

    ok_count = sum(1 for r in results if r.status == "ok")
    sys.stderr.write(
        f"\nSummary: {ok_count} ok, {len(drifts)} drift, {len(unverified)} unverified, "
        f"{len(results)} total citations checked.\n"
    )

    return 1 if drifts else 0


if __name__ == "__main__":
    raise SystemExit(main())
