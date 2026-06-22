"""Sweep test — no internal-tracker refs in ``src/bonfire/``.

Walks every ``.py`` file under ``src/bonfire/`` and scans for the regex
``<TKT>-\\d+`` (with ``<TKT>`` matching the internal-tracker prefix).
Any hit that is NOT in the explicit allowlist below is an offender —
the comment must be scrubbed or rewritten as plain English.

The allowlist is keyed by ``(relative_path, line_number,
expected_substring_prefix)``. The substring prefix is matched against
the START of the offending line (after stripping). Mismatch on any
field causes the test to fail — i.e. if a code edit shifts a citation
to a new line number, the allowlist must be re-confirmed too. That's
the durability we want: every internal-tracker ref in source costs an
explicit allowlist entry.

Currently empty: the source tree is clean. The allowlist machinery is
preserved so a future legitimate citation (e.g. an external-tracker
shape we DO want to encode) can land with an explicit rationale.

Reads files on disk only — no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"

# Regex matching the canonical ticket-ref shape (e.g. ``BON-338``).
# Note: ``BON-W5.3``-style refs do NOT match (W is not a digit) — those
# are intentionally out of scope for this sweep.
_BON_REF = re.compile(r"BON-\d+")

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
# Each entry = (relative_path_from_src_bonfire, line_number, expected_line_prefix).
# ``expected_line_prefix`` is matched with ``.lstrip().startswith(...)`` so
# whitespace at line start is normalised. This couples the allowlist tightly
# to the actual source — a legitimate edit elsewhere in the file is fine, but
# a change to the ref-bearing line itself forces a fresh review.
_ALLOWLIST: frozenset[tuple[str, int, str]] = frozenset()


def _iter_python_files(root: Path) -> list[Path]:
    """Return all .py files under *root*, excluding __pycache__."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _is_allowlisted(rel_path: str, lineno: int, line: str) -> bool:
    """True iff the offender matches an allowlist entry."""
    stripped = line.lstrip()
    for allowed_path, allowed_line, allowed_prefix in _ALLOWLIST:
        if (
            allowed_path == rel_path
            and allowed_line == lineno
            and stripped.startswith(allowed_prefix)
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_no_bon_ref_in_src_outside_allowlist() -> None:
    """No ``BON-\\d+`` ref may live in ``src/bonfire/`` outside the allowlist.

    Failure message lists every offender as ``(path, line_no, line_text)``
    so the Warrior can navigate directly. Future legitimate citations
    require explicitly extending ``_ALLOWLIST`` above with rationale.
    """
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files(_SRC_DIR):
        rel = path.relative_to(_SRC_DIR).as_posix()
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _BON_REF.search(line) and not _is_allowlisted(rel, i, line):
                offenders.append((rel, i, line.rstrip()))

    assert not offenders, (
        "Found stale BON-NNN refs in src/bonfire/ outside the allowlist.\n"
        "Each ref must either be scrubbed or added to _ALLOWLIST with "
        "rationale (canonical decision authority only).\n"
        + "\n".join(f"  src/bonfire/{p}:{n}: {line}" for p, n, line in offenders)
    )


def test_allowlist_entries_still_resolve() -> None:
    """Every allowlist entry must still match a real line in source.

    Guards against the allowlist drifting out of sync with the code.
    If a refactor moves or removes a sweep-guard comment, the allowlist
    entry becomes a lie — this test catches that.
    """
    stale: list[tuple[str, int, str]] = []
    for rel_path, lineno, expected_prefix in _ALLOWLIST:
        full = _SRC_DIR / rel_path
        if not full.is_file():
            stale.append((rel_path, lineno, f"<file missing: {full}>"))
            continue
        lines = full.read_text(encoding="utf-8").splitlines()
        if lineno < 1 or lineno > len(lines):
            stale.append((rel_path, lineno, f"<out-of-range: file has {len(lines)} lines>"))
            continue
        actual = lines[lineno - 1].lstrip()
        if not actual.startswith(expected_prefix):
            stale.append(
                (rel_path, lineno, f"<expected prefix {expected_prefix!r}, got {actual!r}>")
            )

    assert not stale, (
        "Allowlist entries no longer match source — refactor drift detected:\n"
        + "\n".join(f"  src/bonfire/{p}:{n}: {info}" for p, n, info in stale)
    )
