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
  ``summaries``) plus a ``save`` shim so callers and tests persist through the
  same resolved location.

The verbs themselves stay thin: they format what the store returns. Keeping the
location logic here means a future change to where checkpoints live is a
one-line edit, not a three-command sweep.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from bonfire.engine.checkpoint import CheckpointManager

if TYPE_CHECKING:
    from bonfire.engine.checkpoint import CheckpointData, CheckpointSummary
    from bonfire.engine.pipeline import PipelineResult
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
