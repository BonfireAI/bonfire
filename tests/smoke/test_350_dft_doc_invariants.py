"""RED smoke tests — doc-and-style invariants for the 350-cluster follow-ups.

This file locks the contract for FOUR small follow-up tickets that came out
of the 350 cluster doc-polish audit. Every assertion below is currently
``xfail`` because the Warrior has not yet created the target docs / memo
template. As Warrior lands each piece, the corresponding ``xfail`` flips to
``XPASS`` (or the marker is removed in the same PR — either signal is fine).

Contracts (one per ticket):

1. **Sage memo template — no naked ticket-tracker refs**
   When the canonical Sage memo template lives at
   ``docs/audit/sage-decisions/_template-sage-memo.md``, no ``BON-\\d+`` literal
   may appear inside a fenced sample-code block in that template. Citations
   in prose are fine; sample-code blocks must paraphrase ("ticket-NNN" or
   similar) so a copy-paste does NOT seed a fresh memo with stale refs.

2. **Sage memo template — D8 prose-vs-list parity**
   The same template, IF it contains a ``## D8 — Test surface`` section AND
   that section contains a prose total of the form ``= NN net-new tests``
   (or equivalent ``NN tests total``), the explicit ``test_*`` identifiers
   listed in fenced blocks under §D8 must MATCH that count exactly.

3. **`# ---` section-divider style decision codified**
   ``docs/style.md`` exists and contains a section that mentions
   ``# ---`` and an explicit allow / forbid verdict. Conservative call:
   ALLOW (existing source already uses both ``# ---`` and ``# ───``
   dividers; outright forbidding would force a sweep we don't have
   appetite for at v0.1).

4. **Wizard pre-stage step documented**
   ``docs/contributor-guide/wizard-pre-stage.md`` exists and contains
   the canonical phrase ``pip install -e`` together with a reference to
   the Warrior's worktree, so a fresh-boot agent reads the editable-install
   step before reviewing a PR built on a worktree branch.

5. **Memo templates do not lean on `# type: ignore[assignment]`**
   No file under ``docs/audit/sage-decisions/`` whose stem starts with
   ``_template`` (i.e. canonical templates, not historical decisions)
   contains the string ``# type: ignore[assignment]``. The pattern
   "explicit ``Optional[T]`` annotation, then ``.get()`` reassign" is
   the project convention; suppressions are not.

All checks read files on disk only. No subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo root = ``repo/tests/smoke/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAGE_DIR = _REPO_ROOT / "docs" / "audit" / "sage-decisions"
_TEMPLATE_PATH = _SAGE_DIR / "_template-sage-memo.md"
_STYLE_DOC = _REPO_ROOT / "docs" / "style.md"
_WIZARD_PRE_STAGE_DOC = _REPO_ROOT / "docs" / "contributor-guide" / "wizard-pre-stage.md"

_BON_REF = re.compile(r"BON-\d+")
_FENCED_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_TEST_IDENT = re.compile(r"\btest_[A-Za-z0-9_]+")
_PROSE_COUNT = re.compile(r"(\d+)\s*(?:net-new\s+tests|tests\s+total)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 1. Sage memo template — no naked ticket-tracker refs in sample-code blocks
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    condition=not _TEMPLATE_PATH.is_file(),
    reason=(
        "Canonical Sage memo template not yet created at "
        "docs/audit/sage-decisions/_template-sage-memo.md (Warrior writes it)."
    ),
    strict=False,
)
def test_sage_template_sample_code_blocks_have_no_naked_ticket_refs() -> None:
    """Sample-code blocks in the Sage memo template must paraphrase ticket refs.

    A fresh agent copying a fenced block as a starting point should NOT
    seed their new memo with stale ``BON-NNN`` strings. Prose mentions
    outside fenced blocks are fine — they are citations, not templates.
    """
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    offenders: list[str] = []
    for match in _FENCED_BLOCK.finditer(text):
        block_body = match.group(1)
        for ref in _BON_REF.findall(block_body):
            offenders.append(ref)
    assert not offenders, (
        "Sage memo template has naked BON-NNN refs in fenced sample-code blocks; "
        "paraphrase them (e.g. 'ticket-NNN' or '<ticket>'):\n  " + ", ".join(sorted(set(offenders)))
    )


# ---------------------------------------------------------------------------
# 2. Sage memo template — §D8 prose-vs-list parity
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    condition=not _TEMPLATE_PATH.is_file(),
    reason=(
        "Canonical Sage memo template not yet created at "
        "docs/audit/sage-decisions/_template-sage-memo.md (Warrior writes it)."
    ),
    strict=False,
)
def test_sage_template_d8_prose_count_matches_list_count() -> None:
    """If the Sage memo template has a §D8 Test surface section, the prose
    total must match the count of explicit ``test_*`` identifiers listed
    in that section's fenced blocks. A drift between the two is the exact
    bug class this guard exists to prevent.
    """
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    # Find §D8 section (heading "## D8" through next "## " heading or EOF).
    d8_match = re.search(
        r"^##\s*D8[^\n]*\n(.*?)(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if d8_match is None:
        pytest.skip("Template has no §D8 section yet; parity check is conditional.")
    d8_body = d8_match.group(1)
    prose_match = _PROSE_COUNT.search(d8_body)
    assert prose_match is not None, (
        "§D8 has no prose total of the form 'NN net-new tests' or 'NN tests total'; "
        "add one so list-vs-prose parity is checkable."
    )
    prose_count = int(prose_match.group(1))
    listed: set[str] = set()
    for match in _FENCED_BLOCK.finditer(d8_body):
        for ident in _TEST_IDENT.findall(match.group(1)):
            listed.add(ident)
    assert prose_count == len(listed), (
        f"§D8 parity drift: prose says {prose_count} tests, explicit list has "
        f"{len(listed)}. Fix one or the other before merging."
    )


# ---------------------------------------------------------------------------
# 3. `# ---` section-divider style decision codified in docs/style.md
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    condition=not _STYLE_DOC.is_file(),
    reason="docs/style.md not yet created (Warrior writes it).",
    strict=False,
)
def test_style_doc_documents_section_divider_convention() -> None:
    """``docs/style.md`` must mention ``# ---`` dividers and pick a verdict.

    Conservative pick is ALLOW — both ``# ---`` and ``# ───`` already appear
    in source. Either word ('allow', 'permitted', 'forbid', 'banned')
    satisfies the test; the point is that the call is made and findable.
    """
    text = _STYLE_DOC.read_text(encoding="utf-8").lower()
    assert "# ---" in text or "`# ---`" in text, (
        "docs/style.md must explicitly mention the literal `# ---` divider."
    )
    verdict_words = ("allow", "permitted", "forbid", "banned", "discouraged")
    assert any(word in text for word in verdict_words), (
        "docs/style.md must pick a verdict for `# ---` (allow/permit/forbid/ban/discourage)."
    )


# ---------------------------------------------------------------------------
# 4. Wizard pre-stage step — `pip install -e <warrior-worktree>` documented
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    condition=not _WIZARD_PRE_STAGE_DOC.is_file(),
    reason=("docs/contributor-guide/wizard-pre-stage.md not yet created (Warrior writes it)."),
    strict=False,
)
def test_wizard_pre_stage_doc_documents_editable_install() -> None:
    """The Wizard pre-stage doc must spell out ``pip install -e`` and the
    Warrior worktree as the install target, so the editable-install step
    is discoverable without leaving the public tree.
    """
    text = _WIZARD_PRE_STAGE_DOC.read_text(encoding="utf-8")
    assert "pip install -e" in text, (
        "wizard-pre-stage.md must contain the literal phrase 'pip install -e'."
    )
    lower = text.lower()
    assert "worktree" in lower, (
        "wizard-pre-stage.md must reference the Warrior's worktree as install target."
    )


# ---------------------------------------------------------------------------
# 5. Memo templates avoid `# type: ignore[assignment]`
# ---------------------------------------------------------------------------


def _iter_template_memos(root: Path) -> list[Path]:
    """Return Sage-decision files whose stem starts with ``_template``."""
    if not root.is_dir():
        return []
    return [p for p in root.glob("_template*.md") if p.is_file()]


@pytest.mark.xfail(
    condition=not _TEMPLATE_PATH.is_file(),
    reason=(
        "Canonical Sage memo template not yet created at "
        "docs/audit/sage-decisions/_template-sage-memo.md (Warrior writes it)."
    ),
    strict=False,
)
def test_sage_templates_avoid_type_ignore_assignment() -> None:
    """No Sage memo template may rely on ``# type: ignore[assignment]`` for
    Optional reassignment patterns. Convention: explicit ``Optional[T]`` on
    the first line, ``.get()`` reassign on the next, no suppression.

    Asserts the canonical template exists (so the contract is anchored)
    AND scans every ``_template*.md`` for the banned suppression.
    """
    assert _TEMPLATE_PATH.is_file(), (
        f"Canonical Sage memo template missing at {_TEMPLATE_PATH.relative_to(_REPO_ROOT)}; "
        "Warrior must create it."
    )
    offenders: list[str] = []
    for path in _iter_template_memos(_SAGE_DIR):
        text = path.read_text(encoding="utf-8")
        if "# type: ignore[assignment]" in text:
            offenders.append(path.relative_to(_REPO_ROOT).as_posix())
    assert not offenders, (
        "Sage memo template(s) lean on `# type: ignore[assignment]`; replace with "
        "explicit Optional[T] annotation:\n  " + "\n  ".join(offenders)
    )
