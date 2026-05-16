"""RED sweep test — no person-name refs in ``docs/`` (BON-1035, W7.C).

Locks in the v0.1.0-gate ship blocker: public docs must NOT identify the
human operators by name. Cadre/role vocabulary (Blacksmith King, Prompt
Architect, Wizard, Bard, etc.) stays on-canon per ADR-001 — only person
identification is scrubbed.

Walks every file under ``docs/`` and scans for the regex
``\\b(Anta|Ishtar|Passelewe)\\b``. Any hit that is NOT in the explicit
allowlist below is an offender — the Warrior must reframe it (or, if it's
a legitimately preserved breadcrumb per [[history-is-sacred]], extend the
allowlist with rationale).

The allowlist is keyed by ``(relative_path, line_number,
expected_substring_prefix)``. The substring prefix is matched against
the START of the offending line (after stripping). Mismatch on any
field causes the test to fail — i.e. if a doc edit shifts an allowlisted
line, the allowlist must be re-confirmed too. That's the durability we
want: every person-name in docs/ costs an explicit allowlist entry.

Reads files on disk only — no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_DIR = _REPO_ROOT / "docs"

# Regex matching person-name refs (whole-word). Cadre/role names are
# multi-word phrases (Blacksmith King, Prompt Architect) and are not
# matched by this pattern, so they pass through untouched.
_PERSON_NAME = re.compile(r"\b(Anta|Ishtar|Passelewe)\b")

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
# Each entry = (relative_path_from_docs, line_number, expected_line_prefix).
# ``expected_line_prefix`` is matched with ``.lstrip().startswith(...)`` so
# whitespace at line start is normalised.
#
# Rationale category: ``docs/_lore/`` is the canonical archived-breadcrumb
# space per [[history-is-sacred]] — predecessor personas get preserved
# origin pages forever. "Passelewe" appearances there are persona-name
# refs (the in-universe character), not refs to the human operator.
_ALLOWLIST: frozenset[tuple[str, int, str]] = frozenset(
    {
        # --- docs/_lore/passelewe.md — predecessor-persona lore page ----
        # The whole file is the archived breadcrumb for the retired
        # Passelewe persona. Every line referring to her by name is
        # in-universe lore, not operator identification.
        ("_lore/passelewe.md", 6, "# Passelewe — Lore"),
        (
            "_lore/passelewe.md",
            8,
            "Passelewe was the first persona to ship in this source tree.",
        ),
        (
            "_lore/passelewe.md",
            16,
            "Passelewe was the Chamberlain of a forge that never finished its own walls.",
        ),
        (
            "_lore/passelewe.md",
            29,
            "Inspired by John Le Mesurier as Passelewe in *Jabberwocky* (1977, Terry",
        ),
        ("_lore/passelewe.md", 32, "## The Seven Laws of Passelewe's Voice"),
        ("_lore/passelewe.md", 58, "## What Passelewe Is NOT"),
        (
            "_lore/passelewe.md",
            69,
            "Falcor's persona slot in this tree is a refactor of Passelewe's mechanics —",
        ),
        (
            "_lore/passelewe.md",
            71,
            "Where Passelewe is duty-loyal and deadpan, Falcor is luck-loyal and gentle.",
        ),
    }
)


def _iter_doc_files(root: Path) -> list[Path]:
    """Return all text-ish files under *root*."""
    if not root.is_dir():
        return []
    # Sweep all regular files; person-name leakage in any doc format
    # (md, rst, txt, etc.) is a ship-blocker. Skip nothing by extension.
    return [p for p in root.rglob("*") if p.is_file()]


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


def test_no_person_name_in_public_docs_outside_allowlist() -> None:
    """No person-name ref may live in ``docs/`` outside the allowlist.

    Failure message lists every offender as ``(path, line_no, line_text)``
    so the Warrior can navigate directly. Future legitimate breadcrumbs
    require explicitly extending ``_ALLOWLIST`` above with rationale
    (history-is-sacred archived breadcrumbs only).
    """
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_doc_files(_DOCS_DIR):
        rel = path.relative_to(_DOCS_DIR).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary files (images, etc.) — skip.
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _PERSON_NAME.search(line) and not _is_allowlisted(rel, i, line):
                offenders.append((rel, i, line.rstrip()))

    assert not offenders, (
        "Found person-name refs in docs/ outside the allowlist.\n"
        "Each ref must either be reframed to a generic role-name or added "
        "to _ALLOWLIST with rationale (history-is-sacred breadcrumbs only).\n"
        + "\n".join(f"  docs/{p}:{n}: {line}" for p, n, line in offenders)
    )


def test_persona_allowlist_entries_still_resolve() -> None:
    """Every allowlist entry must still match a real line in docs.

    Guards against the allowlist drifting out of sync with the lore.
    If an edit moves or removes a breadcrumb line, the allowlist entry
    becomes a lie — this test catches that.
    """
    stale: list[tuple[str, int, str]] = []
    for rel_path, lineno, expected_prefix in _ALLOWLIST:
        full = _DOCS_DIR / rel_path
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
        "Allowlist entries no longer match docs — drift detected:\n"
        + "\n".join(f"  docs/{p}:{n}: {info}" for p, n, info in stale)
    )
