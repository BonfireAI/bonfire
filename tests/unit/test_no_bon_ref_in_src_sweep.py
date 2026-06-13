"""Sweep test — no internal tracker refs (``BON-NNN``) in ``src/bonfire/``.

This is a public tree, so internal tracker IDs must never ship in source.
The sweep walks every ``.py`` file under ``src/bonfire/`` and scans for the
regex ``BON-\\d+``; any hit is an offender.

The allowlist is empty by policy — there is no sanctioned exception. A
tracker ID introduced into ``src/bonfire/`` therefore fails the gate
outright; the fix is always to rewrite the comment or docstring into
neutral prose that keeps the engineering intent and drops the ID.

Reads files on disk only — no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"

# Regex matching the internal tracker-ref shape: the ``BON-`` prefix
# followed by one or more digits. Suffixes that are not pure digits (a
# letter after the dash) do not match and are out of scope for this sweep.
_BON_REF = re.compile(r"BON-\d+")

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
# Empty by policy: no internal tracker ID is sanctioned in shipped source on
# this public tree. An entry would be keyed by
# ``(relative_path_from_src_bonfire, line_number, expected_line_prefix)`` —
# but the set is intentionally empty, so every ``BON-NNN`` in source is an
# offender with no exception path.
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
    """No ``BON-\\d+`` ref may live in ``src/bonfire/``.

    Failure message lists every offender as ``(path, line_no, line_text)``
    so a contributor can navigate directly. The fix is always to rewrite
    the offending comment or docstring into neutral prose; the allowlist
    stays empty.
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
