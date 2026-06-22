# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Lock the standard_build() stage count and stage-name sequence.

Four doc surfaces describe the standard pipeline (architecture.md,
pipeline-stages.md, product/discipline.md, and this package's own
docstring). When the code drifts from those docs, this test fails first
so the doc surfaces are updated in lockstep with the code.
"""

from __future__ import annotations

from bonfire.workflow import standard_build

EXPECTED_STAGES: tuple[str, ...] = (
    "scout",
    "knight",
    "warrior",
    "prover",
    "sage_correction_bounce",
    "bard",
    "wizard",
    "merge_preflight",
    "steward",
)


def test_standard_build_stage_count_and_names() -> None:
    stages = standard_build().stages
    assert len(stages) == 9, (
        f"standard_build() returned {len(stages)} stages, expected 9. "
        "If you changed the stage count, update docs/architecture.md, "
        "docs/pipeline-stages.md, docs/product/discipline.md, and the "
        "bonfire.workflow package docstring in lockstep."
    )
    names = tuple(stage.name for stage in stages)
    assert names == EXPECTED_STAGES, (
        f"Stage sequence diverged from documented canonical order.\n"
        f"  Got:      {names}\n"
        f"  Expected: {EXPECTED_STAGES}\n"
        "Update the four doc surfaces named in the docstring above and re-run."
    )
