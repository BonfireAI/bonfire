"""BON-541 — bonfire-public CLAUDE.md must include the BON-540 Canon pointer.

RED smoke test for the Knight phase. Asserts the four NON-NEGOTIABLE Canon
anchor elements ratified in BON-540 §F.1 + BON-541 §F.1 (Q5 closed upstream by
Wave 1 R1 ratification on 2026-04-28). Each anchor is a verbatim string the
Warrior must paste from Sage §D.7.

The test is module-level skipped when ``CLAUDE.md`` is absent so the suite
stays green during the Knight RED phase. Once the Warrior writes the file
(per Sage §D.7 verbatim block), the skip-guard releases.

The four anchors per BON-540 §F.1 + BON-541 §F.1:
    1. Literal substring ``THE CANON`` (uppercase, two words).
    2. Full URL with slug ``331e401a0fbf`` (the grep canary).
    3. Literal phrase ``canonical vocabulary`` (the trigger phrase).
    4. A one-sentence rule of the Canon-wins-on-contradiction form, containing
       both ``consult`` and ``canonical`` (case-insensitive).

These anchors are the same set the BON-540 cross-repo constellation test
(``bonfire/tests/integration/test_canon_constellation.py``) checks via the
slug substring. This file's tests are the bonfire-public-local view of the
same contract — the constellation test asserts presence of the slug from the
operator-relative view; this test asserts the full four-anchor set from the
worktree-relative view.

Sources:
- ``ishtar/grimoire/design/2026-04-27-bon-540-canon-pointer-decision.md`` §F.1
  (the verbatim-text source).
- ``ishtar/grimoire/design/2026-04-28-bon-541-bonfire-public-constitution-decision.md``
  §D.7 (the verbatim block Warrior pastes) + §F.1 (the four anchor elements,
  NON-NEGOTIABLE per BON-540 §F.2 drift-detection promise).
- ``ishtar/grimoire/scratch/splatter-wave-2/wave-2-ratification-overrides.md``
  §BON-541 Q5 (closed upstream).
- BON-540 Linear ticket comment id ``49a8f0a5-17f6-4264-8934-c0eb303cfbe9``
  (Bard-posted §F constraint annotation on BON-541).
"""

from __future__ import annotations

import pathlib
import re

import pytest

# tests/integration/test_constitution_canon_pointer.py → parents[2] is worktree root.
CLAUDE_MD = pathlib.Path(__file__).resolve().parents[2] / "CLAUDE.md"

pytestmark = pytest.mark.skipif(
    not CLAUDE_MD.exists(),
    reason="bonfire-public/CLAUDE.md not yet written (BON-541 Warrior phase pending)",
)

# Anchor 1: literal uppercase substring.
CANON_LITERAL = "THE CANON"

# Anchor 2: full URL. Slug ``331e401a0fbf`` is the grep canary BON-540 §G.2 uses.
CANON_SLUG = "331e401a0fbf"
CANON_URL = (
    "https://linear.app/bonfire-codeforge/document/"
    "the-canon-source-of-truth-for-all-surfaces-331e401a0fbf"
)

# Anchor 3: literal trigger phrase.
CANONICAL_VOCABULARY_PHRASE = "canonical vocabulary"

# Anchor 4: one-sentence rule. Per BON-540 §F.1 example
# ("Consult THE CANON before touching canonical vocabulary..."), the sentence
# must contain both ``consult`` and ``canonical`` (case-insensitive). Asserted
# via a sentence-boundary regex so a paragraph that uses both words across
# different sentences does NOT satisfy the contract.
RULE_SENTENCE_PATTERN = re.compile(
    r"[^.!?\n]*\bconsult[^.!?\n]*\bcanonical[^.!?\n]*[.!?]"
    r"|[^.!?\n]*\bcanonical[^.!?\n]*\bconsult[^.!?\n]*[.!?]",
    re.IGNORECASE,
)


def test_constitution_contains_literal_the_canon() -> None:
    """Anchor 1: literal uppercase ``THE CANON`` substring (BON-540 §F.1.1)."""
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert CANON_LITERAL in body, (
        f"CLAUDE.md missing literal {CANON_LITERAL!r}. Per BON-540 §F.1.1, "
        f"the verbatim uppercase phrase is a NON-NEGOTIABLE anchor element of "
        f"the Canon pointer. Paste from Sage §D.7."
    )


def test_constitution_contains_canon_url_with_slug() -> None:
    """Anchor 2: full URL with slug ``331e401a0fbf`` (BON-540 §F.1.2).

    The slug is the cross-repo constellation test's grep canary; presence is
    NON-NEGOTIABLE. The full URL is asserted in addition because BON-540 §F.1.2
    requires it verbatim.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert CANON_SLUG in body, (
        f"CLAUDE.md missing Canon slug {CANON_SLUG!r}. Per BON-540 §F.1.2 "
        f"and §G.2 cross-repo constellation test, the slug is the grep canary "
        f"that catches drift. Paste the full URL from Sage §D.7."
    )
    assert CANON_URL in body, (
        f"CLAUDE.md missing full Canon URL. Per BON-540 §F.1.2, the full URL "
        f"({CANON_URL}) is a NON-NEGOTIABLE anchor element. Paste verbatim "
        f"from Sage §D.7."
    )


def test_constitution_contains_canonical_vocabulary_phrase() -> None:
    """Anchor 3: literal phrase ``canonical vocabulary`` (BON-540 §F.1.3)."""
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert CANONICAL_VOCABULARY_PHRASE in body, (
        f"CLAUDE.md missing trigger phrase {CANONICAL_VOCABULARY_PHRASE!r}. "
        f"Per BON-540 §F.1.3, this exact lowercase two-word phrase is a "
        f"NON-NEGOTIABLE anchor element. Paste from Sage §D.7."
    )


def test_constitution_contains_canon_wins_rule_sentence() -> None:
    """Anchor 4: one-sentence rule combining ``consult`` and ``canonical``.

    Per BON-540 §F.1.4, the pointer must include a one-sentence rule of the
    Canon-wins-on-contradiction form — example: *"Consult THE CANON before
    touching canonical vocabulary..."*. This test asserts at least one sentence
    contains both ``consult`` and ``canonical`` (case-insensitive). A paragraph
    that uses the two words in separate sentences does NOT satisfy the contract.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    match = RULE_SENTENCE_PATTERN.search(body)
    assert match is not None, (
        "CLAUDE.md missing the Canon-wins-on-contradiction rule sentence. "
        "Per BON-540 §F.1.4, the pointer must include a single sentence "
        "containing both 'consult' and 'canonical' (e.g. 'Consult THE CANON "
        "before touching canonical vocabulary...'). Paste verbatim from Sage "
        "§D.7."
    )
