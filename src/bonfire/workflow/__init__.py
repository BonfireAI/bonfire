# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Workflow definitions — pure data factories.

This package provides pre-built workflow plans for common patterns:

- **standard_build**: Full 7-stage TDD pipeline (scout through herald)
- **debug**: Minimal 2-stage quick iteration loop
- **dual_scout**: Two parallel scouts + sage synthesis
- **triple_scout**: Three parallel scouts + sage synthesis
- **spike**: Pure research — scouts + sage, no implementation

All factories return frozen, DAG-validated WorkflowPlan instances.
Depends only on bonfire.models — no engine, dispatch, or handler imports.
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
