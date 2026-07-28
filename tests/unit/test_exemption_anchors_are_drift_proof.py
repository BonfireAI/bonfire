# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin test — ``exemptions.json`` anchors must be drift-proof and unambiguous.

``exemptions.json`` registers every blessed suppression as
``{file, symbol_or_line, rule, reason, approver}``. The quality gate resolves an
entry against a live suppression by ``file + rule + (line OR enclosing symbol)``,
so an entry may be anchored either way. The two forms behave very differently:

* A **line anchor** is a pointer into a file that any edit can move. Inserting a
  single line above a registered ``# noqa`` silently un-registers a blessed
  exemption, and the gate then reports ``UNREGISTERED_SUPPRESSION`` against the
  suppression — naming the code as the culprit when the registry pointer is what
  actually rotted. That message is convincing and it is wrong; it has cost real
  review time and nearly provoked rewrites of load-bearing error barriers.
* A **symbol anchor** names the enclosing ``def``/``class`` by qualified name and
  survives any insertion.

So symbol anchors are the rule. But a symbol anchor is only correct when it
identifies **exactly one** suppression. If two suppressions of the same rule live
inside the same enclosing symbol, one symbol anchor covers both: one entry goes
dead, the register stops being a list of decisions and becomes a list of
permissions, and a *future* suppression of that rule dropped into the same
function is auto-blessed with nobody approving it.

This test pins both halves:

1. every entry is symbol-anchored, except the line pins documented in
   :data:`_LINE_PINNED` — each of which is line-pinned because a symbol anchor
   provably *cannot* identify it uniquely;
2. every entry — either form — resolves to exactly **one** live suppression.

