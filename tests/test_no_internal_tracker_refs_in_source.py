# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin test — no internal-tracker references in shipped source or integration tests.

This is a public repository. ``CONTRIBUTING.md`` §3 forbids internal
tracker IDs, project codenames, and other references that would be
meaningless to outside readers in code comments or documentation.

This test enforces that contract by scanning ``src/bonfire/`` and
``tests/integration/`` for two regex families:

  * ``BON-\\d+`` — internal Linear ticket IDs.
  * ``Sage memo`` / ``Mirror Probe`` — internal review-process artifacts.

A third family covers planning markers: citations to private design
documents, work-planning labels, and personal names. That scan reads every
file under ``src/bonfire/`` (not only ``.py``).

If you find yourself wanting to add a citation to one of those, rewrite
the comment as plain English referencing a public-facing artifact (an
ADR under ``docs/adr/``, a CHANGELOG entry, a docstring section ID, or
inline rationale) so the comment carries its weight without leaking
internal vocabulary.

A separate sweep ``tests/unit/test_no_bon_ref_in_src_sweep.py`` enforces
the same ``BON-NNN`` rule for ``src/bonfire/`` only with a line-anchored
allowlist; this test is the broader integration-test counterpart and
also covers the prose tokens that sweep does not check.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# Repo root: tests/test_no_internal_tracker_refs_in_source.py → parents[1].
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_DIRS: tuple[Path, ...] = (
    _REPO_ROOT / "src" / "bonfire",
    _REPO_ROOT / "tests" / "integration",
)

_BON_REF = re.compile(r"BON-\d+")
_PROSE_REF = re.compile(r"Sage memo|Mirror Probe")


