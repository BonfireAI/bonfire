# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI
"""The reasoned, ratcheted registry of citations the drift gate cannot mechanise.

``check_protocol_doc_citations.py`` exits 2 when a citation cannot be
mechanically resolved: "unverified" is not a pass, because the run that
measured this gate found that BOTH of its unverified citations were real
drift, laundered into a category that could not fail. Making unverified
fail closes that hole and immediately raises the landing problem: the
two known-bad citations would hold the gate off ``main`` forever, and
repairing the doc's prose is owned by the doc, not by the gate.

This module is the answer, modelled on the shared quality kit's
``exemptions.json``: a registry at ``citation-baseline.json`` where each
unverifiable citation is named, one at a time, with a written reason and
a written finding, under a ratchet.

Shape::

    {"frozen_count": 2, "entries": [{
        "doc_line": 179,          # 1-based line of the citation IN THE DOC
        "path": "onboard/protocol.py",   # exactly one file, never a glob
        "cited_start": 107,       # the cited range, verbatim
        "cited_end": 110,
        "finding": "what is actually wrong, in repair terms",
        "reason": "why it is registered instead of fixed here"
    }]}

Rules, all enforced here and reported loudly by the driver on EVERY run:

1. **Exact keys.** All six, no others. A key this gate does not read
   cannot carry a claim; a missing key means the entry cannot be tied to
   one citation.
2. **One citation per entry.** The identity is
   ``(doc_line, path, cited_start, cited_end)`` — no globs, no
   wildcards, no file-level blessings. Move the citation, widen its
   range, or move the doc paragraph and the entry stops matching.
3. **The ratchet.** Entries may be removed freely. Adding one requires
   bumping ``frozen_count`` in the same commit, so growth is a visible
   decision. ``frozen_count`` above the live count is printed as slack
   that may shrink.
4. **Stale entries are violations.** An entry matching no unverified
   citation is a registry grading less than it thinks it is; see
   :func:`cover`.
5. **The registry never covers drift.** It is consulted for the
   ``unverified`` bucket only. The driver decides drift before it opens
   this file, and drift exits 1 whatever is written here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

BASELINE_FILENAME = "citation-baseline.json"

# The identity of one citation: doc line, source path, cited range.
# A tuple rather than a shared class so this module stays independent of
# the driver's record types (no import cycle, and the registry can be
# unit-tested without the gate).
CitationKey = tuple[int, str, int, int]

_INT_KEYS = ("doc_line", "cited_start", "cited_end")
_TEXT_KEYS = ("path", "finding", "reason")
_REQUIRED_KEYS = frozenset(_INT_KEYS + _TEXT_KEYS)


class CitationBaselineError(Exception):
    """The registry itself is unreadable or malformed.

    Typed so the driver reports "the gate could not do its job" (exit 2)
    rather than crashing with a traceback or, worse, treating an
    unparseable registry as an empty one.
    """


@dataclass(frozen=True)
class BaselineEntry:
    """One registered citation: which one, what is wrong, why it is here."""

    doc_line: int
    path: str
    cited_start: int
    cited_end: int
    finding: str
    reason: str

    @property
    def key(self) -> CitationKey:
        """The exact citation this entry covers, and no other."""
        return (self.doc_line, self.path, self.cited_start, self.cited_end)

    def label(self) -> str:
        """Human-facing one-liner naming the covered citation."""
        return (
            f"doc line {self.doc_line}: src/bonfire/{self.path}:{self.cited_start}-{self.cited_end}"
        )


@dataclass(frozen=True)
class Baseline:
    """The committed registry: the live entries plus the ratchet number."""

    frozen_count: int
    entries: tuple[BaselineEntry, ...]
    source: Path


@dataclass(frozen=True)
class Coverage:
    """Which unverified citations the registry covers, and what went stale."""

    covered: tuple[tuple[CitationKey, BaselineEntry], ...]
    uncovered: tuple[CitationKey, ...]
    stale: tuple[BaselineEntry, ...]


def _require_keys(raw: dict[str, object], where: str) -> None:
    keys = set(raw)
    if keys == _REQUIRED_KEYS:
        return
    missing = sorted(_REQUIRED_KEYS - keys)
    unknown = sorted(keys - _REQUIRED_KEYS)
    raise CitationBaselineError(
        f"{where} must carry exactly {sorted(_REQUIRED_KEYS)} "
        f"(missing={missing}, unknown={unknown}): a key this gate does not read "
        "cannot carry a claim, and a missing key means the entry cannot be "
        "tied to one citation"
    )


def _require_line_numbers(raw: dict[str, object], where: str) -> None:
    for key in _INT_KEYS:
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise CitationBaselineError(
                f"{where}.{key} must be a positive line number, got {value!r}"
            )


def _require_prose(raw: dict[str, object], where: str) -> None:
    for key in _TEXT_KEYS:
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            raise CitationBaselineError(
                f"{where}.{key} must be a non-empty string, got {value!r} "
                "(a blank key carries no claim, and an entry without a written "
                "finding and reason is a silent suppression)"
            )


def _entry_from(raw: object, position: int) -> BaselineEntry:
    """Validate one raw registry row into a :class:`BaselineEntry`."""
    where = f"entries[{position}]"
    if not isinstance(raw, dict):
        raise CitationBaselineError(f"{where} must be a JSON object, got {type(raw).__name__}")
    _require_keys(raw, where)
    _require_line_numbers(raw, where)
    _require_prose(raw, where)
    path: str = raw["path"]
    if "*" in path or "?" in path:
        raise CitationBaselineError(
            f"{where}.path must name exactly one source file, not a glob: {path!r}"
        )
    start: int = raw["cited_start"]
    end: int = raw["cited_end"]
    if end < start:
        raise CitationBaselineError(f"{where}.cited_end {end} precedes cited_start {start}")
    return BaselineEntry(
        doc_line=raw["doc_line"],
        path=path,
        cited_start=start,
        cited_end=end,
        finding=raw["finding"],
        reason=raw["reason"],
    )


def _require_no_duplicates(entries: Sequence[BaselineEntry], source: Path) -> None:
    seen: set[CitationKey] = set()
    for entry in entries:
        if entry.key in seen:
            raise CitationBaselineError(
                f"{source}: two entries cover the same citation ({entry.label()}); "
                "duplicate rows inflate the ratchet count while blessing one citation"
            )
        seen.add(entry.key)


def _require_frozen_count(data: dict[str, object], source: Path) -> int:
    frozen = data.get("frozen_count")
    if not isinstance(frozen, int) or isinstance(frozen, bool) or frozen < 0:
        raise CitationBaselineError(
            f"{source}: frozen_count must be a non-negative integer, got {frozen!r}"
        )
    return frozen


def load_baseline(path: Path) -> Baseline:
    """Load the registry. A missing file is an empty (day-one) registry.

    Empty is safe: with nothing registered, every unverified citation is
    unregistered, so the driver exits 2. Deleting the file cannot buy a
    pass, only a louder failure.
    """
    if not path.exists():
        return Baseline(frozen_count=0, entries=(), source=path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CitationBaselineError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CitationBaselineError(f"{path} must hold a JSON object")
    frozen = _require_frozen_count(data, path)
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise CitationBaselineError(
            f"{path}: entries must be a JSON list, got {type(raw_entries).__name__}"
        )
    entries = tuple(_entry_from(raw, position) for position, raw in enumerate(raw_entries))
    _require_no_duplicates(entries, path)
    return Baseline(frozen_count=frozen, entries=entries, source=path)


def cover(keys: Sequence[CitationKey], baseline: Baseline) -> Coverage:
    """Split *keys* (the unverified citations) into covered and uncovered.

    ``stale`` holds every entry that matched nothing. A stale entry is
    reported by the driver as a violation, not a notice: the registry is
    a per-citation claim, and one that no longer matches means either the
    doc moved (so the blessing was never re-read against what it now
    covers) or the citation was repaired (so the blessing is dead and the
    ratchet owes a shrink). Both cases must be settled by a human before
    the gate can be trusted to know what it is grading. Removing an
    entry is free, so the cost of the strict reading is one deletion.
    """
    index = {entry.key: entry for entry in baseline.entries}
    covered = tuple((key, index[key]) for key in keys if key in index)
    uncovered = tuple(key for key in keys if key not in index)
    matched = {key for key, _ in covered}
    stale = tuple(entry for entry in baseline.entries if entry.key not in matched)
    return Coverage(covered=covered, uncovered=uncovered, stale=stale)


def ratchet(baseline: Baseline) -> tuple[list[str], list[str]]:
    """Return (violations, notices) for the add-requires-a-bump ratchet.

    The first notice is unconditional: the count and the frozen number
    are printed on every run, clean or not, so the size of the blessed
    set is a visible decision rather than a fact nobody re-reads.
    """
    count = len(baseline.entries)
    headline = (
        f"citation baseline: {count} registered entr{_y(count)}, "
        f"frozen_count={baseline.frozen_count} ({baseline.source})"
    )
    notices = [headline]
    violations: list[str] = []
    if count > baseline.frozen_count:
        violations.append(
            f"citation baseline holds {count} entr{_y(count)} but frozen_count is "
            f"{baseline.frozen_count}: adding an entry is a decision and must bump "
            "frozen_count in the same commit"
        )
    elif count < baseline.frozen_count:
        slack = baseline.frozen_count - count
        notices.append(
            f"citation baseline slack: frozen_count={baseline.frozen_count} exceeds the "
            f"{count} live entr{_y(count)} by {slack} — it may shrink to {count}"
        )
    return violations, notices


def _y(count: int) -> str:
    """Pluralise ``entry``/``entries`` without a second format string."""
    return "y" if count == 1 else "ies"