A third test cross-checks the small resolver below against the installed quality
kit, so this file cannot drift away from the gate whose behaviour it mirrors.
"""

from __future__ import annotations

import ast
import json
import re
import tokenize
from collections import Counter
from pathlib import Path

import pytest

# Repo root: tests/unit/test_exemption_anchors_are_drift_proof.py → parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXEMPTIONS = _REPO_ROOT / "exemptions.json"

#: The entries that CANNOT be symbol-anchored, each with the reason a symbol
#: anchor would be wrong rather than merely inconvenient. Anything line-anchored
#: and absent from this map fails the test; anything listed here that becomes
#: symbol-anchorable must be removed from the map, so the list cannot go stale.
_SHARED_WS_HANDLER = (
    "two S101 suppressions share the enclosing symbol FrontDoorServer._ws_handler "
    "(lines 446, 447); one symbol anchor would cover both, kill the other entry, and "
    "blanket-bless any future assert dropped into that handler"
)
_LINE_PINNED: dict[tuple[str, str, str], str] = {
    ("src/bonfire/git/scratch.py", "S105", "55"): (
        "module level: the suppression sits outside any def/class, so there is no "
        "enclosing symbol to anchor to"
    ),
    ("src/bonfire/onboard/server.py", "S101", "446"): _SHARED_WS_HANDLER,
    ("src/bonfire/onboard/server.py", "S101", "447"): _SHARED_WS_HANDLER,
}


def _load_entries() -> list[dict[str, str]]:
    """The committed exemption entries, in file order."""
    data = json.loads(_EXEMPTIONS.read_text(encoding="utf-8"))
    return list(data["entries"])


def _symbol_spans(source: str) -> list[tuple[int, int, str]]:
    """``(start, end, qualified name)`` for every def/class in *source*.

    Mirrors the quality kit: names are dotted paths (``Outer.run``), never bare
    names, because bare names let same-named symbols in different scopes collapse
    onto one registry entry.
    """
    spans: list[tuple[int, int, str]] = []
    pending: list[tuple[ast.AST, str]] = [(ast.parse(source), "")]
    while pending:
        node, prefix = pending.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                if child.end_lineno is not None:
                    spans.append((child.lineno, child.end_lineno, qualname))
                pending.append((child, f"{qualname}."))
            else:
                pending.append((child, prefix))
    return spans


def _enclosing_symbol(spans: list[tuple[int, int, str]], line: int) -> str | None:
    """Innermost def/class enclosing *line*, or ``None`` at module level."""
    best: tuple[int, str] | None = None
    for start, end, name in spans:
        if start <= line <= end and (best is None or end - start < best[0]):
            best = (end - start, name)
    return best[1] if best else None


def _suppression_lines(path: Path, rule: str) -> list[int]:
    """Lines of *path* carrying a ``# noqa``/``# nosec`` naming *rule*.

    Comments are read as COMMENT tokens, so suppression text inside a string
    literal never counts.
    """
    pattern = re.compile(rf"#\s*(?:noqa|nosec)\b[^#]*?\b{re.escape(rule)}\b")
    with tokenize.open(path) as handle:
        tokens = list(tokenize.generate_tokens(handle.readline))
    return [
        tok.start[0]
        for tok in tokens
        if tok.type == tokenize.COMMENT and pattern.search(tok.string)
    ]


def _covered_lines(entry: dict[str, str], root: Path = _REPO_ROOT) -> list[int]:
    """Every live suppression line that *entry* covers — the ambiguity measure.

    An entry covers a suppression when file and rule agree and the anchor equals
    either the suppression's line number or its enclosing symbol, exactly as the
    gate resolves it.
    """
    path = root / entry["file"]
    anchor = str(entry["symbol_or_line"]).strip()
    spans = _symbol_spans(path.read_text(encoding="utf-8"))
    return [
        line
        for line in _suppression_lines(path, entry["rule"])
        if anchor == str(line) or anchor == _enclosing_symbol(spans, line)
    ]


def test_every_anchor_is_a_symbol_except_the_documented_line_pins() -> None:
    """Line anchors rot on insertion, so only the provably-stuck ones survive."""
    entries = _load_entries()
    assert entries, "exemptions.json carries no entries — this test would be vacuous"

    line_anchored = {
        (entry["file"], entry["rule"], str(entry["symbol_or_line"]).strip())
        for entry in entries
        if str(entry["symbol_or_line"]).strip().isdigit()
    }
    assert line_anchored == set(_LINE_PINNED), (
        "line-anchored exemption entries must match _LINE_PINNED exactly.\n"
        f"undocumented line anchors (re-anchor to the enclosing symbol): "
        f"{sorted(line_anchored - set(_LINE_PINNED))}\n"
        f"stale _LINE_PINNED rows (entry is gone or now symbol-anchored, drop them): "
        f"{sorted(set(_LINE_PINNED) - line_anchored)}"
    )
    # Control rod on this assertion: it must be measuring a real, non-empty
    # population of symbol anchors, not passing because everything is exempt.
    assert len(entries) - len(line_anchored) > 0


def test_no_exemption_entry_covers_more_than_one_suppression() -> None:
    """One entry, one suppression — an anchor is a decision, never a permission."""
    entries = _load_entries()
    coverage = {index: _covered_lines(entry) for index, entry in enumerate(entries)}

    ambiguous = {index: lines for index, lines in coverage.items() if len(lines) > 1}
    assert not ambiguous, (
        "these exemption entries each cover MORE THAN ONE live suppression, so "
        "one entry silently blesses several sites and a future suppression of "
        "the same rule in that symbol would be auto-covered: "
        + "; ".join(
            f"entry {i} {entries[i]['file']} {entries[i]['rule']} "
            f"anchor={entries[i]['symbol_or_line']!r} -> lines {lines}"
            for i, lines in sorted(ambiguous.items())
        )
    )

    dead = {index: lines for index, lines in coverage.items() if not lines}
    assert not dead, (
        "these exemption entries cover NO live suppression — the anchor is stale "
        "or the suppression is gone, and the entry is dead weight on the ratchet: "
        + "; ".join(
            f"entry {i} {entries[i]['file']} {entries[i]['rule']} "
            f"anchor={entries[i]['symbol_or_line']!r}"
            for i in sorted(dead)
        )
    )


def test_the_ambiguity_measure_reports_two_for_a_deliberately_ambiguous_anchor(
    tmp_path: Path,
) -> None:
    """Control rod: the measure above must be able to fail, not only to pass.

    Two suppressions of one rule inside one function, anchored by that
    function's name, is precisely the case the gate exists to reject.
    """
    module = tmp_path / "src" / "probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "class Handler:\n"
        "    def run(self) -> None:\n"
        "        assert True  # noqa: S101\n"
        "        assert False  # noqa: S101\n"
        "\n"
        "    def other(self) -> None:\n"
        "        assert True  # noqa: S101\n",
        encoding="utf-8",
    )
    ambiguous = {"file": "src/probe.py", "symbol_or_line": "Handler.run", "rule": "S101"}
    assert _covered_lines(ambiguous, root=tmp_path) == [3, 4]

    unique = {"file": "src/probe.py", "symbol_or_line": "Handler.other", "rule": "S101"}
    assert _covered_lines(unique, root=tmp_path) == [7]

    pinned = {"file": "src/probe.py", "symbol_or_line": "4", "rule": "S101"}
    assert _covered_lines(pinned, root=tmp_path) == [4]


def test_the_local_resolver_agrees_with_the_installed_quality_kit() -> None:
    """Round trip: this file's resolver must match the gate it mirrors.

    The gate that actually blocks a merge is ``cf-exemptions`` from the quality
    kit. The kit is not a test-time dependency of this repo, so the tests above
    resolve anchors themselves; this test asserts that the two agree entry by
    entry whenever the kit IS importable, so the mirror cannot silently drift.
    """
    exemptions = pytest.importorskip(
        "cf_quality.exemptions",
        reason="quality kit not installed here; cf-exemptions enforces this in CI",
    )
    suppressions, _ = exemptions._scan_src(_REPO_ROOT)
    assert suppressions, "the kit found no suppressions — the comparison would be vacuous"

    entries = _load_entries()
    kit = Counter[int]()
    for suppression in suppressions:
        for index, entry in enumerate(entries):
            if exemptions._matches(suppression, entry):
                kit[index] += 1

    mine = {index: len(_covered_lines(entry)) for index, entry in enumerate(entries)}
    assert mine == {index: kit[index] for index in range(len(entries))}