def _iter_python_files(root: Path) -> list[Path]:
    """Return all .py files under *root*, excluding __pycache__."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _scan(pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
    """Return every ``(rel_path, lineno, line)`` matching *pattern*."""
    hits: list[tuple[str, int, str]] = []
    for root in _SCAN_DIRS:
        for path in _iter_python_files(root):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append((rel, i, line.rstrip()))
    return hits


def test_no_bon_ticket_refs_in_source_or_integration_tests() -> None:
    """``BON-\\d+`` is banned in ``src/bonfire/`` and ``tests/integration/``.

    Per ``CONTRIBUTING.md`` §3 ("No internal references"), Linear ticket
    IDs are meaningless to outside readers. Rewrite any load-bearing
    citation as plain English referencing a public artifact (an ADR
    under ``docs/adr/`` or a section ID inside a public docstring).
    """
    offenders = _scan(_BON_REF)
    assert not offenders, (
        "Found BON-NNN tracker refs inside shipped source / integration tests.\n"
        "CONTRIBUTING.md §3 forbids internal references in public code.\n"
        "Scrub each ref or rewrite the comment as plain English referencing\n"
        "a public artifact (ADR, docstring section ID, CHANGELOG entry).\n"
        + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
    )


def test_no_sage_memo_or_mirror_probe_refs_in_source_or_integration_tests() -> None:
    """``Sage memo`` and ``Mirror Probe`` prose are banned in public code.

    Both name internal review artifacts. Citations to internal memos
    should be rewritten as inline rationale or as references to the
    public ADRs / design docs that carry the decision authority forward.
    """
    offenders = _scan(_PROSE_REF)
    assert not offenders, (
        "Found 'Sage memo' / 'Mirror Probe' refs inside shipped source / "
        "integration tests.\n"
        "CONTRIBUTING.md §3 forbids internal references in public code.\n"
        "Rewrite each comment as plain English (inline rationale, public ADR "
        "pointer).\n" + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
    )


# ---------------------------------------------------------------------------
# Planning markers: private design-doc citations, work-planning labels, names.
# ---------------------------------------------------------------------------

_MARKER_FAMILIES: dict[str, re.Pattern[str]] = {
    "wave": re.compile(r"\bWave \d+[a-z]?\b"),
    "w-number": re.compile(r"\bW\d+(?:\.\d+)+\b|\bW\d+ Lane\b"),
    "lane-letter": re.compile(r"\bLanes? [A-E](?:/[A-E])*\b"),
    "design-section": re.compile(r"§\s?D\d+|§D-[A-Z]+|§A Q\d+|Sage §"),
    "analysis-doc-section": re.compile(r"§12 [A-Z]\d"),
    "plan-doc": re.compile(r"design doc §|public-port plan|Scout-\d+/\d+"),
    "personal-name": re.compile(r"\bAnta\b"),
    "w-letter": re.compile(r"\bW\d+\.[A-Z]\b"),
    "w-finding": re.compile(r"\bW\d+ [A-Z]\d\b"),
    "design-lock": re.compile(r"\bD-CL\b|\bcluster-\d+\b"),
    "ambiguity-ref": re.compile(r"\bAMBIG #\d+"),
    "role-instance": re.compile(r"\bWarrior [A-Z]\b"),
    "follow-up-wave": re.compile(r"\bfollow-up wave\b"),
}

_MarkerHit = tuple[str, int, str, str]  # (rel_path, lineno, family, stripped_line)

_EXEMPT_REASON = (
    "this file is being edited by a separate open change that rewrites these "
    "comments; drop the entry once it lands"
)
_EXEMPT_PATH = "src/bonfire/engine/gates.py"
# Exact (repo-relative path, exact stripped line text) pairs. Never line numbers.
_EXEMPT_ENTRIES: dict[tuple[str, str], str] = {
    (
        _EXEMPT_PATH,
        "# Gate name string -- locked per Sage §D-CL.6 #5 (line 1071) for the merge-preflight gate.",
    ): _EXEMPT_REASON,
    (
        _EXEMPT_PATH,
        "# Gate name string -- locked per Sage §D-CL.6 #5 + §A Q3 line 124 for the",
    ): _EXEMPT_REASON,
    (
        _EXEMPT_PATH,
        ":class:`GateResult`. Verdict-routing matrix (Sage §D-CL.1 lines 93-97",
    ): _EXEMPT_REASON,
    (_EXEMPT_PATH, "+ Anta-ratified §A Q9a):"): _EXEMPT_REASON,
}


def _scan_markers(root: Path, base: Path) -> tuple[list[_MarkerHit], int]:
    """Scan every non-cache, UTF-8 file under *root* for the marker families.

    Paths in the hits are relative to *base*. Returns ``(hits, files_scanned)``.
    """
    hits: list[_MarkerHit] = []
    scanned = 0
    if not root.is_dir():
        return hits, scanned
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        rel = path.relative_to(base).as_posix()
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            for family, pattern in _MARKER_FAMILIES.items():
                if pattern.search(line):
                    hits.append((rel, i, family, stripped))
    return hits, scanned


def _is_exempt(hit: _MarkerHit) -> bool:
    """A hit is exempt only if BOTH its path and stripped text match an entry."""
    return (hit[0], hit[3]) in _EXEMPT_ENTRIES


def _split_exempt(hits: list[_MarkerHit]) -> tuple[list[_MarkerHit], int]:
    """Return ``(non_exempt_hits, entries_present)``."""
    present = {(h[0], h[3]) for h in hits if _is_exempt(h)}
    return [h for h in hits if not _is_exempt(h)], len(present)


def _independent_file_count(root: Path) -> int:
    """Count UTF-8 readable, non-cache files with a walk that shares no code with the scan."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            try:
                (Path(dirpath) / name).read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            count += 1
    return count


def test_no_planning_markers_in_shipped_src() -> None:
    """No planning markers, design-doc citations or personal names in ``src/bonfire/``."""
    root = _REPO_ROOT / "src" / "bonfire"
    hits, scanned = _scan_markers(root, _REPO_ROOT)
    offenders, present = _split_exempt(hits)
    print(f"allowlisted {present} of {len(_EXEMPT_ENTRIES)} present")
    assert scanned > 100, f"scan looks vacuous: only {scanned} files scanned"
    assert scanned == _independent_file_count(root), "walker disagrees with independent count"
    assert not offenders, (
        f"Found {len(offenders)} planning markers across {len({o[0] for o in offenders})} "
        f"files ({scanned} files scanned) in shipped source.\n"
        "Rewrite each as plain English; public readers cannot resolve these citations.\n"
        + "\n".join(f"  {p}:{n}: [{fam}] {text}" for p, n, fam, text in offenders)
    )


