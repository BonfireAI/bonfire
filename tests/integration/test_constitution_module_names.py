"""bonfire-public CLAUDE.md must list the public-tree module names.

Asserts the ADR-001 Naming Vocabulary section in CLAUDE.md contains each
renamed module's PUBLIC tree name and marks the legacy PRIVATE names as
forbidden targets. Catches the drift class where legacy plurals (vault,
costs, workflows) bleed into the constitution because a fresh paste
defaults to the legacy CLAUDE.md.

The test is module-level skipped when ``CLAUDE.md`` is absent so the
suite stays green during the RED phase of any future rewrite. Once the
file is present, the skip-guard releases.

Note: ``workflow/`` is singular in the rename table even though the
public-tree filesystem currently has ``workflows/`` plural at HEAD; the
atomic rename is in flight and tracked as a separate follow-up. This
test asserts the post-rename intended state.

Sources:
- ``docs/adr/ADR-001-naming-vocabulary.md`` §Module Renames —
  the binding rename table.
"""

from __future__ import annotations

import pathlib

import pytest

# tests/integration/test_constitution_module_names.py → parents[2] is the worktree root.
CLAUDE_MD = pathlib.Path(__file__).resolve().parents[2] / "CLAUDE.md"

pytestmark = pytest.mark.skipif(
    not CLAUDE_MD.exists(),
    reason="bonfire-public/CLAUDE.md not yet written",
)

# Public-tree module names per ADR-001 §Module Renames.
# Each token must appear at least once in the constitution body.
# ``workflow/`` is singular per ADR-001 (post-rename intended state;
# atomic rename follow-up in flight).
REQUIRED_PUBLIC_TOKENS: tuple[str, ...] = (
    "knowledge/",
    "cost/",
    "workflow/",
    "analysis/",
    "onboard/",
    "scan/",
)

# Legacy PRIVATE names that must NOT appear as the renamed-to target.
# They MAY appear as the "do NOT use" column of the rename table; the
# second test below enforces that contextual framing.
FORBIDDEN_LEGACY_TOKENS: tuple[str, ...] = (
    "vault/",
    "costs/",
    "workflows/",  # in flight (atomic rename follow-up)
    "cartographer/",
    "front_door/",
    "scanners/",
)


@pytest.mark.parametrize("token", REQUIRED_PUBLIC_TOKENS)
def test_constitution_contains_public_tree_module_name(token: str) -> None:
    """Each public-tree module name must appear at least once in CLAUDE.md.

    The constitution embeds an inline summary of the ADR-001 §Module
    Renames table. A grep for each public-tree token (left column of
    the rename table) is the boot-time-drift detector.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    assert token in body, (
        f"CLAUDE.md missing public-tree module name {token!r}. "
        f"Per ADR-001 §Module Renames inline rename table, this "
        f"token MUST appear in the constitution. The defect class this "
        f"test catches: a reviewer pastes legacy plural names into the "
        f"public constitution."
    )


def test_constitution_marks_legacy_names_as_forbidden_targets() -> None:
    """Legacy names may appear ONLY in the rename-table 'do NOT use' framing.

    Per ADR-001's rename-table layout, columns are ``Public (use this)``
    and ``Legacy (do NOT use)``. If a legacy token appears in the file,
    the ``do NOT use`` table-header text MUST also appear so a reader
    sees the rename framing. Without that framing, a legacy plural in
    the constitution body is an unmarked drift defect.
    """
    body = CLAUDE_MD.read_text(encoding="utf-8")
    found_forbidden = [token for token in FORBIDDEN_LEGACY_TOKENS if token in body]
    if found_forbidden:
        assert "do NOT use" in body, (
            f"CLAUDE.md contains legacy module names {found_forbidden!r} but "
            f"the rename-table marker 'do NOT use' is absent. Legacy "
            f"tokens may appear ONLY inside the rename table's 'do NOT use' "
            f"column. An unmarked legacy plural is exactly the drift defect "
            f"this constitution check was filed to prevent."
        )
