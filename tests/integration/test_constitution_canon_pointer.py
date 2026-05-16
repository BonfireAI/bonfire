"""bonfire-public CLAUDE.md must include the Canon pointer (four anchors).

Asserts the four NON-NEGOTIABLE Canon-pointer anchor elements live in
the repo constitution. The test is module-level skipped when
``CLAUDE.md`` is absent so the suite stays green during the RED phase
of any future rewrite. Once the file is present, the skip-guard releases.

The four anchors:
    1. Literal substring ``THE CANON`` (uppercase, two words).
    2. Full URL with slug ``331e401a0fbf`` (the grep canary).
    3. Literal phrase ``canonical vocabulary`` (the trigger phrase).
    4. A one-sentence rule of the Canon-wins-on-contradiction form,
       containing both ``consult`` and ``canonical`` (case-insensitive).

These anchors are the same set the upstream cross-repo constellation
test checks via the slug substring. This file's tests are the
bonfire-public-local view of the same contract — the constellation
test asserts presence of the slug from the operator-relative view;
this test asserts the full four-anchor set from the worktree-relative
view.
"""

from __future__ import annotations

import pathlib
import re

import pytest

# tests/integration/test_constitution_canon_pointer.py → parents[2] is worktree root.
CLAUDE_MD = pathlib.Path(__file__).resolve().parents[2] / "CLAUDE.md"

pytestmark = pytest.mark.skipif(
    not CLAUDE_MD.exists(),
    reason="bonfire-public/CLAUDE.md not yet written",
)

# Anchor 1: literal uppercase substring.
CANON_LITERAL = "THE CANON"

# Anchor 2: full URL. Slug ``331e401a0fbf`` is the grep canary.
CANON_SLUG = "331e401a0fbf"
CANON_URL = (
    "https://linear.app/bonfire-codeforge/document/"
    "the-canon-source-of-truth-for-all-surfaces-331e401a0fbf"
)

# Anchor 3: literal trigger phrase.
CANONICAL_VOCABULARY_PHRASE = "canonical vocabulary"

# Anchor 4: one-sentence rule. The sentence must contain both ``consult``
# and ``canonical`` (case-insensitive). Asserted via a sentence-boundary
# regex so a paragraph that uses both words across different sentences
# does NOT satisfy the contract.
RULE_SENTENCE_PATTERN = re.compile(
    r"[^.!?\n]*\bconsult[^.!?\n]*\bcanonical[^.!?\n]*[.!?]"
    r"|[^.!?\n]*\bcanonical[^.!?\n]*\bconsult[^.!?\n]*[.!?]",
    re.IGNORECASE,
)


def test_constitution_contains_literal_the_canon() -> None:
    """Anchor 1: literal uppercase ``THE CANON`` substring."""
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert CANON_LITERAL in body, (
        f"CLAUDE.md missing literal {CANON_LITERAL!r}. The verbatim "
        f"uppercase phrase is a NON-NEGOTIABLE anchor element of the "
        f"Canon pointer."
    )


def test_constitution_contains_canon_url_with_slug() -> None:
    """Anchor 2: full URL with slug ``331e401a0fbf``.

    The slug is the cross-repo constellation test's grep canary;
    presence is NON-NEGOTIABLE. The full URL is asserted in addition
    so the canon pointer is dereferenceable, not just greppable.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert CANON_SLUG in body, (
        f"CLAUDE.md missing Canon slug {CANON_SLUG!r}. The slug is "
        f"the grep canary the cross-repo constellation test uses to "
        f"catch drift."
    )
    assert CANON_URL in body, (
        f"CLAUDE.md missing full Canon URL. The full URL "
        f"({CANON_URL}) is a NON-NEGOTIABLE anchor element."
    )


def test_constitution_contains_canonical_vocabulary_phrase() -> None:
    """Anchor 3: literal phrase ``canonical vocabulary``."""
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert CANONICAL_VOCABULARY_PHRASE in body, (
        f"CLAUDE.md missing trigger phrase {CANONICAL_VOCABULARY_PHRASE!r}. "
        f"This exact lowercase two-word phrase is a NON-NEGOTIABLE "
        f"anchor element."
    )


def test_constitution_contains_canon_wins_rule_sentence() -> None:
    """Anchor 4: one-sentence rule combining ``consult`` and ``canonical``.

    The pointer must include a one-sentence rule of the Canon-wins-on-
    contradiction form — example: *"Consult THE CANON before touching
    canonical vocabulary..."*. This test asserts at least one sentence
    contains both ``consult`` and ``canonical`` (case-insensitive). A
    paragraph that uses the two words in separate sentences does NOT
    satisfy the contract.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    match = RULE_SENTENCE_PATTERN.search(body)
    assert match is not None, (
        "CLAUDE.md missing the Canon-wins-on-contradiction rule "
        "sentence. The pointer must include a single sentence "
        "containing both 'consult' and 'canonical' (e.g. 'Consult THE "
        "CANON before touching canonical vocabulary...')."
    )