# --- teeth -----------------------------------------------------------------


def _plant(tmp_path: Path, rel: str, line: str) -> list[_MarkerHit]:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(line + "\n", encoding="utf-8")
    hits, _ = _scan_markers(tmp_path, tmp_path)
    return hits


@pytest.mark.parametrize(
    ("family", "line"),
    [
        ("wave", "# consumed by Wave 2b."),
        ("w-number", "# W1.5.3 default floor + W4.1 user seam"),
        ("w-number", "# W9 Lane B: removed"),
        ("lane-letter", "# Wave 11 Lane D parity fix"),
        ("design-section", "# (Sage §D-CL.7 #6 envelope-size discipline)"),
        ("analysis-doc-section", "# per §12 C3 so two workspaces"),
        ("plan-doc", "# per the public-port plan §D-FT A/B/C"),
        ("personal-name", "# + Anta-ratified §A Q9a):"),
        ("w-letter", "# closed by W7.M (see below)"),
        ("w-finding", "# W11 M4: reject hostile prefixes"),
        ("design-lock", "# (per the cluster-350 D-CL.1 lock)"),
        ("ambiguity-ref", "# per AMBIG #5."),
        ("role-instance", "# (Warrior B pure function)"),
        ("follow-up-wave", "# will land in a follow-up wave."),
    ],
)
def test_marker_family_is_caught(tmp_path: Path, family: str, line: str) -> None:
    hits = _plant(tmp_path, "mod.py", line)
    assert family in {h[2] for h in hits}, f"{family!r} missed: {line!r}"


def test_marker_in_non_python_file_is_caught(tmp_path: Path) -> None:
    hits = _plant(tmp_path, "docs/notes.md", "consumed by Wave 2b.")
    assert [h[0] for h in hits] == ["docs/notes.md"]


@pytest.mark.parametrize(
    "line",
    [
        "see ADR-001 § Ratified Exceptions",
        "Spec: ``docs/specs/ism-v1.md`` §7, §8.",
        "class SageCorrectionBounceHandler:",
        "the real Q1/Q2/Q3 free-text answers",
        "SHA-256 hex digest",
        "a waveform sample",
        "the Sage reviewer role",
        "Cross-wave interaction detected with",
        "CROSS_WAVE_INTERACTION",
        "closed by PR #93",
        'f"PR #{number}"',
        "the Warrior agent writes code",
        "a cluster of nodes",
    ],
)
def test_innocent_text_is_not_caught(tmp_path: Path, line: str) -> None:
    assert _plant(tmp_path, "mod.py", f"# {line}") == []


def test_exemption_does_not_travel_to_other_files(tmp_path: Path) -> None:
    body = "\n".join(text for _, text in _EXEMPT_ENTRIES) + "\n"
    other = tmp_path / "src" / "bonfire" / "engine" / "other.py"
    other.parent.mkdir(parents=True)
    other.write_text(body, encoding="utf-8")
    hits, _ = _scan_markers(tmp_path, tmp_path)
    offenders, present = _split_exempt(hits)
    assert present == 0
    assert {h[3] for h in offenders} == {text for _, text in _EXEMPT_ENTRIES}


def test_exemption_applies_only_to_exact_path_and_text(tmp_path: Path) -> None:
    exact = "\n".join(text for _, text in _EXEMPT_ENTRIES) + "\n"
    gates = tmp_path / _EXEMPT_PATH
    gates.parent.mkdir(parents=True)
    gates.write_text(exact + "# also per Sage §D-CL.9 here\n", encoding="utf-8")
    offenders, present = _split_exempt(_scan_markers(tmp_path, tmp_path)[0])
    assert present == len(_EXEMPT_ENTRIES)
    assert {h[3] for h in offenders} == {"# also per Sage §D-CL.9 here"}
