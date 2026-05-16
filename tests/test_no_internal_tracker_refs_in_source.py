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

import re
from pathlib import Path

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
