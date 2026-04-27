"""RED sweep test — no stale ``BON-NNN`` refs in ``src/bonfire/`` (BON-353).

Locks in audit items **B1, B2, B3** from the BON-353 doc-polish audit
(``docs/audit/scout-reports/bon-353-audit-20260427T164458Z.md``).

Walks every ``.py`` file under ``src/bonfire/`` and scans for the regex
``BON-\\d+``. Any hit that is NOT in the explicit allowlist below is an
offender — the Warrior must scrub it (or, if it's a legitimate citation
of canonical decision authority, extend the allowlist with rationale).

The allowlist is keyed by ``(relative_path, line_number,
expected_substring_prefix)``. The substring prefix is matched against
the START of the offending line (after stripping). Mismatch on any
field causes the test to fail — i.e. if a code edit shifts a citation
to a new line number, the allowlist must be re-confirmed too. That's
the durability we want: every BON-NNN ref in source costs an explicit
allowlist entry.

Expected RED-state failures at HEAD (Warrior must scrub these):

  * ``src/bonfire/protocols.py:74``                — ``BON-338`` (audit B1)
  * ``src/bonfire/dispatch/security_hooks.py:1``    — ``BON-338`` (audit B2)
  * ``src/bonfire/dispatch/security_patterns.py:1`` — ``BON-338`` (audit B3)

Allowlisted (legitimate sweep-guard / decision-authority citations):

  * ``src/bonfire/cli/app.py:16``                  — ``BON-345`` sweep-guard
  * ``src/bonfire/cli/commands/persona.py:14``     — ``BON-345`` sweep-guard
  * ``src/bonfire/analysis/models.py`` (BON-347)   — Sage decision/Wave
    citations carried over from the BON-347 port; canonical authority
    pointers, not task-pointer rot.

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
_ALLOWLIST: frozenset[tuple[str, int, str]] = frozenset(
    {
        # --- BON-345 sweep-guards (post-BON-348 cli/ port) -------------
        (
            "cli/app.py",
            16,
            "# BON-345 sweep-guard: avoid the banned default-persona Python literal in",
        ),
        (
            "cli/commands/persona.py",
            14,
            "# BON-345 sweep-guard: avoid emitting the default-persona name as a single",
        ),
        # --- BON-347 analysis port (canonical Sage / Wave citations) --
        (
            "analysis/models.py",
            44,
            '"""Frozen budget of Cartographer tunables (BON-226 §5)."""',
        ),
        (
            "analysis/models.py",
            64,
            "# ─── BON-294 Wave 2c.1 enrichment delta ──────────────────────────",
        ),
        (
            "analysis/models.py",
            94,
            '"``min_length=1`` so an external caller (BON-231 composition root, "',
        ),
        (
            "analysis/models.py",
            106,
            "# ─── BON-294 Wave 2c.1 enrichment delta ──────────────────────────",
        ),
        (
            "analysis/models.py",
            206,
            "# BON-303 Wave 3a.4 — discovered gaps for DiscoveredIntentSource.",
        ),
        (
            "analysis/models.py",
            214,
            "# BON-294 Wave 2c.1 A10 — reject v1 cache blobs so Wave 2b cache",
        ),
        (
            "analysis/models.py",
            222,
            '"""Gzip-compressed JSON — BON-231 Wave 2b cache seam.',
        ),
    }
)


def _iter_python_files(root: Path) -> list[Path]:
    """Return all .py files under *root*, excluding __pycache__."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _is_allowlisted(rel_path: str, lineno: int, line: str) -> bool:
    """True iff the offender matches an allowlist entry."""
    stripped = line.lstrip()
    for allowed_path, allowed_line, allowed_prefix in _ALLOWLIST:
        if allowed_path == rel_path and allowed_line == lineno and stripped.startswith(allowed_prefix):
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
            stale.append((rel_path, lineno, f"<expected prefix {expected_prefix!r}, got {actual!r}>"))

    assert not stale, (
        "Allowlist entries no longer match source — refactor drift detected:\n"
        + "\n".join(f"  src/bonfire/{p}:{n}: {info}" for p, n, info in stale)
    )
