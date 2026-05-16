# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Wave 11 Lane E — ``StageExecutor`` deletion forward-canary (BON-1098).

The dead ``StageExecutor.execute_single`` path diverged from
``PipelineEngine._execute_stage`` over four Probe N+7 findings:

    H1. Unreachable code path — no production caller in
        ``src/bonfire/`` ever instantiated ``StageExecutor``; only the
        re-export at ``bonfire.engine.__init__`` and test files held
        references.
    H2. ``vault_advisor`` was wired only through the dead path; the
        live engine path never queried it.
    H3. The dead path dropped ``initial_envelope.metadata``; the live
        engine path merges it.
    M4. ``model_override`` semantics diverged.

Lane E deletes the entire ``StageExecutor`` class. This canary asserts
the class can no longer be imported, so any future revival has to first
delete this test (which forces a human review of whether the live path
has finally absorbed every responsibility the dead path used to carry).

Symmetric to the Lane D forward-canary at
``tests/unit/test_wave_11_lane_d_handler_runner_invariant.py``: both
canaries lock load-bearing structural invariants the deletion
established, and both are cheap to keep green forever.
"""

from __future__ import annotations

import pytest


class TestStageExecutorDeleted:
    """``StageExecutor`` MUST be absent from both the submodule and the
    public ``bonfire.engine`` surface."""

    def test_stage_executor_not_importable_from_executor_submodule(self) -> None:
        """``from bonfire.engine.executor import StageExecutor`` must
        fail. We accept either ``ImportError`` (module gone) or
        ``AttributeError`` (module survives without the class) so the
        canary tolerates a future caretaker that keeps ``executor.py``
        for other purposes."""
        with pytest.raises((ImportError, ModuleNotFoundError, AttributeError)):
            from bonfire.engine.executor import StageExecutor  # noqa: F401

    def test_stage_executor_not_in_engine_package_namespace(self) -> None:
        """``bonfire.engine`` must not expose ``StageExecutor`` as an
        attribute — the re-export at ``bonfire.engine.__init__`` is
        gone."""
        from bonfire import engine as _e

        assert not hasattr(_e, "StageExecutor"), (
            "StageExecutor reappeared on the bonfire.engine surface. "
            "Wave 11 Lane E deleted the dead execution path. Reviving "
            "the class requires deleting this canary AND auditing "
            "Probe N+7 findings H1/H2/H3/M4 against the new code."
        )

    def test_stage_executor_not_in_public_all(self) -> None:
        """``bonfire.engine.__all__`` must not include ``StageExecutor``."""
        from bonfire import engine as _e

        assert "StageExecutor" not in _e.__all__, (
            "StageExecutor reappeared in bonfire.engine.__all__. "
            "Wave 11 Lane E removed the public re-export of the dead "
            "execution path."
        )
