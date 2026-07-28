# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Shared read-layer over the persisted checkpoint store.

The three session-lifecycle verbs — ``bonfire status``, ``bonfire resume``,
and ``bonfire handoff`` — all answer the same underlying question: *what did
the last (or a named) Bonfire run leave behind on disk?* Rather than have each
command reach into :class:`~bonfire.engine.checkpoint.CheckpointManager`
independently and re-derive the on-disk location three times,
:class:`SessionStore` is the single place that:

* resolves the checkpoint directory once (``BONFIRE_CHECKPOINT_DIR`` env
  override first, then the ``~/.bonfire/checkpoints`` default — the same
  ``~/.bonfire/<subsystem>`` convention the cost ledger and personas already
  follow), and
* exposes the three lookups the verbs need (``latest``, ``load``,
  ``summaries``) plus the two writes (``save`` for a finished run,
  ``save_progress`` for one still going) so every read and every write resolves
  the same location.

The verbs themselves stay thin: they format what the store returns. Keeping the
location logic here means a future change to where checkpoints live is a
one-line edit, not a three-command sweep.

``save_progress`` is the producer side, and it went missing for a release:
``save`` had no caller anywhere in ``src/bonfire/`` and the pipeline had no
write site, so the three verbs above read a store that a real ``bonfire run``
never wrote to. The composition root now injects this class into the engine as
its checkpoint sink.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.engine.checkpoint import CheckpointManager

if TYPE_CHECKING:
    from bonfire.engine.checkpoint import CheckpointData, CheckpointSummary
    from bonfire.engine.pipeline import PipelineResult
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import WorkflowPlan

#: Environment variable that overrides the checkpoint directory. Mirrors the
#: ``BONFIRE_COST_LEDGER_PATH`` override the cost CLI already honours, so tests
#: and operators steer persistence the same way across subsystems.
CHECKPOINT_DIR_ENV_VAR = "BONFIRE_CHECKPOINT_DIR"

#: Default on-disk home for checkpoints, under the shared ``~/.bonfire`` root
#: (alongside ``~/.bonfire/cost`` and ``~/.bonfire/personas``).
DEFAULT_CHECKPOINT_DIR: Path = Path.home() / ".bonfire" / "checkpoints"


def _resolve_checkpoint_dir(explicit: Path | None) -> Path:
    """Pick the checkpoint directory: explicit arg, then env, then default."""
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(CHECKPOINT_DIR_ENV_VAR)
    if env_value:
        return Path(env_value)
    return DEFAULT_CHECKPOINT_DIR


class SessionStore:
    """Read/write access to persisted sessions at a single resolved location."""

    def __init__(self, checkpoint_dir: Path | None = None) -> None:
        self._dir = _resolve_checkpoint_dir(checkpoint_dir)
        self._manager = CheckpointManager(self._dir)

    @property
    def checkpoint_dir(self) -> Path:
        """The resolved directory checkpoints are read from and written to."""
        return self._dir

    def latest(self) -> CheckpointData | None:
        """The most recent persisted session, or ``None`` if the store is empty."""
        return self._manager.latest()

    def load(self, session_id: str) -> CheckpointData:
        """Load one persisted session by id. Raises ``FileNotFoundError`` if absent."""
        return self._manager.load(session_id)

    def summaries(self) -> list[CheckpointSummary]:
        """Lightweight summaries of every persisted session, newest first."""
        return self._manager.list_checkpoints()

    def save(self, result: PipelineResult, plan: WorkflowPlan) -> Path:
        """Persist a pipeline result so the verbs (and tests) can read it back."""
        return self._manager.save(result.session_id, result, plan)

    def save_progress(
        self,
        session_id: str,
        stages: dict[str, Envelope],
        total_cost_usd: float,
        plan: WorkflowPlan,
    ) -> Path:
        """Persist a run that is still going, from the facts the engine holds.

        This is the write side of the three lifecycle verbs, and it is what
        :class:`~bonfire.engine.pipeline.PipelineEngine` calls at each stage-group
        boundary. It exists separately from :meth:`save` because a run in
        progress has no :class:`~bonfire.engine.pipeline.PipelineResult` to hand
        over: building one at the call site would mean the engine stamping a
        ``success`` value onto a question it has not answered yet. Constructing
        the snapshot here keeps that decision with the layer that knows what a
        stored record means.

        ``success=False`` is therefore chosen here and is deliberate rather
        than incidental. It is not persisted -- :class:`CheckpointData` records
        the completed stages, the plan and the spend, and nothing else -- but
        an in-progress snapshot must not be constructed claiming it finished.

        Durability comes from :meth:`CheckpointManager.save`, which writes a
        tmp file and ``os.replace``s it into position. That matters more here
        than on the terminal write: this method is called repeatedly while the
        run is alive, so an interruption during a write is an ordinary
        outcome, and it must leave either the previous checkpoint or the new
        one -- never a truncated file naming stages that did not finish.
        """
        from bonfire.engine.pipeline import PipelineResult

        snapshot = PipelineResult(
            success=False,
            session_id=session_id,
            stages=stages,
            total_cost_usd=total_cost_usd,
        )
        return self._manager.save(session_id, snapshot, plan)
