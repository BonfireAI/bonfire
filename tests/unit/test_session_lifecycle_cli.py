# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""End-to-end CLI tests for the session-lifecycle verbs.

``bonfire status`` / ``bonfire resume`` / ``bonfire handoff`` were release-day
stubs that only echoed an absence-of-state line. These tests pin their real
behaviour against a populated checkpoint store, and guard the honest
empty-store path (no session persisted yet).

The store directory is redirected via ``BONFIRE_CHECKPOINT_DIR`` so the tests
never touch the operator's ``~/.bonfire``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.engine.pipeline import PipelineResult
from bonfire.models.envelope import Envelope
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.session.store import CHECKPOINT_DIR_ENV_VAR, SessionStore

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture
def store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "checkpoints"
    monkeypatch.setenv(CHECKPOINT_DIR_ENV_VAR, str(path))
    return path


def _seed(path: Path, session_id: str, *, plan: str = "standard_build", cost: float = 0.9) -> None:
    store = SessionStore(checkpoint_dir=path)
    completed = {
        "scout": Envelope(task="research", result="ok", cost_usd=cost / 2),
        "knight": Envelope(task="tests", result="ok", cost_usd=cost / 2),
    }
    plan_obj = WorkflowPlan(
        name=plan,
        workflow_type=WorkflowType.STANDARD,
        stages=[
            StageSpec(name="scout", agent_name="researcher"),
            StageSpec(name="knight", agent_name="tester"),
        ],
        task_description="ship a tested refactor",
    )
    store.save(
        PipelineResult(success=True, session_id=session_id, stages=completed, total_cost_usd=cost),
        plan_obj,
    )


class TestStatus:
    def test_empty_store_is_honest(self, store_dir: Path) -> None:
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "no active session" in result.output.lower() or "no session" in result.output.lower()

    def test_reports_latest_session(self, store_dir: Path) -> None:
        _seed(store_dir, "ses_status", cost=1.23)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "ses_status" in result.output
        assert "standard_build" in result.output
        assert "1.23" in result.output

    def test_reports_stage_progress(self, store_dir: Path) -> None:
        _seed(store_dir, "ses_progress")
        result = runner.invoke(app, ["status"])
        # 2 of the standard_build stages are done; the count must surface.
        assert "2" in result.output


class TestResume:
    def test_nothing_to_resume_is_honest(self, store_dir: Path) -> None:
        result = runner.invoke(app, ["resume"])
        assert result.exit_code == 0
        assert "no session" in result.output.lower() or "nothing to resume" in result.output.lower()

    def test_resume_loads_checkpoint_and_names_remaining(self, store_dir: Path) -> None:
        _seed(store_dir, "ses_resume")
        result = runner.invoke(app, ["resume"])
        assert result.exit_code == 0
        assert "ses_resume" in result.output
        # The plan is known (standard_build) so the verb must surface what is
        # left to re-enter, not silently no-op.
        assert "remaining" in result.output.lower() or "resume" in result.output.lower()

    def test_resume_unknown_plan_is_honest(self, store_dir: Path) -> None:
        _seed(store_dir, "ses_badplan", plan="not_a_real_plan")
        result = runner.invoke(app, ["resume"])
        # Cannot reconstruct an unregistered plan; must fail loudly, not lie.
        assert result.exit_code != 0
        assert "not_a_real_plan" in result.output


class TestHandoff:
    def test_no_session_is_honest(self, store_dir: Path) -> None:
        result = runner.invoke(app, ["handoff"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "generated" not in output_lower
        assert "no session" in output_lower or "not" in output_lower

    def test_handoff_emits_document(self, store_dir: Path) -> None:
        _seed(store_dir, "ses_handoff", cost=2.0)
        result = runner.invoke(app, ["handoff"])
        assert result.exit_code == 0
        assert "ses_handoff" in result.output
        assert "standard_build" in result.output
        assert "2.00" in result.output
        # It is a markdown handoff document.
        assert "#" in result.output

    def test_handoff_help_still_exits_zero(self) -> None:
        result = runner.invoke(app, ["handoff", "--help"])
        assert result.exit_code == 0
