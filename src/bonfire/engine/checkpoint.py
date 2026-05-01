"""Checkpoint persistence for pipeline state save/restore.

Provides atomic JSON persistence of pipeline results, enabling
resume-from-checkpoint across sessions.

Module-level ``os`` import is load-bearing: the canonical test
``test_save_is_atomic_via_tmp_and_replace`` patches
``bonfire.engine.checkpoint.os.replace``, so a lazy import would break
the patch. Atomic writes via tmp+replace guarantee no half-written
checkpoint files on crash.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path  # noqa: TC003 -- runtime use in constructor
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from bonfire.models.envelope import Envelope  # noqa: TC001 -- Pydantic needs runtime access

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from bonfire.engine.pipeline import PipelineResult
    from bonfire.models.plan import WorkflowPlan


# ---------------------------------------------------------------------------
# CheckpointData -- frozen Pydantic model
# ---------------------------------------------------------------------------


class CheckpointData(BaseModel):
    """Immutable snapshot of pipeline state at a point in time."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    plan_name: str
    task_description: str = ""
    completed: dict[str, Envelope]
    total_cost_usd: float
    timestamp: float
    checkpoint_version: int = 1


# ---------------------------------------------------------------------------
# CheckpointSummary -- frozen Pydantic model
# ---------------------------------------------------------------------------


class CheckpointSummary(BaseModel):
    """Lightweight summary for listing checkpoints without full envelope data."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    plan_name: str
    timestamp: float
    stages_completed: int
    total_cost_usd: float


# ---------------------------------------------------------------------------
# CheckpointManager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """Manages checkpoint persistence to a directory of JSON files.

    Each checkpoint is stored as ``{session_id}.json``. Writes use an atomic
    pattern: data is written to a ``.tmp`` file first, then ``os.replace()``
    moves it into place -- guaranteeing no corrupt files on crash.
    """

    def __init__(self, checkpoint_dir: Path) -> None:
        self._dir = checkpoint_dir

    def save(
        self,
        session_id: str,
        result: PipelineResult,
        plan: WorkflowPlan,
    ) -> Path:
        """Persist pipeline state to JSON with atomic write.

        Creates the checkpoint directory if it does not exist.
        Returns the path to the written checkpoint file.
        """
        self._dir.mkdir(parents=True, exist_ok=True)

        data = CheckpointData(
            session_id=session_id,
            plan_name=plan.name,
            task_description=plan.task_description,
            completed=dict(result.stages),
            total_cost_usd=result.total_cost_usd,
            timestamp=time.time(),
        )

        final_path = self._dir / f"{session_id}.json"
        tmp_path = self._dir / f"{session_id}.json.tmp"

        payload = json.dumps(data.model_dump(mode="json"), indent=2)
        tmp_path.write_text(payload)
        os.replace(str(tmp_path), str(final_path))

        return final_path

    def load(self, session_id: str) -> CheckpointData:
        """Load a checkpoint by session ID.

        Raises FileNotFoundError if the checkpoint file does not exist.
        """
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            msg = f"No checkpoint found for session '{session_id}' at {path}"
            raise FileNotFoundError(msg)

        raw = json.loads(path.read_text())
        return CheckpointData.model_validate(raw)

    def latest(self) -> CheckpointData | None:
        """Return the most recent checkpoint by timestamp, or None if empty."""
        checkpoints = self._load_all()
        if not checkpoints:
            return None
        return max(checkpoints, key=lambda c: c.timestamp)

    def list_checkpoints(self) -> list[CheckpointSummary]:
        """Return summaries of all checkpoints, sorted by timestamp descending."""
        checkpoints = self._load_all()
        summaries = [
            CheckpointSummary(
                session_id=c.session_id,
                plan_name=c.plan_name,
                timestamp=c.timestamp,
                stages_completed=len(c.completed),
                total_cost_usd=c.total_cost_usd,
            )
            for c in checkpoints
        ]
        return sorted(summaries, key=lambda s: s.timestamp, reverse=True)

    # -- Private helpers -----------------------------------------------------

    def _load_all(self) -> list[CheckpointData]:
        """Load all checkpoint files from the directory.

        Corrupt files (malformed JSON, schema violations, read errors) are
        skipped with a ``logger.warning`` rather than poisoning the entire
        scan. This ensures that one bad checkpoint file does not break
        ``latest()`` or ``list_checkpoints()`` when valid checkpoints exist
        alongside.
        """
        if not self._dir.exists():
            return []
        results: list[CheckpointData] = []
        for path in self._dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text())
                results.append(CheckpointData.model_validate(raw))
            except (json.JSONDecodeError, ValidationError, OSError) as exc:
                logger.warning(
                    "Skipping corrupt checkpoint file %s: %s",
                    path,
                    exc,
                )
                continue
        return results
