# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Workflow definitions — pure data factories.

This package provides pre-built workflow plans for common patterns:

- **standard_build**: Full 9-stage TDD pipeline (scout, knight, warrior,
  prover, sage_correction_bounce, bard, wizard, merge_preflight, steward)
- **debug**: Minimal 2-stage quick iteration loop
- **dual_scout**: Two parallel scouts + sage synthesis
- **triple_scout**: Three parallel scouts + sage synthesis
- **spike**: Pure research — scouts + sage, no implementation

All factories return frozen, DAG-validated WorkflowPlan instances.
Depends only on bonfire.models — no engine, dispatch, or handler imports.

The standard 9-stage sequence is pinned by
``tests/unit/test_workflow_stage_count.py``. If you change the stage
count or names, update that test and the four doc surfaces it names in
lockstep.
"""

from bonfire.workflow.registry import WorkflowRegistry, get_default_registry
from bonfire.workflow.research import dual_scout, spike, triple_scout
from bonfire.workflow.standard import debug, standard_build

__all__ = [
    "WorkflowRegistry",
    "debug",
    "dual_scout",
    "get_default_registry",
    "spike",
    "standard_build",
    "triple_scout",
]
