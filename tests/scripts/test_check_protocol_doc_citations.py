# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the protocol-doc citation drift checker.

The checker's contract is a three-valued exit code:

* **0** — every citation resolved (or is registered in
  ``citation-baseline.json``) AND the run graded a non-empty set.
* **1** — DRIFT: the gate did its job and a citation points at moved code.
* **2** — COULD NOT VERIFY: the gate could not do its job (an
  unregistered unverifiable citation, an absent/unparseable cited
  source, an unreadable doc, a malformed or over-ratchet registry, a
  stale registry entry, or a run that graded zero citations).

Every branch of that contract has a control rod below: a fixture built
in ``tmp_path`` with its own tiny source tree, driven through the real
``main()`` via ``--doc`` / ``--source-root`` / ``--baseline``. Rods that
must go RED assert the exit code AND the text a human would act on.
The GREEN rods are the counterfactual, so a rod going red for the wrong
reason cannot hide: the same fixture harness exits 0 on a resolvable
citation, and the real repo doc exits 0 having graded a non-empty set.

Unit-level coverage of the resolution passes (containment, hint,
drift, unverified) sits at the bottom.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_protocol_doc_citations.py"
_spec = importlib.util.spec_from_file_location("check_protocol_doc_citations", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["check_protocol_doc_citations"] = _module
_spec.loader.exec_module(_module)

# The script puts its own ``scripts/`` directory on sys.path and imports
# its siblings by bare name, so executing it above registered them. Read
# them out of sys.modules rather than importing here: an import
# statement after module-level code is E402, and the script is the only
# thing that legitimately owns that path insert.
_source = sys.modules["citation_source"]
_baseline_mod = sys.modules["citation_baseline"]
_doc_mod = sys.modules["citation_doc"]


_REPO = Path(__file__).resolve().parents[2]
_PROTOCOL_PY = _REPO / "src" / "bonfire" / "onboard" / "protocol.py"

# The fixture source tree every rod resolves its citations against.
# Line map, load-bearing for every cited line number below:
#   1 module docstring · 3 CONSTANT · 6 class Widget · 9 def spin
#   10 return (the last line inside Widget.spin)
# Lines 2, 4, 5 are module-level gaps: cited there, a citation is inside
# no indexed symbol, which is what forces the hint pass.
_FIXTURE_SOURCE = '''"""Fixture module."""

CONSTANT = 1


class Widget:
    """A widget."""

    def spin(self) -> int:
        return CONSTANT
'''

# A citation whose hint (``Widget``) resolves to a real symbol at line 6
# while the cited line is 20: real drift, and far enough from the symbol
# that the rod does not depend on the value of ``--tolerance``.
_DOC_DRIFT = """# Fixture protocol doc

The `Widget` class: `src/bonfire/fixture/sample.py:20`.
"""

# Cited line 4 is a module-level gap and no backticked identifier appears
# in the preceding lines, so neither pass resolves: unverifiable.
_DOC_UNVERIFIED = """# Fixture protocol doc

The registry table has exactly one entry:
`src/bonfire/fixture/sample.py:4`.
"""

# Same, but the one hint in range is on the checker's SKIP_HINTS list.
_DOC_SKIPPED_HINT = """# Fixture protocol doc

The `scan_update` frame is described above.
`src/bonfire/fixture/sample.py:4`.
"""

# Cited line 10 is inside ``Widget.spin``: resolves by containment.
_DOC_CLEAN = """# Fixture protocol doc

The spin method: `src/bonfire/fixture/sample.py:10`.
"""

_DOC_ABSENT_SOURCE = """# Fixture protocol doc

Absent module: `src/bonfire/fixture/ghost.py:5`.
"""

_DOC_NO_CITATIONS = """# Fixture protocol doc

This doc cites no source lines at all.
"""


def _entry(doc_line: int, cited_start: int, cited_end: int) -> dict[str, Any]:
    """One well-formed registry row for the fixture tree."""
    return {
        "doc_line": doc_line,
        "path": "fixture/sample.py",
        "cited_start": cited_start,
        "cited_end": cited_end,
        "finding": "fixture citation: the doc names the registry table, the range covers a gap",
        "reason": "fixture entry for the control rods; never a real blessing",
    }


def _argv(
    tmp_path: Path,
    doc_body: str,
    *,
    baseline: dict[str, Any] | None = None,
) -> list[str]:
    """Write a fixture doc + source tree + registry; return the CLI argv.

    ``--baseline`` always points inside ``tmp_path``, even when no
    registry is written, so no rod can accidentally read (or be rescued
    by) the repository's real ``citation-baseline.json``.
    """
    doc = tmp_path / "doc.md"
    doc.write_text(doc_body, encoding="utf-8")
    source_root = tmp_path / "srcroot"
    (source_root / "fixture").mkdir(parents=True)
    (source_root / "fixture" / "sample.py").write_text(_FIXTURE_SOURCE, encoding="utf-8")
    registry = tmp_path / "citation-baseline.json"
    if baseline is not None:
        registry.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    return [
        "--doc",
        str(doc),
        "--source-root",
        str(source_root),
        "--baseline",
        str(registry),
    ]


# ---------------------------------------------------------------------------
# RED rods — each proves the gate refuses
# ---------------------------------------------------------------------------


def test_drifted_citation_exits_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 1: a citation resolving to a moved symbol is DRIFT -> exit 1."""
    rc = _module.main(_argv(tmp_path, _DOC_DRIFT))
    err = capsys.readouterr().err
    assert rc == 1, f"drift must exit 1, got {rc}; report was:\n{err}"
    assert "DRIFT" in err
    assert "Verdict: exit 1" in err


def test_unregistered_unverifiable_citation_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 2: an unverifiable citation nobody registered -> exit 2, not 0.

    This is the defect this gate was rebuilt to close: ``unverified``
    used to print on stderr and return 0, so the gate was most
    permissive exactly where its confidence was lowest. The report must
    also be actionable — it names the neighbouring symbols and says why
    no hint was usable.
    """
    rc = _module.main(_argv(tmp_path, _DOC_UNVERIFIED))
    err = capsys.readouterr().err
    assert rc == 2, f"an unregistered unverifiable citation must exit 2, got {rc}:\n{err}"
    assert "COULD NOT VERIFY" in err
    assert "unregistered unverifiable citation" in err
    assert "nearest symbol above: CONSTANT (lines 3-3)" in err
    assert "nearest symbol below: Widget (lines 6-10)" in err
    assert "no backticked identifier found in the 5 doc lines" in err


def test_unverifiable_report_names_the_skip_hints_rejection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hint rejected by SKIP_HINTS is reported by name, not silently dropped."""
    rc = _module.main(_argv(tmp_path, _DOC_SKIPPED_HINT))
    err = capsys.readouterr().err
    assert rc == 2
    assert "`scan_update` (listed in citation_doc.SKIP_HINTS)" in err
    assert "scan_update" in _doc_mod.SKIP_HINTS, "the rod must name a real SKIP_HINTS member"


def test_doc_with_zero_citations_is_not_clean(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 3: a graded set of zero must NOT report clean -> exit 2.

    The control rod on the gate itself. A gate that selects the set it
    grades must assert that set is non-empty, or it reports success
    having checked nothing.
    """
    rc = _module.main(_argv(tmp_path, _DOC_NO_CITATIONS))
    err = capsys.readouterr().err
    assert rc == 2, f"a doc with no citations must not pass, got {rc}:\n{err}"
    assert "GRADED NOTHING" in err
    assert "0 citations extracted" in err
    assert "Non-vacuity: FAIL — checked=0" in err


def test_absent_cited_source_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 4: a citation naming a file that does not exist -> exit 2."""
    rc = _module.main(_argv(tmp_path, _DOC_ABSENT_SOURCE))
    err = capsys.readouterr().err
    assert rc == 2, f"an absent cited source must exit 2, got {rc}:\n{err}"
    assert "could not read" in err
    assert "ghost.py" in err


def test_registry_cannot_launder_a_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 5: a registry entry aimed at a DRIFT still exits 1.

    The registry covers the ``unverified`` bucket only. A citation that
    resolves and is wrong fails no matter what is written about it.
    """
    baseline = {"frozen_count": 1, "entries": [_entry(doc_line=3, cited_start=20, cited_end=20)]}
    rc = _module.main(_argv(tmp_path, _DOC_DRIFT, baseline=baseline))
    err = capsys.readouterr().err
    assert rc == 1, f"a registered drift must still exit 1, got {rc}:\n{err}"
    assert "DRIFT" in err
    assert "0 registered-unverifiable" in err
    assert "REGISTERED" not in err, "a drift must never be reported as a registered pass"


def test_added_entry_without_a_frozen_count_bump_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 6: the ratchet — an entry added without bumping frozen_count is red."""
    baseline = {"frozen_count": 0, "entries": [_entry(doc_line=4, cited_start=4, cited_end=4)]}
    rc = _module.main(_argv(tmp_path, _DOC_UNVERIFIED, baseline=baseline))
    err = capsys.readouterr().err
    assert rc == 2, f"an unbumped ratchet must exit 2, got {rc}:\n{err}"
    assert "must bump frozen_count in the same commit" in err


def test_stale_registry_entry_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An entry matching no unverifiable citation is a violation, not a notice."""
    baseline = {"frozen_count": 1, "entries": [_entry(doc_line=99, cited_start=4, cited_end=4)]}
    rc = _module.main(_argv(tmp_path, _DOC_CLEAN, baseline=baseline))
    err = capsys.readouterr().err
    assert rc == 2, f"a stale entry must exit 2, got {rc}:\n{err}"
    assert "stale citation-baseline.json entry" in err


def test_malformed_registry_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A registry entry missing its reason cannot buy a pass."""
    broken = _entry(doc_line=4, cited_start=4, cited_end=4)
    del broken["reason"]
    baseline = {"frozen_count": 1, "entries": [broken]}
    rc = _module.main(_argv(tmp_path, _DOC_UNVERIFIED, baseline=baseline))
    err = capsys.readouterr().err
    assert rc == 2, f"a malformed registry must exit 2, got {rc}:\n{err}"
    assert "citation-baseline.json is unusable" in err


def test_unreadable_doc_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A doc that cannot be read is a structural inability to run -> exit 2."""
    rc = _module.main(["--doc", str(tmp_path / "nope.md")])
    err = capsys.readouterr().err
    assert rc == 2, f"an unreadable doc must exit 2, got {rc}:\n{err}"
    assert "cannot read the doc under test" in err


# ---------------------------------------------------------------------------
# GREEN rods — the counterfactual, so a red rod cannot be red for free
# ---------------------------------------------------------------------------


def test_real_doc_and_real_registry_exit_zero_on_a_nonempty_graded_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 7: the shipped doc + shipped registry exit 0, having graded > 0.

    BEHAVIOUR CHANGE (this assertion replaces the old
    ``test_current_doc_has_no_drift``): exit 0 used to mean only "no
    drift", and the run that measured this gate reached 0 with two
    ``unverified`` citations that were both real drift — the pass was
    partly manufactured by a category that could not fail. Exit 0 now
    means every citation resolved OR is named in
    ``citation-baseline.json`` with a written reason, AND the graded set
    was non-empty. The ``checked > 0`` assertion is the other half: a
    doc whose citations stopped being extractable would have satisfied
    the old assertion by grading nothing.
    """
    rc = _module.main([])
    err = capsys.readouterr().err
    assert rc == 0, f"the shipped doc + registry must exit 0, got {rc}:\n{err}"
    match = re.search(r"checked=(\d+) of (\d+) extracted", err)
    assert match is not None, f"the summary must report the graded count:\n{err}"
    checked, extracted = int(match.group(1)), int(match.group(2))
    assert checked > 0, "a clean run must have graded a non-empty set of citations"
    assert checked == extracted, "every extracted citation must have been graded"
    assert "Non-vacuity: PASS" in err


def test_registered_unverifiable_citation_passes_loudly_with_its_reason(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rod 8: a registered unverifiable citation exits 0 and prints its reason."""
    entry = _entry(doc_line=4, cited_start=4, cited_end=4)
    baseline = {"frozen_count": 1, "entries": [entry]}
    rc = _module.main(_argv(tmp_path, _DOC_UNVERIFIED, baseline=baseline))
    err = capsys.readouterr().err
    assert rc == 0, f"a registered unverifiable citation must exit 0, got {rc}:\n{err}"
    assert "REGISTERED" in err
    assert entry["reason"] in err
    assert entry["finding"] in err
    assert "citation baseline: 1 registered entry, frozen_count=1" in err


def test_clean_fixture_exits_zero_without_a_registry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The harness itself is not rigged red: a resolvable citation exits 0."""
    rc = _module.main(_argv(tmp_path, _DOC_CLEAN))
    err = capsys.readouterr().err
    assert rc == 0, f"a containment-resolved citation must exit 0, got {rc}:\n{err}"
    assert "Verdict: exit 0" in err


def test_removed_entries_leave_shrinkable_slack(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Entries may be removed freely; the leftover frozen_count prints as slack."""
    baseline: dict[str, Any] = {"frozen_count": 3, "entries": []}
    rc = _module.main(_argv(tmp_path, _DOC_CLEAN, baseline=baseline))
    err = capsys.readouterr().err
    assert rc == 0, f"slack is not a violation, got {rc}:\n{err}"
    assert "citation baseline slack: frozen_count=3" in err
    assert "it may shrink to 0" in err


# ---------------------------------------------------------------------------
# Resolution-pass units (against the real protocol module)
# ---------------------------------------------------------------------------


def test_drift_is_flagged_when_hint_resolves_to_moved_symbol() -> None:
    """A citation that names a symbol but points at the wrong line is drift."""
    idx = _source.index_symbols(_PROTOCOL_PY)
    cite = _doc_mod.Citation(doc_line=1, path="onboard/protocol.py", start=15, end=15)
    result = _module._check_citation(cite, hint="ConversationStart", index=idx, tolerance=3)
    assert result.status == "drift"
    # The actual ConversationStart class is well-known to live somewhere
    # past the imports block; the exact line is not what we're testing,
    # only that the checker reported drift and resolved to the right
    # symbol name.
    assert result.resolved_symbol == "ConversationStart"


def test_out_of_range_citation_is_unverified_not_silently_ok() -> None:
    """A cited line past EOF with no hint MUST be ``unverified``."""
    idx = _source.index_symbols(_PROTOCOL_PY)
    cite = _doc_mod.Citation(doc_line=1, path="onboard/protocol.py", start=99_999, end=99_999)
    result = _module._check_citation(cite, hint=None, index=idx, tolerance=3)
    assert result.status == "unverified"


def test_containment_pass_resolves_in_body_citation() -> None:
    """A citation that lands inside a class body is OK + names the class."""
    idx = _source.index_symbols(_PROTOCOL_PY)
    # ``ScanUpdate``'s ``detail`` field lives inside the ScanUpdate
    # class. The citation does not have to point at the class header
    # to count as OK.
    scan_update_range = idx.by_name["ScanUpdate"]
    in_body_line = scan_update_range[1]  # last line of the class
    cite = _doc_mod.Citation(
        doc_line=1,
        path="onboard/protocol.py",
        start=in_body_line,
        end=in_body_line,
    )
    result = _module._check_citation(cite, hint=None, index=idx, tolerance=3)
    assert result.status == "ok"
    assert result.resolved_symbol == "ScanUpdate"


def test_unparseable_source_raises_a_typed_error() -> None:
    """The source indexer speaks a typed error, never a bare crash."""
    with pytest.raises(_source.SourceIndexError):
        _source.index_symbols(_REPO / "docs" / "scan-front-door-protocol.md")


def test_shipped_registry_entries_each_name_one_citation() -> None:
    """The shipped registry parses, and every entry is a single-citation claim."""
    baseline = _baseline_mod.load_baseline(_REPO / _baseline_mod.BASELINE_FILENAME)
    assert len(baseline.entries) <= baseline.frozen_count
    keys = [entry.key for entry in baseline.entries]
    assert len(keys) == len(set(keys)), "two entries must never cover the same citation"
    for entry in baseline.entries:
        assert "*" not in entry.path and "?" not in entry.path
        assert entry.finding.strip() and entry.reason.strip()
