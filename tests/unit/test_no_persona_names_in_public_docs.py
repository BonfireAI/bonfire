"""RED sweep test — no person-name refs in the public docs surface (BON-1035, W7.C).

Locks in the v0.1.0-gate ship blocker: public docs must NOT identify the
human operators by name. Cadre/role vocabulary (Blacksmith King, Prompt
Architect, Wizard, Bard, etc.) stays on-canon per ADR-001 — only person
identification is scrubbed.

**Scope.** The Gate-7 docs-surface, as defined in ``docs/release-gates.md``
(see the "Re-publish checklist" section), is **``docs/`` recursively PLUS
the four root markdown files** ``README.md``, ``CHANGELOG.md``,
``CONTRIBUTING.md``, ``CLAUDE.md``. Earlier versions of this sweep walked
only ``docs/``; that left the four root files unguarded and let
person-name refs slip into the very surface the gate text claims to
cover. The scope here matches the gate text exactly.

**Regex.** ``\\b(Anta|Ishtar|Passelewe)\\b`` with ``re.IGNORECASE``.
Case-insensitive matching catches lowercase variants that appear in
file paths (``docs/_lore/passelewe.md``, ``ishtar/CLAUDE.md``) and in
quoted historical strings (``"passelewe"`` in CHANGELOG). Each such hit
is a *real* person-name reference that should either be reframed or
allowlisted with rationale — it should not pass silently because of a
capitalisation gap.

**Carve-out.** ``antawari/`` (the git-branch namespace used in
``docs/release-gates.md`` sample feature-branch paths like
``antawari/bon-<n>-*``) is NOT matched by the regex because ``\\b``
anchors require word boundaries on both sides of the candidate token —
in ``antawari`` there is no boundary after ``Anta`` (the next char ``w``
is a word char), so the regex never fires. We keep an explicit
allowlist entry for that line anyway, as documentation that the carve-
out is intentional (belt-and-suspenders against future regex broadening).

**Allowlist matching.** Entries are matched with **full-line equality
after ``.strip()``** (whitespace trimmed from both ends, then ``==``).
Previously the allowlist matched with ``.lstrip().startswith(prefix)``,
which silently tolerated trailing edits to the allowlisted line. Full-
line equality means: ANY edit to a breadcrumb line — adding a word,
changing punctuation, shifting indentation — invalidates the allowlist
entry and forces a re-confirmation. That's the durability we want:
every person-name reference in the gate-7 docs surface costs an explicit
allowlist entry, and that entry stays honest against drift.

The allowlist is keyed by ``(relative_path_from_repo_root, line_number,
expected_full_line_stripped)``. Mismatch on any field causes the test
to fail.

Reads files on disk only — no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_DIR = _REPO_ROOT / "docs"

# Root markdown files that are part of the Gate-7 docs surface
# (per docs/release-gates.md "Re-publish checklist"). These are scanned
# in addition to docs/ recursively.
_ROOT_DOC_FILES: tuple[str, ...] = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CLAUDE.md",
)

# Regex matching person-name refs (whole-word, case-insensitive).
# Case-insensitive catches lowercase variants in file paths and quoted
# historical strings; the word-boundary anchors leave ``antawari``
# (where ``Anta`` is not a whole word) deliberately unmatched.
# Cadre/role names are multi-word phrases (Blacksmith King, Prompt
# Architect) and are not matched by this pattern, so they pass through
# untouched.
_PERSON_NAME = re.compile(r"\b(Anta|Ishtar|Passelewe)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
# Each entry = (relative_path_from_repo_root, line_number, expected_full_line).
# ``expected_full_line`` is matched with ``line.strip() == expected_full_line``
# (full-line equality after stripping leading/trailing whitespace).
#
# Rationale categories:
# - ``docs/_lore/`` is the canonical archived-breadcrumb space per
#   [[history-is-sacred]] — predecessor personas get preserved origin
#   pages forever. "Passelewe" appearances there are persona-name refs
#   (the in-universe character), not refs to the human operator.
# - Root-doc references to "Passelewe" name the *retired predecessor
#   persona* explicitly, as part of the history-is-sacred breadcrumb
#   that points readers at ``docs/_lore/passelewe.md``. The retired-
#   persona builtins path (``src/bonfire/persona/builtins/passelewe/``)
#   and the quoted ``"passelewe"`` literal in CHANGELOG are the same
#   class: historical-state descriptions, not active references.
# - ``CLAUDE.md`` workspace/forge pointers reference operator-local
#   constellation paths (``/home/ishtar/Projects/CLAUDE.md`` and
#   ``ishtar/CLAUDE.md``). These are documented constellation breadcrumbs
#   per the "Links Upward" section — they tell readers where the
#   governance layers above this file live.
# - ``docs/release-gates.md`` sample feature-branch path
#   (``antawari/bon-<n>-*``) is the canonical naming pattern for the
#   release-train lifecycle diagram. The regex's word boundaries do not
#   match ``antawari`` (no boundary after ``Anta``), so this entry is
#   defensive documentation rather than load-bearing.
_ALLOWLIST: frozenset[tuple[str, int, str]] = frozenset(
    {
        # --- docs/_lore/passelewe.md — predecessor-persona lore page ----
        # The whole file is the archived breadcrumb for the retired
        # Passelewe persona. Every line referring to her by name is
        # in-universe lore, not operator identification.
        ("docs/_lore/passelewe.md", 6, "# Passelewe — Lore"),
        (
            "docs/_lore/passelewe.md",
            8,
            "Passelewe was the first persona to ship in this source tree. She is now",
        ),
        (
            "docs/_lore/passelewe.md",
            16,
            "Passelewe was the Chamberlain of a forge that never finished its own walls.",
        ),
        (
            "docs/_lore/passelewe.md",
            29,
            "Inspired by John Le Mesurier as Passelewe in *Jabberwocky* (1977, Terry",
        ),
        ("docs/_lore/passelewe.md", 32, "## The Seven Laws of Passelewe's Voice"),
        ("docs/_lore/passelewe.md", 58, "## What Passelewe Is NOT"),
        (
            "docs/_lore/passelewe.md",
            69,
            "Falcor's persona slot in this tree is a refactor of Passelewe's mechanics —",
        ),
        (
            "docs/_lore/passelewe.md",
            71,
            "Where Passelewe is duty-loyal and deadpan, Falcor is luck-loyal and gentle.",
        ),
        # --- README.md — predecessor-persona breadcrumb -----------------
        # Two-line breadcrumb pointing readers at docs/_lore/passelewe.md
        # per history-is-sacred. Names the retired persona explicitly
        # (line 278) and the lore-page path (line 279) so the lineage
        # is discoverable. W9 Lane B (H2): line numbers shifted from
        # 271/272 → 278/279 when the dead ``--persona`` example was
        # removed and replaced by a multi-line explanatory note.
        (
            "README.md",
            278,
            "predecessor named Passelewe. History is sacred — see",
        ),
        (
            "README.md",
            279,
            "`docs/_lore/passelewe.md` if you want the lineage.",
        ),
        # --- CHANGELOG.md — predecessor-persona historical entries -----
        # CHANGELOG documents the retirement of the Passelewe persona.
        # The four lines below name her, the historical persona-builtins
        # path, and the quoted persona-name literal that the rename-
        # sweep test bans in src/. All are historical-state descriptions,
        # not active references.
        (
            "CHANGELOG.md",
            422,
            "predecessor persona (Passelewe, the Chamberlain) was retired; the",
        ),
        (
            "CHANGELOG.md",
            424,
            "`docs/_lore/passelewe.md`. The persona builtins directory",
        ),
        (
            "CHANGELOG.md",
            425,
            "`src/bonfire/persona/builtins/passelewe/` was deleted; a new",
        ),
        (
            "CHANGELOG.md",
            442,
            'to ban `"passelewe"` in src/ (the predecessor persona is gone, so',
        ),
        # --- CLAUDE.md — constellation-pointer breadcrumbs --------------
        # Operator-local paths in the "Links Upward" section. They tell
        # readers where the workspace coordinator and forge constitution
        # live in the operator's checkout. Path refs, not person refs.
        # --- docs/release-gates.md — release-train lifecycle diagram ----
        # Sample feature-branch path in the release-train lifecycle
        # diagram. Defensive entry: the regex's word boundaries do not
        # match ``antawari`` (no boundary after ``Anta``), so this entry
        # is documentation of the carve-out, not a live filter. Kept so
        # any future broadening of the regex would surface this line
        # explicitly rather than silently flag it.
        (
            "docs/release-gates.md",
            146,
            "└── antawari/bon-<n>-* feature branches → PR into v0.1",
        ),
    }
)


def _iter_doc_files(repo_root: Path) -> list[Path]:
    """Return all gate-7 docs-surface files.

    Per ``docs/release-gates.md`` "Re-publish checklist", the docs surface
    is ``docs/`` recursively PLUS the four root markdown files
    (``README.md``, ``CHANGELOG.md``, ``CONTRIBUTING.md``, ``CLAUDE.md``).
    """
    files: list[Path] = []
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        # Sweep all regular files; person-name leakage in any doc format
        # (md, rst, txt, etc.) is a ship-blocker. Skip nothing by extension.
        files.extend(p for p in docs_dir.rglob("*") if p.is_file())
    for name in _ROOT_DOC_FILES:
        candidate = repo_root / name
        if candidate.is_file():
            files.append(candidate)
    return files


def _is_allowlisted(rel_path: str, lineno: int, line: str) -> bool:
    """True iff the offender matches an allowlist entry.

    Matching is full-line equality after ``.strip()`` — any edit to the
    line (added word, punctuation change, indentation shift) invalidates
    the allowlist entry and forces a re-confirmation.
    """
    stripped = line.strip()
    for allowed_path, allowed_line, allowed_full in _ALLOWLIST:
        if allowed_path == rel_path and allowed_line == lineno and stripped == allowed_full:
            return True
    return False


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_no_person_name_in_public_docs_outside_allowlist() -> None:
    """No person-name ref may live in the gate-7 docs surface outside the allowlist.

    Scope: ``docs/`` recursively PLUS root files ``README.md``,
    ``CHANGELOG.md``, ``CONTRIBUTING.md``, ``CLAUDE.md`` (per
    ``docs/release-gates.md`` "Re-publish checklist").

    Failure message lists every offender as ``(path, line_no, line_text)``
    so the Warrior can navigate directly. Future legitimate breadcrumbs
    require explicitly extending ``_ALLOWLIST`` above with rationale
    (history-is-sacred archived breadcrumbs only).
    """
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_doc_files(_REPO_ROOT):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary files (images, etc.) — skip.
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _PERSON_NAME.search(line) and not _is_allowlisted(rel, i, line):
                offenders.append((rel, i, line.rstrip()))

    assert not offenders, (
        "Found person-name refs in the gate-7 docs surface outside the allowlist.\n"
        "Each ref must either be reframed to a generic role-name or added "
        "to _ALLOWLIST with rationale (history-is-sacred breadcrumbs only).\n"
        + "\n".join(f"  {p}:{n}: {line}" for p, n, line in offenders)
    )


def test_persona_allowlist_entries_still_resolve() -> None:
    """Every allowlist entry must still match a real line in the docs surface.

    Guards against the allowlist drifting out of sync with the lore.
    If an edit moves, removes, or alters a breadcrumb line, the
    allowlist entry becomes a lie — this test catches that. Full-line
    equality (after ``.strip()``) is intentional: prefix-matching
    silently tolerates trailing edits, full-line equality does not.
    """
    stale: list[tuple[str, int, str]] = []
    for rel_path, lineno, expected_full in _ALLOWLIST:
        full = _REPO_ROOT / rel_path
        if not full.is_file():
            stale.append((rel_path, lineno, f"<file missing: {full}>"))
            continue
        lines = full.read_text(encoding="utf-8").splitlines()
        if lineno < 1 or lineno > len(lines):
            stale.append((rel_path, lineno, f"<out-of-range: file has {len(lines)} lines>"))
            continue
        actual = lines[lineno - 1].strip()
        if actual != expected_full:
            stale.append((rel_path, lineno, f"<expected {expected_full!r}, got {actual!r}>"))

    assert not stale, "Allowlist entries no longer match docs — drift detected:\n" + "\n".join(
        f"  {p}:{n}: {info}" for p, n, info in stale
    )
