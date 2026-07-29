# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI
"""What the SOURCE says: the AST symbol index the citation gate resolves against.

One of four modules behind ``check_protocol_doc_citations.py`` (see
``citation_doc`` for the split). This one answers a single question:
"what symbol, if any, lives at line N of this file, and what are its
nearest neighbours?". The driver keeps the resolution rules and the CLI.

Every failure here is a typed :class:`SourceIndexError`. A cited source
file that cannot be read or parsed means the gate COULD NOT DO ITS JOB
(the driver turns that into exit 2), never a silently skipped citation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


class SourceIndexError(Exception):
    """A cited source file could not be read or parsed.

    Typed rather than a bare raise so the driver can tell "this citation
    is unverifiable" apart from "this gate crashed".
    """


@dataclass
class SymbolIndex:
    """Top-level + nested symbols extracted from a source file via ``ast``."""

    # name -> (start_line, end_line). Includes both top-level and
    # dotted ``Class.method`` entries so the doc's
    # ``ConversationEngine.start`` shape resolves naturally.
    by_name: dict[str, tuple[int, int]] = field(default_factory=dict)

    # Flat ordered list of (start_line, end_line, name) for the
    # containment pass. Ordered by widening span so the FIRST match
    # while iterating gives the tightest enclosing symbol.
    intervals: list[tuple[int, int, str]] = field(default_factory=list)


def index_symbols(source_path: Path) -> SymbolIndex:  # noqa: C901
    """Return name -> line-range map for every def/class in *source_path*.

    Top-level functions/classes are keyed by their bare name. Methods
    are also keyed dotted (``Class.method``). Module-level assignments
    to ``UPPER_CASE`` or ``_underscore`` names (``_SERVER_TYPES``,
    ``MAX_USER_MESSAGE_LEN``, etc.) are indexed too — the doc cites
    those tables/constants by name and we want to detect when they
    move.

    Raises :class:`SourceIndexError` when the file cannot be read or
    parsed. A gate that cannot read the code it grades has not passed.
    """
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceIndexError(f"cannot read cited source {source_path}: {exc}") from exc
    try:
        tree = ast.parse(text, filename=str(source_path))
    except (SyntaxError, ValueError) as exc:
        raise SourceIndexError(f"cannot parse cited source {source_path}: {exc}") from exc
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


def innermost_containing(index: SymbolIndex, lineno: int) -> tuple[int, int, str] | None:
    """Return the smallest indexed (start, end, name) that contains ``lineno``."""
    for start, end, name in index.intervals:
        if start <= lineno <= end:
            return (start, end, name)
    return None


def _describe(interval: tuple[int, int, str] | None, empty: str) -> str:
    """Render one neighbour as ``name (lines A-B)``, or *empty* when absent."""
    if interval is None:
        return empty
    start, end, name = interval
    return f"{name} (lines {start}-{end})"


def neighbours(index: SymbolIndex, lineno: int) -> tuple[str, str]:
    """Describe the nearest indexed symbol above and below *lineno*.

    This is the actionable half of an "unverified" report: knowing that
    the cited line sits in the gap between ``UserMessage`` and
    ``_SERVER_TYPES`` is what lets a human see, in one read, which
    symbol the doc probably meant and which one it actually points near.
    """
    above = max(
        (iv for iv in index.intervals if iv[1] < lineno),
        key=lambda iv: iv[1],
        default=None,
    )
    below = min(
        (iv for iv in index.intervals if iv[0] > lineno),
        key=lambda iv: iv[0],
        default=None,
    )
    return (
        _describe(above, "nothing indexed above it"),
        _describe(below, "nothing indexed below it"),
    )
