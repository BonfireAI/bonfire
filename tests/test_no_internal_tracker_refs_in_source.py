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
    "design-section": re.compile(r"§\s?D\d+|§D-[A-Z]+|§A Q\d+|Sage §|\bSage D\d+"),
    "analysis-doc-section": re.compile(r"§12 [A-Z]\d"),
    "plan-doc": re.compile(r"design doc §|public-port plan|Scout-\d+/\d+"),
    "personal-name": re.compile(r"\bA" r"nta\b"),
    "w-letter": re.compile(r"\bW\d+\.[A-Z]\b"),
    "w-finding": re.compile(r"\bW\d+ [A-Z]\d\b"),
    "design-lock": re.compile(r"\bD-CL\b|\bcluster-\d+\b"),
    "ambiguity-ref": re.compile(r"\bAMBIG #\d+"),
    "role-instance": re.compile(r"\bWarrior [A-Z]\b"),
    "follow-up-wave": re.compile(r"\bfollow-up wave\b"),
    "wave-hyphen": re.compile(r"\bWave-\d+"),
}

_MarkerHit = tuple[str, int, str, str]  # (rel_path, lineno, family, stripped_line)


def _scan_tree(
    paths: list[Path], base: Path, families: dict[str, re.Pattern[str]]
) -> tuple[list[_MarkerHit], int]:
    """Scan each UTF-8 file in *paths* for *families*; skip files that are not UTF-8 text."""
    hits: list[_MarkerHit] = []
    scanned = 0
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        rel = path.relative_to(base).as_posix()
        for i, line in enumerate(text.splitlines(), start=1):
            for family, pattern in families.items():
                if pattern.search(line):
                    hits.append((rel, i, family, line.strip()))
    return hits, scanned


def _scan_markers(root: Path, base: Path) -> tuple[list[_MarkerHit], int]:
    """Scan every non-cache, UTF-8 file under *root* for the marker families.

    Paths in the hits are relative to *base*. Returns ``(hits, files_scanned)``.
    """
    if not root.is_dir():
        return [], 0
    paths = [p for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    return _scan_tree(paths, base, _MARKER_FAMILIES)


_DOC_ROOT_FILES = ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "CLAUDE.md")
_DOC_FAMILIES: dict[str, re.Pattern[str]] = {
    **_MARKER_FAMILIES,
    "ticket-id": re.compile(r"\bbon-\d+", re.IGNORECASE),
    "memo-citation": re.compile(r"Sage memo\s*(?:`|§|$)"),
}


def _doc_paths(repo: Path) -> list[Path]:
    """Root documents that exist, plus every file under ``docs/`` (recursive)."""
    paths = [repo / name for name in _DOC_ROOT_FILES if (repo / name).is_file()]
    docs = repo / "docs"
    if docs.is_dir():
        paths += [p for p in sorted(docs.rglob("*")) if p.is_file()]
    return paths


def _scan_docs(repo: Path) -> tuple[list[_MarkerHit], int]:
    """Scan the public documents under *repo*; hit paths are relative to *repo*."""
    return _scan_tree(_doc_paths(repo), repo, _DOC_FAMILIES)


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
    offenders = hits
    assert scanned > 100, f"scan looks vacuous: only {scanned} files scanned"
    assert scanned == _independent_file_count(root), "walker disagrees with independent count"
    assert not offenders, (
        f"Found {len(offenders)} planning markers across {len({o[0] for o in offenders})} "
        f"files ({scanned} files scanned) in shipped source.\n"
        "Rewrite each as plain English; public readers cannot resolve these citations.\n"
        + "\n".join(f"  {p}:{n}: [{fam}] {text}" for p, n, fam, text in offenders)
    )


def _utf8_readable(path: Path) -> bool:
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def test_no_planning_markers_in_public_docs() -> None:
    """No planning markers, tracker ids or memo citations in the public documents."""
    hits, scanned = _scan_docs(_REPO_ROOT)
    roots = [_REPO_ROOT / name for name in _DOC_ROOT_FILES]
    independent = sum(1 for p in roots if p.is_file() and _utf8_readable(p))
    independent += _independent_file_count(_REPO_ROOT / "docs")
    assert scanned >= 15, f"scan looks vacuous: only {scanned} files scanned"
    assert scanned == independent, "walker disagrees with independent count"
    assert not hits, (
        f"Found {len(hits)} planning markers across {len({h[0] for h in hits})} "
        f"files ({scanned} files scanned) in public docs.\n"
        "Rewrite each as plain English; public readers cannot resolve these citations.\n"
        + "\n".join(f"  {p}:{n}: {fam}: {text}" for p, n, fam, text in hits)
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
        ("personal-name", "# + " + "An" + "ta" + "-ratified §A Q9a):"),
        ("w-letter", "# closed by W7.M (see below)"),
        ("w-finding", "# W11 M4: reject hostile prefixes"),
        ("design-lock", "# (per the cluster-350 D-CL.1 lock)"),
        ("ambiguity-ref", "# per AMBIG #5."),
        ("role-instance", "# (Warrior B pure function)"),
        ("follow-up-wave", "# will land in a follow-up wave."),
        ("design-section", "# locked per Sage D9."),
        ("wave-hyphen", "# the Wave-9 sweep"),
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
        "the Sage reviewer",
    ],
)
def test_innocent_text_is_not_caught(tmp_path: Path, line: str) -> None:
    assert _plant(tmp_path, "mod.py", f"# {line}") == []


def _plant_docs(tmp_path: Path, files: dict[str, str]) -> list[_MarkerHit]:
    for rel, line in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(line + "\n", encoding="utf-8")
    hits, _ = _scan_docs(tmp_path)
    return hits


@pytest.mark.parametrize("rel", ["README.md", "docs/sub/x.md"])
@pytest.mark.parametrize(
    ("family", "line"),
    [
        ("memo-citation", "(Sage memo `x-sage.md` §A Q4)"),
        ("memo-citation", "See Sage memo"),
        ("ticket-id", "tracked under BON-610"),
        ("ticket-id", "`bon-519-sage-x.md`"),
        ("wave", "Wave 9.2 release preparation"),
    ],
)
def test_docs_marker_is_caught_in_root_and_nested(
    tmp_path: Path, rel: str, family: str, line: str
) -> None:
    hits = _plant_docs(tmp_path, {rel: line})
    assert {h[0] for h in hits} == {rel}
    assert family in {h[2] for h in hits}, f"{family!r} missed: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        "- `BON-NNN` in commit subjects",
        "checks against the binding Sage memo, and either approves",
        "| 1 | `<wave>` | *(required)* | Wave number the gate is evaluating.",
        "see § Ratified Exceptions below",
        "SHA-256 digest",
    ],
)
def test_docs_innocent_text_is_not_caught(tmp_path: Path, line: str) -> None:
    assert _plant_docs(tmp_path, {"README.md": line, "docs/sub/x.md": line}) == []
