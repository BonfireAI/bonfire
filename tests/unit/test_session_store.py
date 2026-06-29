# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the shared session-read plumbing (``bonfire.session.store``).

``SessionStore`` is the single read-layer the three session-lifecycle verbs
(``status`` / ``resume`` / ``handoff``) share. It resolves the on-disk
checkpoint directory (env override first, then the ``~/.bonfire/checkpoints``
default), wraps :class:`~bonfire.engine.checkpoint.CheckpointManager`, and
exposes the lookups the verbs need: ``latest``, ``load``, and ``summaries``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bonfire.engine.pipeline import PipelineResult
from bonfire.models.envelope import Envelope
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.session.store import (
    CHECKPOINT_DIR_ENV_VAR,
    DEFAULT_CHECKPOINT_DIR,
    SessionStore,
)

if TYPE_CHECKING:
    pass


def _plan(name: str = "standard_build") -> WorkflowPlan:
    return WorkflowPlan(
        name=name,
        workflow_type=WorkflowType.STANDARD,
        stages=[StageSpec(name="scout", agent_name="researcher")],
        task_description="ship the checkout refactor",
    )


def _result(session_id: str, *, stages: int = 1, cost: float = 0.5) -> PipelineResult:
    completed = {
        f"stage_{i}": Envelope(task=f"stage {i}", result="done", cost_usd=cost / max(stages, 1))
        for i in range(stages)
    }
    return PipelineResult(
        success=True,
        session_id=session_id,
        stages=completed,
        total_cost_usd=cost,
    )


class TestCheckpointDirResolution:
    def test_default_dir_is_under_dot_bonfire(self) -> None:
        assert DEFAULT_CHECKPOINT_DIR == Path.home() / ".bonfire" / "checkpoints"

    def test_env_var_overrides_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CHECKPOINT_DIR_ENV_VAR, str(tmp_path))
        store = SessionStore()
        assert store.checkpoint_dir == tmp_path

    def test_explicit_dir_beats_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CHECKPOINT_DIR_ENV_VAR, str(tmp_path / "env"))
        explicit = tmp_path / "explicit"
        store = SessionStore(checkpoint_dir=explicit)
        assert store.checkpoint_dir == explicit


class TestSessionStoreLookups:
    def test_latest_is_none_when_empty(self, tmp_path: Path) -> None:
        store = SessionStore(checkpoint_dir=tmp_path)
        assert store.latest() is None

    def test_latest_returns_most_recent(self, tmp_path: Path) -> None:
        store = SessionStore(checkpoint_dir=tmp_path)
        store.save(_result("ses_old"), _plan())
        store.save(_result("ses_new"), _plan())
        latest = store.latest()
        assert latest is not None
        assert latest.session_id == "ses_new"

    def test_load_roundtrips_a_saved_session(self, tmp_path: Path) -> None:
        store = SessionStore(checkpoint_dir=tmp_path)
        store.save(_result("ses_abc", stages=3, cost=1.25), _plan("debug"))
        data = store.load("ses_abc")
        assert data.session_id == "ses_abc"
        assert data.plan_name == "debug"
        assert len(data.completed) == 3
        assert data.total_cost_usd == pytest.approx(1.25)

    def test_load_missing_raises(self, tmp_path: Path) -> None:
        store = SessionStore(checkpoint_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            store.load("nope")

    def test_summaries_sorted_newest_first(self, tmp_path: Path) -> None:
        store = SessionStore(checkpoint_dir=tmp_path)
        store.save(_result("ses_1"), _plan())
        store.save(_result("ses_2"), _plan())
        summaries = store.summaries()
        assert [s.session_id for s in summaries] == ["ses_2", "ses_1"]

    def test_summaries_empty_when_no_dir(self, tmp_path: Path) -> None:
        store = SessionStore(checkpoint_dir=tmp_path / "absent")
        assert store.summaries() == []
