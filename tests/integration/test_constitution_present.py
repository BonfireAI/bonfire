"""BON-541 — bonfire-public/CLAUDE.md repo constitution: presence + structure.

RED smoke test for the Knight phase. Asserts the customer-facing constitution
file exists at ``bonfire-public/CLAUDE.md`` and carries the fourteen-section
structure ratified by Sage §C.1 (Q1.C hybrid template) + override record line 48.

The test is module-level skipped when ``CLAUDE.md`` is absent so the suite
stays green during the Knight RED phase. Once the Warrior writes the file
(per Sage §D.1–§D.15), the skip-guard releases and the assertions evaluate.

Sources:
- ``ishtar/grimoire/design/2026-04-28-bon-541-bonfire-public-constitution-decision.md``
  §C.1 (full structure outline) + §A.Q6 (length target 350–450).
- ``ishtar/grimoire/scratch/splatter-wave-2/wave-2-ratification-overrides.md``
  §BON-541 Q1 (14-section hybrid template ratified, all greens).
- BON-541 acceptance criteria (Linear ticket).
"""

from __future__ import annotations

import pathlib

import pytest

# Resolve the constitution path relative to this test file.
# tests/integration/test_constitution_present.py → parents[2] is the worktree root,
# whose ``CLAUDE.md`` is the repo constitution under construction.
CLAUDE_MD = pathlib.Path(__file__).resolve().parents[2] / "CLAUDE.md"

pytestmark = pytest.mark.skipif(
    not CLAUDE_MD.exists(),
    reason="bonfire-public/CLAUDE.md not yet written (BON-541 Warrior phase pending)",
)

# Section headings ratified per Sage §C.1 (Q1.C hybrid template). Order matters
# only in the source doc; this test asserts presence of each heading line so the
# Warrior is free to keep the §C.1 ordering. Heading text is exact (level-2 ``##``
# for sections, level-1 ``#`` for the title) per Sage §C.1.
REQUIRED_HEADINGS: tuple[str, ...] = (
    "# Bonfire — Public Tree (v0.1)",
    "## Architecture",
    "## Tech Stack",
    "## TDD Is the Law",
    "## Virtual Environment",
    "## ADR-001 Naming Vocabulary",
    "## Canon Awareness",
    "## Agent Commit Protocol",
    "## Worktree Merge Protocol",
    "## Worktree Rules",
    "## Conventions",
    "## Release Policy and Gates",
    "## v0.1 Branch Protection",
    "## For External Contributors",
    "## Links Upward",
)

# Sage §A.Q6 ratified target: 350–450 lines (target band). Override record §BON-541
# Q6 stamps this. Allow ±50 line slack (300–500) for prose/blank-line variance,
# matching the "Wizard latitude" clause in §A.Q6 (drop §Worktree Merge Protocol
# for ~300 / expand §For External Contributors for ~500).
LENGTH_MIN = 300
LENGTH_MAX = 500


def test_constitution_file_exists() -> None:
    """The customer-facing constitution must exist at ``bonfire-public/CLAUDE.md``.

    BON-541 AC #1: file present at the public-tree repo root. The skip-guard
    above means this assertion only fires when the file IS present — but the
    explicit assertion documents the contract for a reader.
    """
    assert CLAUDE_MD.is_file(), (
        f"Expected bonfire-public/CLAUDE.md at {CLAUDE_MD}, file not found. "
        f"BON-541 Warrior must create this file per Sage §D.1–§D.15."
    )


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_constitution_contains_required_heading(heading: str) -> None:
    """Each Q1.C-ratified section heading must appear verbatim in the file.

    Sage §C.1 locks the fourteen-section structure (plus title). Each heading
    is asserted as a line-anchored substring so the Warrior cannot satisfy
    ``## Architecture`` by writing only ``### Architecture sub-heading`` deeper
    in the file.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    lines = body.splitlines()
    assert heading in lines, (
        f"CLAUDE.md missing required heading line: {heading!r}. "
        f"Per Sage §C.1 (Q1.C hybrid template, ratified Wave 2), the file must "
        f"carry all 14 sections + title. Verify the heading is on its own line "
        f"with the exact level (#/##) shown."
    )


def test_constitution_length_within_target_band() -> None:
    """File length must fall within Sage §A.Q6 target band (300–500 lines).

    Sage target: 350–450 lines. Wizard latitude: ±50 lines for terser/richer
    variants per §A.Q6 (drop §Worktree Merge Protocol → ~300; expand
    §For External Contributors → ~500). Outside this band signals either
    section omission (too short) or scope creep (too long).
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    assert LENGTH_MIN <= line_count <= LENGTH_MAX, (
        f"CLAUDE.md is {line_count} lines; Sage §A.Q6 target band is "
        f"{LENGTH_MIN}–{LENGTH_MAX} (target 350–450 + Wizard latitude). "
        f"Either a §C.1 section was omitted ({line_count} < {LENGTH_MIN}) "
        f"or content drifted out of scope ({line_count} > {LENGTH_MAX})."
    )
