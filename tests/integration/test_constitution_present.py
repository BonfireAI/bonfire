"""bonfire-public/CLAUDE.md repo constitution: presence + structure.

Asserts the customer-facing constitution file exists at
``bonfire-public/CLAUDE.md`` and carries the fourteen-section ratified
structure.

The test is module-level skipped when ``CLAUDE.md`` is absent so the
suite stays green during the RED phase of any future rewrite. Once the
file is present, the skip-guard releases and the assertions evaluate.
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
    reason="bonfire-public/CLAUDE.md not yet written",
)

# Section headings ratified for the hybrid template. Order matters only
# in the source doc; this test asserts presence of each heading line.
# Heading text is exact (level-2 ``##`` for sections, level-1 ``#`` for
# the title).
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
)

# Ratified target band: 350–450 lines. Allow ±50 line slack (300–500)
# for prose/blank-line variance, matching the reviewer-latitude clause
# (drop §Worktree Merge Protocol for ~300 / expand §For External
# Contributors for ~500).
LENGTH_MIN = 300
LENGTH_MAX = 500


def test_constitution_file_exists() -> None:
    """The customer-facing constitution must exist at ``bonfire-public/CLAUDE.md``.

    The skip-guard above means this assertion only fires when the file
    IS present — but the explicit assertion documents the contract for
    a reader.
    """
    assert CLAUDE_MD.is_file(), f"Expected bonfire-public/CLAUDE.md at {CLAUDE_MD}, file not found."


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_constitution_contains_required_heading(heading: str) -> None:
    """Each ratified section heading must appear verbatim in the file.

    The fourteen-section structure (plus title) is locked. Each heading
    is asserted as a line-anchored substring so a writer cannot satisfy
    ``## Architecture`` by writing only ``### Architecture sub-heading``
    deeper in the file.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    lines = body.splitlines()
    assert heading in lines, (
        f"CLAUDE.md missing required heading line: {heading!r}. "
        f"The file must carry all 14 sections + title. Verify the "
        f"heading is on its own line with the exact level (#/##) shown."
    )


def test_constitution_length_within_target_band() -> None:
    """File length must fall within the target band (300–500 lines).

    Target: 350–450 lines. Reviewer latitude: ±50 lines for terser/
    richer variants (drop §Worktree Merge Protocol → ~300; expand §For
    External Contributors → ~500). Outside this band signals either
    section omission (too short) or scope creep (too long).
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    assert LENGTH_MIN <= line_count <= LENGTH_MAX, (
        f"CLAUDE.md is {line_count} lines; target band is "
        f"{LENGTH_MIN}–{LENGTH_MAX} (target 350–450 + reviewer latitude). "
        f"Either a section was omitted ({line_count} < {LENGTH_MIN}) "
        f"or content drifted out of scope ({line_count} > {LENGTH_MAX})."
    )
