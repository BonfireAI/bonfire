# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

r"""What the DOC says: the citation record, and how citations are read out of it.

One of four modules behind ``check_protocol_doc_citations.py``, split by
question rather than by size (the gate outgrew the 500-line file cap when
it acquired an honest three-valued exit contract):

* this module — the doc side: what a citation IS, and what the doc says
  near one;
* ``citation_source`` — the source side: what symbol lives at line N;
* ``citation_baseline`` — the registry of reasoned, ratcheted blessings;
* ``citation_report`` — the verdict record, the report, the exit code.

The gate script itself keeps the resolution rules and the CLI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches ``src/bonfire/<anything>.py:NN`` or ``.py:NN-NN`` inside a
# markdown backtick span. We accept either an opening ``\``` directly
# before the path or surrounding text — the doc uses both shapes.
CITATION_RE = re.compile(
    r"src/bonfire/(?P<path>[A-Za-z0-9_/]+\.py):(?P<start>\d+)(?:-(?P<end>\d+))?"
)

# Matches an inline-code Python identifier. Used to find a symbol hint
# in the 5 lines preceding a citation. We capture dotted names
# (``ConversationEngine.start``) so we can resolve method-on-class
# citations as well as bare ``parse_server_message`` shapes.
IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`")

# How many lines of doc context to scan backwards from a citation for
# a symbol hint. The doc's pattern is "**Source (model)**:
# `src/.../protocol.py:NN-NN`." with the symbol named within the
# preceding paragraph; 5 lines is enough for the longest case
# (multi-line bullet) but tight enough that we don't capture an
# unrelated symbol two paragraphs up.
CONTEXT_BACK_LINES = 5

# Identifiers that are doc-shorthand for line ranges we do NOT want
# to resolve mechanically — protocol modules expose them but they're
# referenced for context rather than as load-bearing pointers, and a
# false "drift" alert would be more noise than signal.
#
# MEASURED SCAR: when EVERY hint in a citation's context window is on
# this list AND the cited line sits at module level, both resolution
# passes come up empty and the citation lands in ``unverified``. While
# ``unverified`` exited 0, that combination laundered real drift into a
# free pass — it is how two genuinely wrong citations sat unnoticed in
# the shipped doc. It cannot any more (the gate exits 2), and every
# rejection is now reported with this table named, so a citation in that
# position is legible instead of merely dismissed.
SKIP_HINTS = frozenset(
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

# Backticked spans that name a module, not a symbol: nothing to resolve.
MODULE_SHORTHANDS = frozenset({"flow.py", "server.py", "protocol.py", "scan.py", "ui.html"})

# Why a candidate hint was thrown away. Reported verbatim, with the
# table named, because "no symbol hint resolvable" is not actionable.
SKIP_HINTS_REASON = "listed in citation_doc.SKIP_HINTS"
SHORTHAND_REASON = "a module filename, not a symbol"


@dataclass
class Citation:
    """One ``src/bonfire/...py:NN-NN`` reference in the doc."""

    doc_line: int  # 1-based line number in the doc
    path: str  # e.g. "onboard/protocol.py"
    start: int  # cited start line
    end: int  # cited end line (= start when single-line)


@dataclass(frozen=True)
class HintProbe:
    """What the hint pass found in the doc lines before a citation.

    ``rejected`` carries ``(identifier, why)`` for every backticked
    candidate the pass threw away. Reporting it is the difference
    between "no symbol hint resolvable" and "the three hints in range
    are all in SKIP_HINTS" — only the second can be acted on.
    """

    symbol: str | None = None
    rejected: tuple[tuple[str, str], ...] = ()


def extract_citations(doc_text: str) -> list[Citation]:
    """Return one ``Citation`` per ``src/bonfire/...py:NN[-NN]`` match."""
    citations: list[Citation] = []
    for doc_line_idx, line in enumerate(doc_text.splitlines(), start=1):
        for match in CITATION_RE.finditer(line):
            end_raw = match.group("end")
            start = int(match.group("start"))
            citations.append(
                Citation(
                    doc_line=doc_line_idx,
                    path=match.group("path"),
                    start=start,
                    end=int(end_raw) if end_raw is not None else start,
                )
            )
    return citations


def hint_for_citation(doc_lines: list[str], cite: Citation) -> HintProbe:
    """Walk back up to ``CONTEXT_BACK_LINES`` looking for a backticked symbol."""
    # doc_lines is 0-indexed; cite.doc_line is 1-based.
    end_idx = cite.doc_line - 1
    start_idx = max(0, end_idx - CONTEXT_BACK_LINES)
    rejected: list[tuple[str, str]] = []
    # Walk back from the citation's own line first so an "on the same
    # line" hint wins ("``parse_server_message``: ``src/...:NN-NN``").
    for idx in range(end_idx, start_idx - 1, -1):
        for hit in IDENT_RE.findall(doc_lines[idx]):
            if hit.split(".", 1)[0].lower() in SKIP_HINTS:
                rejected.append((hit, SKIP_HINTS_REASON))
            elif hit in MODULE_SHORTHANDS:
                rejected.append((hit, SHORTHAND_REASON))
            else:
                return HintProbe(symbol=hit, rejected=tuple(rejected))
    return HintProbe(symbol=None, rejected=tuple(rejected))


def cited_range(cite: Citation) -> str:
    """``src/bonfire/<path>:NN`` or ``:NN-NN``, as the doc wrote it."""
    span = f"{cite.start}-{cite.end}" if cite.end != cite.start else str(cite.start)
    return f"src/bonfire/{cite.path}:{span}"
