"""BON-541 — bonfire-public CLAUDE.md must list the public-tree module names.

RED smoke test for the Knight phase. Asserts the §ADR-001 Naming Vocabulary
section in CLAUDE.md contains each renamed module's PUBLIC tree name and marks
the v1 PRIVATE names as forbidden targets. Catches the drift class where v1
plurals (vault, costs, workflows) bleed into the constitution because a fresh
Wizard defaults to v1's CLAUDE.md (Phase A row #24 defect class).

The test is module-level skipped when ``CLAUDE.md`` is absent so the suite
stays green during the Knight RED phase. Once the Warrior writes the file
(per Sage §D.6 + §E.3 contract), the skip-guard releases.

Notes per Wave 2 ratification override record (line 49 — Sage §A.Q2 ratified):
    The constitution describes the POST-RENAME intended state per ADR-001
    (singular ``workflow/``), even though the public-tree filesystem currently
    has ``workflows/`` plural at HEAD. The atomic rename is filed as BON-637
    (parent BON-541, formerly BON-FUP-541-MODULE-RENAME). This test asserts
    the post-rename state Sage locked.

Sources:
- ``ishtar/grimoire/design/2026-04-28-bon-541-bonfire-public-constitution-decision.md``
  §A.Q2 (Q2.C hybrid: inline summary + path citation) + §D.6 (rename table) +
  §E.3 (drift mitigation contract for this exact test).
- ``ishtar/grimoire/scratch/splatter-wave-2/wave-2-ratification-overrides.md``
  §BON-541 Q2 + §B.0 drift-catch (BON-637 follow-up).
- ``bonfire-public/docs/adr/ADR-001-naming-vocabulary.md`` §Module Renames
  lines 44–51 (the binding rename table).
"""

from __future__ import annotations

import pathlib

import pytest

# tests/integration/test_constitution_module_names.py → parents[2] is the worktree root.
CLAUDE_MD = pathlib.Path(__file__).resolve().parents[2] / "CLAUDE.md"

pytestmark = pytest.mark.skipif(
    not CLAUDE_MD.exists(),
    reason="bonfire-public/CLAUDE.md not yet written (BON-541 Warrior phase pending)",
)

# Public-tree module names per ADR-001 §Module Renames lines 44–51.
# Each token must appear at least once in the constitution body.
# ``workflow/`` is singular per ADR-001 line 49 (post-rename intended state per
# Wave 2 override record + BON-637 follow-up).
REQUIRED_PUBLIC_TOKENS: tuple[str, ...] = (
    "knowledge/",
    "cost/",
    "workflow/",
    "analysis/",
    "onboard/",
    "scan/",
)

# v1 PRIVATE names that must NOT appear as the renamed-to target. They MAY appear
# as the "do NOT use" column of the rename table (Sage §D.6 layout); the second
# test below enforces that contextual framing.
FORBIDDEN_V1_TOKENS: tuple[str, ...] = (
    "vault/",
    "costs/",
    "workflows/",  # in flight per BON-637 (parent BON-541) — Sage §A.Q2 + §B.0
    "cartographer/",
    "front_door/",
    "scanners/",
)


@pytest.mark.parametrize("token", REQUIRED_PUBLIC_TOKENS)
def test_constitution_contains_public_tree_module_name(token: str) -> None:
    """Each public-tree module name must appear at least once in CLAUDE.md.

    Per Sage §A.Q2 (Q2.C hybrid) and §D.6 (rename table), the constitution
    embeds an inline summary of the ADR-001 §Module Renames table. A grep for
    each public-tree token (left column of the rename table) is the
    boot-time-drift detector promised by §E.3.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert token in body, (
        f"CLAUDE.md missing public-tree module name {token!r}. "
        f"Per ADR-001 §Module Renames + Sage §D.6 inline rename table, this "
        f"token MUST appear in the constitution. The defect class this test "
        f"catches: a Wizard pastes v1 plural names into the public constitution."
    )


def test_constitution_marks_v1_names_as_forbidden_targets() -> None:
    """v1 names may appear ONLY in the rename-table 'do NOT use' framing.

    Per Sage §D.6 layout, the rename table has columns ``Public (use this)`` and
    ``Private v1 (do NOT use)``. If a v1 token appears in the file, the
    ``do NOT use`` table-header text MUST also appear so a reader sees the
    rename framing. Without that framing, a v1 plural in the constitution
    body is an unmarked drift defect.

    Mirrors Sage §E.3's two-test split (REQUIRED + FORBIDDEN-context).
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    found_forbidden = [token for token in FORBIDDEN_V1_TOKENS if token in body]
    if found_forbidden:
        assert "do NOT use" in body, (
            f"CLAUDE.md contains v1 module names {found_forbidden!r} but the "
            f"rename-table marker 'do NOT use' is absent. Per Sage §D.6, v1 "
            f"tokens may appear ONLY inside the rename table's 'do NOT use' "
            f"column. An unmarked v1 plural is exactly the drift defect "
            f"BON-541 was filed to prevent."
        )
